"""NIST/ITL StRD linear-least-squares check of the independent OLS oracle.

Acceptance item MP-COM-20260912 / C06-A02.

WHAT THIS TEST PROVES, AND WHAT IT DOES NOT
-------------------------------------------
It proves that `tests/fixtures/pro_workflow/ols_oracle.py` reproduces NIST's
certified least-squares numbers to the accuracy the conditioning of each input
permits. That is an arithmetic statement about the oracle.

It is *not a certification of MODELA PRO*. NIST has not examined, tested,
endorsed or approved this product. StRD is not ABNT, not NBR 14653-2, not a
normative authority of any kind, and contains no real-estate data. Nothing here
supports a claim of external validation, accreditation or institutional
acceptance. See `tests/fixtures/pro_workflow/nist_strd/PROVENANCE.md`.

HOW SHARP IS IT? -- READ THIS BEFORE QUOTING A PASS
---------------------------------------------------
The pre-registered floors are a bound on what double-precision arithmetic could
be expected to achieve. The oracle beats them by factors of 1e2 to 2e5 (Filip:
floor 1.42e-04 vs achieved 6.24e-10; Wampler5: 3.98e-07 vs 4.34e-10; Longley:
7.60e-10 vs 5.66e-13). So the pre-registered tier alone verifies "NOT
CATASTROPHICALLY WRONG", not "reproduces the certified digits": corrupting
Longley's certified B1 by 1e-6 relative passes every pre-registered assertion in
this file. That looseness is intrinsic to a worst-case bound and is not a defect
in the bound; it is a limit on what a pass here means, and it is on the record
in PROVENANCE.md section 4.3 with the full achieved-vs-floor margin table.

Two further tiers narrow the gap, and each is labelled by what it actually is:

  * `sd_rel_floor_qr` -- derived from the ORACLE'S ALGORITHM (QR, never X'X), not
    from observed errors, but derived AFTER the first run, so NOT pre-registered.
  * `EMPIRICAL_REGRESSION_CEILINGS` -- MEASURED on 2026-09-11 and multiplied by
    100. No theoretical authority at all. A regression tripwire, nothing more.

Never present either as pre-registered, and never present any of it as a NIST
tolerance. NIST publishes certified values; every tolerance here is ours.

PRE-REGISTERED TOLERANCES
-------------------------
Frozen literals in `nist_strd/datasets.py`, derived by a fixed rule from the
condition number of the column-equilibrated design matrix and the certified
residual size, both computed from NIST inputs alone before any oracle output
existed:

    digits(A)    = max(0, 15 - log10(A))              # 15 ~ digits of a double
    rel_floor(A) = min(1.0, 10 ** -(digits(A) - 1))   # 1 digit of margin
    beta                 -> A = kappa_eq + kappa_eq**2 * rho  (Higham, ASNA 20.1)
    sigma-hat and R^2    -> A = kappa_eq
    parameter std devs   -> A = kappa_eq**2   (worst case; superseded below)

The min(1.0, ...) clamp is part of the rule and bites on exactly one literal
(Filip's `sd_rel_floor`). `test_every_frozen_floor_reproduces_the_stated_rule`
re-derives all 44 floors from kappa_eq and rho and fails if any literal
disagrees, so the rule and the literals cannot drift apart unnoticed.

THE METRIC THE FLOORS APPLY TO -- AND A CORRECTION, DISCLOSED IN FULL
---------------------------------------------------------------------
Theorem 20.1 bounds a NORMWISE relative error, of the EQUILIBRATED solution.
The first version of this test asserted the floors against a componentwise
relative error in RAW coordinates, which is a different quantity. Thirteen
coefficient comparisons across six datasets missed: Norris[B0], Pontius[B0],
Wampler1[B0,B1], Wampler3[B0,B1,B2], Wampler4[B0,B1,B2], Wampler5[B0,B1,B2].
(An earlier revision of this docstring claimed every failure was on B0. That was
false. The true pattern is reconstructed and asserted by
`test_v1_metric_failure_pattern_is_as_documented`.)

The signature that identifies the cause is not "B0" but the ORDERING: on every
dataset the failing set is exactly a PREFIX of the coefficients ranked by
||D*beta_cert|| / |D_jj*beta_cert_j| descending -- which is precisely the factor
by which a normwise bound and a componentwise metric differ. Wampler2, with the
same n=21, p=6 and kappa_eq=2220 as Wampler1/3/4/5, missed nothing at all. See
PROVENANCE.md section 4.1.

The correction changes the METRIC to the one the bound actually governs. Not one
pre-registered tolerance was changed: every floor in datasets.py is the frozen
literal, byte for byte. The primary assertion is now

    rel_eq = ||D (beta_hat - beta_cert)||_2 / ||D beta_cert||_2   <=   beta_rel_floor

with D = diag(column norms of the raw design matrix), the same D used to define
kappa_eq and rho. A secondary per-coefficient assertion is kept, because a norm
can hide one blown coefficient, using the scale the bound permits:

    floor_j = beta_rel_floor * ||D beta_cert||_2 / |D_jj * beta_cert_j|

No tolerance in this file may be relaxed after observing a result. If a dataset
misses its floor, that is a finding to report, not a number to adjust.

PARAMETER STANDARD DEVIATIONS -- A RETRACTED PREDICTION
-------------------------------------------------------
An earlier revision stated, as the rule's advance prediction, that Filip's
parameter standard deviations "carry no reproducible significant digit in
IEEE-754 double precision", and on that basis asserted nothing numeric for
eleven comparisons. THAT PREDICTION IS RETRACTED: it is empirically false. The
oracle reproduces Filip's certified sds to 8.5-10.1 correct digits (B0
rel=3.41e-09 through B8 rel=7.75e-11). What the pre-registered rule actually
predicted was a bound so weak it clamped to 1.0 -- a vacuous assertion, not a
measured limit, and the distinction was not drawn.

The reason the kappa_eq**2 worst case is not attained is structural, not lucky:
`fit_ols` never forms X'X. It takes a Householder QR and sets
xtx_inv = R^-1 R^-T, so sd_j = sigma * ||row_j(R^-1)||_2, and triangular
inversion is componentwise backward stable (Higham, ASNA 2nd ed., ch. 8 on
triangular systems), giving one factor of kappa_eq rather than two. The
confirming signature is in the data: across j, the sd errors are flat where the
beta errors are not. Wampler5 sd max/min = 3.9 against beta max/min = 20922;
Longley 3.5 against 197; Pontius 1.3 against 931. A kappa_eq**2 mechanism would
not look like that.

So all 33 sd comparisons are now asserted against
min(sd_rel_floor, sd_rel_floor_qr), which is sd_rel_floor_qr on every dataset.
The tightest comparison in the whole suite is Norris sd(B0): 1.752e-14 against a
floor of 2.801e-14, 63% of budget. If that trips it is a finding to investigate,
not a literal to move.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import math
import re
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures.pro_workflow import ols_oracle as oracle
from tests.fixtures.pro_workflow.nist_strd import datasets as strd

DATASETS = strd.DATASETS
NAMES = list(DATASETS)

# Pre-registered absolute scale for NIST-certified-ZERO quantities (Wampler1 and
# Wampler2 fit exactly, so residual sd and all parameter sds are certified
# 0.000000000000000 and no relative comparison is defined). With an exact fit the
# computed residual is pure roundoff, bounded by ~u * kappa_eq * ||y||
# = 2.2e-16 * 2.2e3 ~ 5e-13 relative; 1e-9 leaves three orders of margin while
# staying a real constraint. Frozen before the first run.
ZERO_SIGMA_REL = 1e-9
# R^2 certified exactly 1.0 on the exact-fit sets; compared absolutely.
R2_EXACT_ABS_TOL = 1e-12
# Self-consistency of the transcription itself (pure literal arithmetic).
ANOVA_SELF_CHECK_ABS_TOL = 1e-14

DATASETS_PATH = Path(inspect.getfile(strd)).resolve()
NIST_DIR = DATASETS_PATH.parent
DATA_DIR = NIST_DIR / strd.VENDORED_DATA_DIRNAME


# --------------------------------------------------------------------------
# helpers (test-side only; ols_oracle.py is never modified or monkeypatched)
# --------------------------------------------------------------------------

def _design_columns(spec):
    """Build the oracle's `columns` mapping for a StRD dataset.

    The raw monomial / raw predictor basis is used deliberately: NIST certifies
    coefficients for that basis, so centring or rescaling x would change what the
    certified numbers mean.
    """
    xcols = spec["x_columns"]
    if spec["design"] == "poly":
        assert len(xcols) == 1, spec["name"]
        x = np.asarray(xcols[0], dtype=float)
        degree = int(spec["degree"])
        if degree == 1:
            return {"x": x.tolist()}, ["x"]
        cols = {f"x^{d}": (x ** d).tolist() for d in range(1, degree + 1)}
        return cols, [f"x^{d}" for d in range(1, degree + 1)]
    cols = {f"x{j + 1}": list(map(float, col)) for j, col in enumerate(xcols)}
    return cols, [f"x{j + 1}" for j in range(len(xcols))]


def _fit(spec):
    cols, order = _design_columns(spec)
    return oracle.fit_ols(
        [float(v) for v in spec["y"]],
        cols,
        intercept=bool(spec["intercept"]),
        column_order=order,
    )


def _coefficient_sds(fit):
    sigma2 = float(fit["sigma2"])
    xtx_inv = np.asarray(fit["xtx_inv"], dtype=float)
    return [math.sqrt(sigma2 * float(xtx_inv[j, j])) for j in range(int(fit["p"]))]


def _r_squared(fit, intercept):
    """NIST certifies a CENTRED R^2 with an intercept and an UNCENTRED R^2
    without one. Verified against the certified ANOVA tables, not assumed --
    see `test_transcription_is_self_consistent` and PROVENANCE.md section 2."""
    y = np.asarray(fit["y"], dtype=float)
    sse = float(fit["sse"])
    total = float(np.sum((y - y.mean()) ** 2)) if intercept else float(np.sum(y ** 2))
    return 1.0 - sse / total


def _rel_error(observed, certified):
    if certified == 0.0:
        return float("inf") if observed != 0.0 else 0.0
    return abs(float(observed) - float(certified)) / abs(float(certified))


def _digits(rel):
    if rel == 0.0:
        return float("inf")
    if not math.isfinite(rel) or rel <= 0.0:
        return 0.0
    return max(0.0, -math.log10(rel))


def _assert_within(label, observed, certified, floor, spec):
    """Assert against a frozen floor; never widen it here.

    A floor of 1.0 or more is not a bound on anything (relative error 1.0 already
    means "not one correct digit"), so it is refused outright rather than silently
    turned into a finiteness check. An earlier revision of this file did exactly
    that for eleven Filip comparisons; the guard below is what stops it recurring.
    """
    assert 0.0 < floor < 1.0, (
        f"{spec['name']} {label}: refusing to assert against a vacuous floor "
        f"{floor!r}. A relative-error floor >= 1.0 constrains nothing. Derive a "
        f"real bound for this quantity or report it as unverifiable -- do not "
        f"degrade the comparison to a finiteness check."
    )
    rel = _rel_error(observed, certified)
    msg = (
        f"{spec['name']} {label}: certified={certified!r} observed={observed!r} "
        f"rel_err={rel:.3e} ({_digits(rel):.2f} correct digits) "
        f"floor={floor:.3e} "
        f"(kappa_eq={spec['kappa_equilibrated']:.3e})"
    )
    assert rel <= floor, msg
    return rel


def _rule_digits(amplification):
    return max(0.0, strd.DOUBLE_PRECISION_DIGITS - math.log10(amplification))


def _rule_floor(amplification):
    """The frozen rule, clamp included. See datasets.py for why the clamp exists."""
    raw = 10.0 ** -(_rule_digits(amplification) - strd.MARGIN_DIGITS)
    return min(strd.MAX_MEANINGFUL_RELATIVE_FLOOR, raw)


def _sd_floor(spec):
    """The binding parameter-standard-deviation floor.

    min(pre-registered kappa_eq**2 floor, post-hoc QR-structure kappa_eq floor).
    The QR one is tighter on every dataset, so it binds everywhere; the
    pre-registered literal is retained so the re-derivation test can still check
    it, and so a reader can see that nothing was loosened.
    """
    return min(float(spec["sd_rel_floor"]), float(spec["sd_rel_floor_qr"]))


def _column_norms(fit):
    """D = diag(||X_j||_2) of the RAW design matrix - the same equilibration used
    to define kappa_eq and rho in datasets.py."""
    return np.linalg.norm(np.asarray(fit["X"], dtype=float), axis=0)


def _equilibrated_scale_ratios(spec, fit):
    """||D beta_cert|| / |D_jj beta_cert_j| per coefficient.

    This is exactly the factor by which the v1 componentwise metric and the v2
    equilibrated normwise metric can differ, so it is the quantity that predicts
    which coefficients v1 flagged.
    """
    certified = np.array([e for _n, e, _sd in spec["certified"]["parameters"]], dtype=float)
    d = _column_norms(fit)
    scale = float(np.linalg.norm(d * certified))
    return [scale / abs(float(d[j]) * float(certified[j])) for j in range(len(certified))], scale


# --------------------------------------------------------------------------
# the vendored raw files: what makes the sha256 values falsifiable
# --------------------------------------------------------------------------

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"
_BLOCK_RANGE = re.compile(r"^\s*(Certified Values|Data)\s+\(lines\s+(\d+)\s+to\s+(\d+)\)", re.M)
_PARAM_LINE = re.compile(rf"^\s*(B\d+)\s+({_NUM})\s+({_NUM})\s*$")
_RESID_SD_LINE = re.compile(rf"^\s*Standard Deviation\s+({_NUM})\s*$")
_R2_LINE = re.compile(rf"^\s*R-Squared\s+({_NUM})\s*$")
_REGRESSION_LINE = re.compile(rf"^\s*Regression\s+(\d+)\s+({_NUM})\s+({_NUM})")
_RESIDUAL_LINE = re.compile(rf"^\s*Residual\s+(\d+)\s+({_NUM})\s+({_NUM})")


def _parse_nist_dat(text):
    """Re-parse a raw NIST StRD .dat file into certified values and data rows.

    Deliberately independent of `datasets.py`: it reads only the bytes NIST
    serves, using the line ranges the file's own header declares. Its output is
    compared to the transcribed literals with EXACT float equality, which is what
    turns those literals from "someone typed them" into a checked fact.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    spans = {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in _BLOCK_RANGE.finditer("\n".join(lines[:30]))
    }
    cert_first, cert_last = spans["Certified Values"]
    data_first, data_last = spans["Data"]

    certified = {"parameters": [], "residual_sd": None, "r_squared": None, "anova": {}}
    for line in lines[cert_first - 1:cert_last]:
        match = _PARAM_LINE.match(line)
        if match:
            certified["parameters"].append(
                (match.group(1), float(match.group(2)), float(match.group(3)))
            )
            continue
        match = _RESID_SD_LINE.match(line)
        if match:
            certified["residual_sd"] = float(match.group(1))
            continue
        match = _R2_LINE.match(line)
        if match:
            certified["r_squared"] = float(match.group(1))
            continue
        match = _REGRESSION_LINE.match(line)
        if match:
            certified["anova"]["regression_df"] = int(match.group(1))
            certified["anova"]["regression_ss"] = float(match.group(2))
            continue
        match = _RESIDUAL_LINE.match(line)
        if match:
            certified["anova"]["residual_df"] = int(match.group(1))
            certified["anova"]["residual_ss"] = float(match.group(2))
            continue

    rows = []
    for line in lines[data_first - 1:data_last]:
        tokens = line.split()
        if tokens:
            rows.append([float(tok) for tok in tokens])
    return certified, rows


