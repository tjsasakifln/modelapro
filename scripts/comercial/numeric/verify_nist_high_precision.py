#!/usr/bin/env python3
"""Reconstruct all vendored NIST StRD LLS results with Decimal arithmetic.

This diagnostic is independent of NumPy, SciPy, BLAS and the repository's QR
oracle.  It reads decimal tokens from the vendored NIST files, solves the normal
equations at 100 decimal digits, and checks beta, residual sigma and coefficient
standard deviations against the resolution of NIST's published values.

Normal equations are unsuitable for the binary64 oracle because they square the
condition number.  At 100 decimal digits they retain ample headroom even for
Filip and provide a deliberately different path for this verification.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
from pathlib import Path
import re
import sys


PRECISION = 100
CERTIFIED_SIGNIFICANT_DIGITS = 15
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"
PARAM = re.compile(rf"^\s*(B\d+)\s+({NUM})\s+({NUM})\s*$")
RESIDUAL_SD = re.compile(rf"^\s*Standard Deviation\s+({NUM})\s*$")
RESIDUAL_SS = re.compile(rf"^\s*Residual\s+\d+\s+({NUM})\s+({NUM})")
BLOCK = re.compile(r"^\s*(Certified Values|Data)\s+\(lines\s+(\d+)\s+to\s+(\d+)\)", re.M)


def decimal(token: str) -> Decimal:
    return Decimal(token.replace("D", "E").replace("d", "e"))


def parse(path: Path):
    lines = path.read_text(encoding="ascii").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    spans = {m.group(1): (int(m.group(2)), int(m.group(3))) for m in BLOCK.finditer("\n".join(lines[:30]))}
    first, last = spans["Certified Values"]
    parameters = []
    sigma = residual_ss = None
    for line in lines[first - 1:last]:
        if match := PARAM.match(line):
            parameters.append((match.group(1), decimal(match.group(2)), decimal(match.group(3))))
        elif match := RESIDUAL_SD.match(line):
            sigma = decimal(match.group(1))
        elif match := RESIDUAL_SS.match(line):
            residual_ss = decimal(match.group(1))
    first, last = spans["Data"]
    rows = [[decimal(token) for token in line.split()] for line in lines[first - 1:last] if line.split()]
    if not parameters or sigma is None or residual_ss is None or not rows:
        raise ValueError(f"incomplete NIST parse: {path}")
    return parameters, sigma, residual_ss, rows


def design(parameters, rows):
    has_intercept = parameters[0][0] == "B0"
    p = len(parameters)
    x_count = len(rows[0]) - 1
    matrix = []
    for row in rows:
        xs = row[1:]
        if x_count == 1:
            last_degree = p - 1 if has_intercept else p
            values = ([Decimal(1)] if has_intercept else []) + [
                xs[0] ** degree for degree in range(1, last_degree + 1)
            ]
        else:
            values = ([Decimal(1)] if has_intercept else []) + xs
        if len(values) != p:
            raise ValueError(f"cannot infer design with p={p}, x_count={x_count}")
        matrix.append(values)
    return matrix


def dot(left, right):
    return sum((a * b for a, b in zip(left, right)), Decimal(0))


def transpose(matrix):
    return [list(column) for column in zip(*matrix)]


def solve(matrix, rhs):
    n = len(matrix)
    matrix_rhs = bool(rhs) and isinstance(rhs[0], list)
    rhs_matrix = rhs if matrix_rhs else [[value] for value in rhs]
    aug = [list(matrix[i]) + list(rhs_matrix[i]) for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if aug[pivot][col] == 0:
            raise ArithmeticError("singular high-precision normal matrix")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        scale = aug[col][col]
        aug[col] = [value / scale for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor:
                aug[row] = [a - factor * b for a, b in zip(aug[row], aug[col])]
    result = [row[n:] for row in aug]
    return result if matrix_rhs else [row[0] for row in result]


def reference_relative_rounding(value: Decimal) -> Decimal:
    if not value:
        return Decimal(0)
    adjusted = abs(value).adjusted()
    quantum = Decimal(10) ** (adjusted - CERTIFIED_SIGNIFICANT_DIGITS + 1)
    return quantum / (Decimal(2) * abs(value))


def relative_error(observed: Decimal, certified: Decimal) -> Decimal:
    return abs(observed - certified) / abs(certified)


def verify(path: Path):
    parameters, certified_sigma, certified_sse, rows = parse(path)
    X = design(parameters, rows)
    y = [row[0] for row in rows]
    xt = transpose(X)
    xtx = [[dot(left, right) for right in xt] for left in xt]
    xty = [dot(column, y) for column in xt]
    beta = solve(xtx, xty)
    identity = [[Decimal(int(i == j)) for j in range(len(xtx))] for i in range(len(xtx))]
    inverse = solve(xtx, identity)
    residuals = [yi - dot(row, beta) for yi, row in zip(y, X)]
    sse = dot(residuals, residuals)
    sigma = (sse / Decimal(len(y) - len(beta))).sqrt()
    sds = [sigma * inverse[j][j].sqrt() for j in range(len(beta))]

    checks = []
    for observed, (name, certified, certified_sd), observed_sd in zip(beta, parameters, sds):
        checks.append((f"beta({name})", observed, certified))
        if certified_sd:
            checks.append((f"sd({name})", observed_sd, certified_sd))
    if certified_sigma:
        checks.append(("sigma", sigma, certified_sigma))
    else:
        # A 100-digit solve of the exact polynomial data should leave only
        # Decimal elimination noise on certified exact-fit datasets.
        checks.append(("sigma-zero", sigma, Decimal(0)))

    failures = []
    published = [value for _name, estimate, sd in parameters for value in (estimate, sd)]
    published.extend((certified_sigma, certified_sse))
    for value in published:
        if value and len(value.as_tuple().digits) != CERTIFIED_SIGNIFICANT_DIGITS:
            failures.append(
                f"{path.stem}: expected {CERTIFIED_SIGNIFICANT_DIGITS} significant "
                f"digits in published value {value}, found {len(value.as_tuple().digits)}"
            )
    worst = Decimal(0)
    for label, observed, certified in checks:
        if certified:
            error = relative_error(observed, certified)
            allowed = reference_relative_rounding(certified) + Decimal("1e-80")
        else:
            error = abs(observed)
            allowed = Decimal("1e-70") * max(abs(value) for value in y)
        worst = max(worst, error)
        if error > allowed:
            failures.append(f"{path.stem} {label}: error={error:.6E} allowed={allowed:.6E}")

    # This independently checks that residual reconstruction and the certified
    # ANOVA quantity describe the same least-squares solution.
    sse_error = relative_error(sse, certified_sse) if certified_sse else abs(sse)
    sse_allowed = reference_relative_rounding(certified_sse) + Decimal("1e-80") if certified_sse else Decimal("1e-70")
    if sse_error > sse_allowed:
        failures.append(f"{path.stem} SSE: error={sse_error:.6E} allowed={sse_allowed:.6E}")
    return worst, failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "tests/fixtures/pro_workflow/nist_strd/data",
    )
    args = parser.parse_args(argv)
    paths = sorted(args.data_dir.glob("*.dat"))
    if len(paths) != 11:
        parser.error(f"expected 11 vendored .dat files under {args.data_dir}, found {len(paths)}")

    failures = []
    with localcontext() as context:
        context.prec = PRECISION
        for path in paths:
            worst, problems = verify(path)
            failures.extend(problems)
            print(f"{path.stem:9} worst_checked_error={worst:.6E}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"verified={len(paths)} precision={PRECISION} result=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