@pytest.mark.parametrize("name", NAMES)
def test_vendored_dat_files_match_the_recorded_sha256(name):
    """Hash the vendored bytes against the recorded digest.

    Before the files were vendored, `sha256` in datasets.py was only ever compared
    to the same string repeated in PROVENANCE.md -- a circular assertion that could
    not fail for any reason a reader cares about. This one hashes actual bytes.
    Note the bytes are as NIST serves them, CRLF included; `data/.gitattributes`
    marks *.dat as binary so no checkout normalises them.
    """
    path = DATA_DIR / f"{name}.dat"
    assert path.is_file(), f"vendored NIST source file missing: {path}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == DATASETS[name]["sha256"], (
        f"{name}: vendored {path.name} hashes to {digest}, but datasets.py and "
        f"PROVENANCE.md record {DATASETS[name]['sha256']}. Either the file was "
        f"modified (check eol normalisation first) or the recorded digest is wrong."
    )


@pytest.mark.parametrize("name", NAMES)
def test_certified_literals_reparse_from_the_vendored_file(name):
    """Every transcribed literal must come back bit-identical from NIST's bytes.

    EXACT float equality, not a tolerance: the literals were copied verbatim from
    these files, so any difference at all is a transcription defect. This is the
    assertion that would catch a corrupted certified value -- the pre-registered
    accuracy floors are far too loose to (a 1e-9 relative change to a certified
    sum of squares passes every one of them).
    """
    spec = DATASETS[name]
    parsed, rows = _parse_nist_dat((DATA_DIR / f"{name}.dat").read_text(encoding="ascii"))
    cert = spec["certified"]

    assert len(parsed["parameters"]) == len(cert["parameters"]), name
    for got, stored in zip(parsed["parameters"], cert["parameters"]):
        assert got[0] == stored[0], f"{name}: parameter name {got[0]} != {stored[0]}"
        assert got[1] == stored[1], f"{name}: {got[0]} estimate {got[1]!r} != {stored[1]!r}"
        assert got[2] == stored[2], f"{name}: {got[0]} sd {got[2]!r} != {stored[2]!r}"
    assert parsed["residual_sd"] == cert["residual_sd"], name
    assert parsed["r_squared"] == cert["r_squared"], name
    for key in ("regression_df", "regression_ss", "residual_df", "residual_ss"):
        assert parsed["anova"][key] == cert["anova"][key], (
            f"{name}: ANOVA {key} {parsed['anova'][key]!r} != {cert['anova'][key]!r}"
        )

    assert len(rows) == spec["n_obs"], f"{name}: {len(rows)} data rows != {spec['n_obs']}"
    assert [row[0] for row in rows] == list(spec["y"]), f"{name}: y column mismatch"
    n_x = len(rows[0]) - 1
    assert n_x == len(spec["x_columns"]), f"{name}: {n_x} x columns != {len(spec['x_columns'])}"
    for j in range(n_x):
        assert [row[j + 1] for row in rows] == list(spec["x_columns"][j]), (
            f"{name}: x column {j + 1} mismatch against the vendored file"
        )


# --------------------------------------------------------------------------
# provenance / independence
# --------------------------------------------------------------------------

def test_reference_data_imports_no_product_code():
    tree = ast.parse(DATASETS_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    bad = [
        name
        for name in imported
        if name.split(".")[0] in {"modules", "backend", "frontend"}
    ]
    assert not bad, f"NIST reference data imports product code: {bad}"


def test_provenance_disclaims_certification_of_the_product():
    """Consistency of the two in-repo records, plus the disclaimers.

    Note what this does and does not establish: the sha256 half is a
    datasets.py-vs-PROVENANCE.md consistency check only, and would be circular on
    its own. What makes the digests falsifiable is
    `test_vendored_dat_files_match_the_recorded_sha256`, which hashes bytes.
    """
    doc = (NIST_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "not a certification of MODELA PRO" in doc
    assert "2026-09-11" in doc
    for name, spec in DATASETS.items():
        assert spec["sha256"] in doc, f"sha256 of {name} missing from PROVENANCE.md"
        assert spec["source_url"].rsplit("/", 1)[-1] in doc or name in doc


@pytest.mark.parametrize("name", NAMES)
def test_transcription_is_self_consistent(name):
    """Independent check that the certified block was parsed correctly.

    RegSS / (RegSS + ResidSS) from the ANOVA table must reproduce the separately
    transcribed certified R^2. A mis-parse of either block breaks this. It also
    pins the R^2 convention: for NoInt1/NoInt2 the implied total is sum(y**2),
    for the intercept sets it is sum((y - ybar)**2).
    """
    spec = DATASETS[name]
    cert = spec["certified"]
    anova = cert["anova"]
    total_ss = anova["regression_ss"] + anova["residual_ss"]
    implied_r2 = anova["regression_ss"] / total_ss
    assert abs(implied_r2 - cert["r_squared"]) <= ANOVA_SELF_CHECK_ABS_TOL, (
        f"{name}: ANOVA-implied R^2 {implied_r2!r} != certified {cert['r_squared']!r}"
    )

    y = np.asarray(spec["y"], dtype=float)
    assert len(y) == spec["n_obs"]
    assert len(cert["parameters"]) == spec["n_params"]
    assert anova["residual_df"] == spec["n_obs"] - spec["n_params"]

    expected_total = float(np.sum((y - y.mean()) ** 2)) if spec["intercept"] else float(np.sum(y ** 2))
    assert abs(expected_total - total_ss) <= 1e-8 * max(1.0, abs(total_ss)), (
        f"{name}: certified ANOVA total {total_ss!r} does not match the "
        f"{'centred' if spec['intercept'] else 'uncentred'} total {expected_total!r}"
    )


# --------------------------------------------------------------------------
# the frozen rule vs the frozen literals
# --------------------------------------------------------------------------

def test_every_frozen_floor_reproduces_the_stated_rule():
    """Diff the stated rule against the stored literals, mechanically.

    datasets.py advertises that its floors can be re-derived from kappa_eq and rho
    by one written-down rule. That is only a real property if something checks it:
    before this test existed, Filip's `sd_rel_floor` was 1.000e+00 where the rule
    as then written produced 1.000e+01, and nothing caught the discrepancy. The
    min(1.0, ...) clamp that reconciles them is now part of the documented rule.

    Literals are stored rounded (4 significant figures for floors, 3 decimals for
    the digit counts), so the comparison is against that same rounding.
    """
    problems = []
    for name, spec in DATASETS.items():
        kappa = float(spec["kappa_equilibrated"])
        rho = float(spec["rho_residual"])
        classes = (
            ("beta", kappa + kappa * kappa * rho, "beta_expected_digits", "beta_rel_floor"),
            ("proj", kappa, "proj_expected_digits", "proj_rel_floor"),
            ("sd", kappa * kappa, "sd_expected_digits", "sd_rel_floor"),
            ("sd_qr", kappa, "sd_qr_expected_digits", "sd_rel_floor_qr"),
        )
        for tag, amplification, digits_key, floor_key in classes:
            want_digits = round(_rule_digits(amplification), 3)
            want_floor = float(f"{_rule_floor(amplification):.3e}")
            if abs(want_digits - float(spec[digits_key])) > 5e-4:
                problems.append(
                    f"{name}.{digits_key}: rule gives {want_digits!r}, literal is {spec[digits_key]!r}"
                )
            if want_floor != float(spec[floor_key]):
                problems.append(
                    f"{name}.{floor_key}: rule gives {want_floor:.4e}, literal is {float(spec[floor_key]):.4e}"
                )
    assert not problems, (
        "frozen floors no longer match the documented rule -- fix whichever is "
        "actually wrong and say which; do not quietly align them:\n  "
        + "\n  ".join(problems)
    )


def test_no_frozen_floor_is_vacuous_for_an_asserted_quantity():
    """Every quantity this suite compares must have a floor that can go red.

    `sd_rel_floor` is allowed to be vacuous (it clamps to 1.0 on Filip) because it
    is superseded by `sd_rel_floor_qr`; what must never happen again is a quantity
    whose BINDING floor is >= 1.0, which is an assertion that cannot fail.
    """
    for name, spec in DATASETS.items():
        for key, value in (
            ("beta_rel_floor", float(spec["beta_rel_floor"])),
            ("proj_rel_floor", float(spec["proj_rel_floor"])),
            ("binding sd floor", _sd_floor(spec)),
        ):
            assert 0.0 < value < 1.0, f"{name}: {key} = {value!r} constrains nothing"


def test_v1_metric_failure_pattern_is_as_documented():
    """Reconstruct the withdrawn v1 metric and check the diagnosis it supports.

    PROVENANCE.md section 4.1 and this module's docstring justify the change from
    a raw componentwise metric to the equilibrated normwise one by the SHAPE of
    the v1 failures. That justification is load-bearing, so it executes here
    rather than living only in prose.

    The structural claim -- not the exact failure list, which has coefficients
    sitting at 73% of budget and would flip on a LAPACK difference for no
    substantive reason -- is:

      on every dataset, the set of v1 failures is a PREFIX of the coefficients
      ranked by ||D beta_cert|| / |D_jj beta_cert_j| descending.

    That ratio is exactly the normwise-vs-componentwise gap. A coefficient with a
    small ratio failing while one with a larger ratio passed would falsify the
    equilibration diagnosis, and this test would go red.
    """
    observed = {}
    for name, spec in DATASETS.items():
        fit = _fit(spec)
        beta = np.asarray(fit["beta"], dtype=float)
        params = spec["certified"]["parameters"]
        floor = float(spec["beta_rel_floor"])
        ratios, _scale = _equilibrated_scale_ratios(spec, fit)

        failed = [_rel_error(float(beta[j]), est) > floor for j, (_p, est, _s) in enumerate(params)]
        if any(failed):
            observed[name] = [params[j][0] for j, bad in enumerate(failed) if bad]

        order = sorted(range(len(params)), key=lambda j: -ratios[j])
        flags = [failed[j] for j in order]
        n_failed = sum(flags)
        assert flags[:n_failed] == [True] * n_failed and not any(flags[n_failed:]), (
            f"{name}: v1 failures are not a prefix of the equilibrated-scale ranking, "
            f"which falsifies the diagnosis in PROVENANCE.md section 4.1. "
            f"ranking={[params[j][0] for j in order]} "
            f"ratios={[f'{ratios[j]:.2e}' for j in order]} "
            f"failed={[int(f) for f in flags]}"
        )

    # Wampler2 shares n, p and kappa_eq exactly with Wampler1/3/4/5 and misses
    # nothing; that is what rules out a dimension-only c(n, p) explanation.
    assert "Wampler2" not in observed, (
        "Wampler2 now fails under v1 too. The rejection of the c(n,p) hypothesis in "
        "PROVENANCE.md section 4.1 rests on Wampler2 passing with identical n=21, "
        "p=6 and kappa_eq=2220; re-open that argument before touching anything else."
    )
    for shared in ("Wampler1", "Wampler3", "Wampler4", "Wampler5"):
        assert DATASETS[shared]["n_obs"] == DATASETS["Wampler2"]["n_obs"]
        assert DATASETS[shared]["n_params"] == DATASETS["Wampler2"]["n_params"]
        assert DATASETS[shared]["kappa_equilibrated"] == DATASETS["Wampler2"]["kappa_equilibrated"]

    print(f"[v1 metric, reconstructed] failures by dataset: {observed}")


# --------------------------------------------------------------------------
# the actual StRD comparisons
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_certified_parameter_estimates(name):
    """Primary: equilibrated normwise relative error vs the pre-registered floor."""
    spec = DATASETS[name]
    fit = _fit(spec)
    assert fit["n"] == spec["n_obs"]
    assert fit["p"] == spec["n_params"]
    assert fit["df"] == spec["certified"]["anova"]["residual_df"]

    beta = np.asarray(fit["beta"], dtype=float)
    certified = np.array([e for _n, e, _sd in spec["certified"]["parameters"]], dtype=float)
    d = _column_norms(fit)
    scale = float(np.linalg.norm(d * certified))
    rel_eq = float(np.linalg.norm(d * (beta - certified))) / scale
    floor = float(spec["beta_rel_floor"])

    per_param = ", ".join(
        f"{pname}={_rel_error(float(beta[j]), est):.2e}"
        for j, (pname, est, _sd) in enumerate(spec["certified"]["parameters"])
    )
    assert rel_eq <= floor, (
        f"{name}: equilibrated normwise beta error {rel_eq:.3e} "
        f"({_digits(rel_eq):.2f} correct digits) exceeds the pre-registered floor "
        f"{floor:.3e} derived from kappa_eq={spec['kappa_equilibrated']:.3e}, "
        f"rho={spec['rho_residual']:.3e}. Raw componentwise errors: {per_param}"
    )


@pytest.mark.parametrize("name", NAMES)
def test_certified_parameter_estimates_componentwise(name):
    """Secondary: per-coefficient, so a norm cannot hide one blown coefficient.

    The per-coefficient scale is what the normwise bound permits for that
    component; it is derived from the pre-registered floor and certified values
    only, and introduces no new tunable number.
    """
    spec = DATASETS[name]
    fit = _fit(spec)
    beta = np.asarray(fit["beta"], dtype=float)
    ratios, _scale = _equilibrated_scale_ratios(spec, fit)
    floor = float(spec["beta_rel_floor"])

    for j, (pname, estimate, _sd) in enumerate(spec["certified"]["parameters"]):
        if estimate == 0.0:  # no certified-zero estimates exist in StRD LLS today
            assert abs(float(beta[j])) <= ZERO_SIGMA_REL
            continue
        # Deliberately uncapped. If a ratio were large enough to push floor_j to
        # 1.0 or more, that coefficient would be unverifiable at this metric and
        # `_assert_within` refuses it loudly rather than pretending to check it.
        # The largest floor_j across all eleven datasets today is 0.427
        # (Wampler5 B0), so the guard does not fire.
        floor_j = floor * ratios[j]
        _assert_within(f"{pname} estimate", float(beta[j]), estimate, floor_j, spec)


@pytest.mark.parametrize("name", NAMES)
def test_certified_residual_standard_deviation_and_r_squared(name):
    spec = DATASETS[name]
    cert = spec["certified"]
    fit = _fit(spec)
    floor = float(spec["proj_rel_floor"])

    rms_y = float(np.sqrt(np.mean(np.asarray(spec["y"], dtype=float) ** 2)))
    certified_sigma = cert["residual_sd"]
    observed_sigma = float(fit["sigma"])
    if certified_sigma == 0.0:
        # Exact-fit sets (Wampler1/Wampler2): absolute floor tied to rms(y).
        assert observed_sigma <= ZERO_SIGMA_REL * rms_y, (
            f"{name} residual sd: certified exactly 0, observed {observed_sigma!r}, "
            f"pre-registered bound {ZERO_SIGMA_REL * rms_y:.3e}"
        )
    else:
        _assert_within("residual sd", observed_sigma, certified_sigma, floor, spec)

    observed_r2 = _r_squared(fit, bool(spec["intercept"]))
    certified_r2 = cert["r_squared"]
    if certified_r2 == 1.0:
        assert abs(observed_r2 - 1.0) <= R2_EXACT_ABS_TOL, (
            f"{name} R^2: certified exactly 1, observed {observed_r2!r}"
        )
    else:
        _assert_within("R^2", observed_r2, certified_r2, floor, spec)


@pytest.mark.parametrize("name", NAMES)
def test_certified_standard_deviations_of_estimates(name):
    """All 33 sd comparisons are numeric. None of them is a finiteness check.

    The binding floor is min(pre-registered kappa_eq**2, QR-structure kappa_eq);
    the QR one is tighter everywhere. See the module docstring for why the
    kappa_eq**2 worst case is not attained by this oracle, and for the retraction
    of the earlier claim that Filip's sds carry no reproducible digit -- they
    carry 8.5 to 10.1.
    """
    spec = DATASETS[name]
    fit = _fit(spec)
    sds = _coefficient_sds(fit)
    floor = _sd_floor(spec)
    rms_y = float(np.sqrt(np.mean(np.asarray(spec["y"], dtype=float) ** 2)))
    xtx_inv = np.asarray(fit["xtx_inv"], dtype=float)

    for j, (pname, _est, certified_sd) in enumerate(spec["certified"]["parameters"]):
        if certified_sd == 0.0:
            bound = ZERO_SIGMA_REL * rms_y * math.sqrt(abs(float(xtx_inv[j, j])))
            assert sds[j] <= bound, (
                f"{name} sd({pname}): certified exactly 0, observed {sds[j]!r}, "
                f"pre-registered bound {bound:.3e}"
            )
            continue
        _assert_within(f"sd({pname})", sds[j], certified_sd, floor, spec)


# --------------------------------------------------------------------------
# EMPIRICAL regression tripwires -- NOT pre-registered. See datasets.py.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(strd.EMPIRICAL_REGRESSION_CEILINGS))
def test_empirical_regression_tripwire(name):
    """Measured-on-2026-09-11 ceilings, 100x the observed error. NOT a bound.

    These exist only because the pre-registered floors are 1e2 to 2e5 looser than
    what the oracle achieves, so they would not notice a real numerical
    regression. They have no theoretical standing and must never be quoted as
    pre-registered, as certified, or as a NIST tolerance.

    A trip is a signal to investigate and to record the new measurement
    explicitly, not a licence to widen the literal.
    """
    spec = DATASETS[name]
    ceilings = strd.EMPIRICAL_REGRESSION_CEILINGS[name]
    fit = _fit(spec)
    cert = spec["certified"]

    beta = np.asarray(fit["beta"], dtype=float)
    certified = np.array([e for _n, e, _sd in cert["parameters"]], dtype=float)
    d = _column_norms(fit)
    scale = float(np.linalg.norm(d * certified))
    measured = {
        "beta_rel_eq": float(np.linalg.norm(d * (beta - certified))) / scale,
        "sigma_rel": (
            _rel_error(float(fit["sigma"]), cert["residual_sd"])
            if cert["residual_sd"] != 0.0 else None
        ),
        "r2_rel": (
            _rel_error(_r_squared(fit, bool(spec["intercept"])), cert["r_squared"])
            if cert["r_squared"] != 1.0 else None
        ),
        "sd_rel_max": None,
    }
    sds = _coefficient_sds(fit)
    sd_rels = [
        _rel_error(sds[j], csd)
        for j, (_p, _e, csd) in enumerate(cert["parameters"])
        if csd != 0.0
    ]
    if sd_rels:
        measured["sd_rel_max"] = max(sd_rels)

    for key, ceiling in ceilings.items():
        value = measured[key]
        assert (ceiling is None) == (value is None), (
            f"{name}.{key}: ceiling {ceiling!r} and measurement {value!r} disagree on "
            f"whether this quantity has a defined relative error"
        )
        if ceiling is None:
            continue
        assert value <= ceiling, (
            f"{name} {key}: {value:.4e} exceeds the EMPIRICAL regression ceiling "
            f"{ceiling:.1e} (= {strd.EMPIRICAL_CEILING_MARGIN:.0f}x the value measured on "
            f"{strd.EMPIRICAL_CEILING_MEASURED_ON}, rounded up). This is a tripwire, not a "
            f"bound: the pre-registered floor here is far looser and still passes. "
            f"Investigate and record the new measurement -- do not widen the literal silently."
        )


# --------------------------------------------------------------------------
# no-intercept handling (NoInt1 / NoInt2)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["NoInt1", "NoInt2"])
def test_no_intercept_datasets_are_fitted_without_an_intercept(name):
    """The sharpest available check is the residual degrees of freedom.

    NIST certifies residual df = n - 1 for these one-parameter, no-intercept
    models (10 for NoInt1, 2 for NoInt2). A wrongly-intercepted fit would give
    n - 2 (9 and 1) and a different B1 entirely.
    """
    spec = DATASETS[name]
    assert spec["intercept"] is False
    assert spec["model"].startswith("y = B1*x")

    fit = _fit(spec)
    assert fit["names"] == ["x"], fit["names"]
    assert "const" not in fit["names"]
    assert fit["p"] == 1
    assert fit["df"] == spec["n_obs"] - 1 == spec["certified"]["anova"]["residual_df"]
    assert np.asarray(fit["X"]).shape == (spec["n_obs"], 1)

    # And the fit really is the no-intercept one, not a coincidence of df.
    certified_b1 = spec["certified"]["parameters"][0][1]
    _assert_within("B1 estimate", float(fit["beta"][0]), certified_b1, float(spec["beta_rel_floor"]), spec)

    # An intercept-bearing fit on the same data must disagree materially, which
    # is what makes the no-intercept requirement meaningful rather than cosmetic.
    cols, order = _design_columns(spec)
    with_intercept = oracle.fit_ols(
        [float(v) for v in spec["y"]], cols, intercept=True, column_order=order
    )
    assert with_intercept["df"] == spec["n_obs"] - 2
    assert _rel_error(float(with_intercept["beta"][1]), certified_b1) > 1e-3, (
        f"{name}: an intercept-bearing fit reproduced the no-intercept certified "
        f"B1, so this test would not detect a wrong design matrix"
    )


# --------------------------------------------------------------------------
# ill-conditioned sets: the oracle must still form a fit at all
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Longley", "Filip", "Wampler5"])
def test_hardest_sets_are_fitted_rather_than_refused(name):
    """`fit_ols` guards on abs(diag(R)) < 1e-12 and would decline a design it
    judges rank-deficient. On the three hardest StRD designs it must not: a
    refusal is a different outcome from a wrong answer, and both are reportable,
    so the distinction is asserted rather than left implicit."""
    spec = DATASETS[name]
    try:
        fit = _fit(spec)
    except oracle.OracleError as exc:  # pragma: no cover - outcome is data dependent
        pytest.fail(
            f"{name}: oracle declined to fit (rank guard) with kappa_eq="
            f"{spec['kappa_equilibrated']:.3e}: {exc}. Documented numerical limit "
            f"of double-precision QR on this design, not a silent wrong answer."
        )
    assert np.all(np.isfinite(np.asarray(fit["beta"], dtype=float)))
    assert fit["df"] == spec["certified"]["anova"]["residual_df"]
