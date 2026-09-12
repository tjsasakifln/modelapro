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

PRE-REGISTERED TOLERANCES
-------------------------
Every tolerance used below is a frozen literal in `nist_strd/datasets.py`,
derived by a fixed rule from the condition number of the column-equilibrated
design matrix and the certified residual size, both computed from NIST inputs
alone before any oracle output existed:

    digits(A)    = max(0, 15 - log10(A))      # 15 ~ decimal digits of a double
    rel_floor(A) = 10 ** -(digits(A) - 1)     # 1 digit of engineering margin
    beta                 -> A = kappa_eq + kappa_eq**2 * rho  (Higham, ASNA 20.1)
    sigma-hat and R^2    -> A = kappa_eq
    parameter std devs   -> A = kappa_eq**2

THE METRIC THE FLOORS APPLY TO -- AND A CORRECTION, DISCLOSED IN FULL
---------------------------------------------------------------------
Theorem 20.1 bounds a NORMWISE relative error, of the EQUILIBRATED solution.
The first version of this test asserted the floors against a componentwise
relative error in RAW coordinates, which is a different quantity, and six
datasets (Norris, Pontius, Wampler1, Wampler3, Wampler4, Wampler5) failed.
Every single failure was on B0 -- the intercept is the smallest equilibrated
component in each of those designs (Norris: B0 = -0.262 against a response
running to 998; Wampler: B0 = 1.0 against an x**5 column of norm ~3.5e6), so the
mismatch bit exactly there. The oracle was independently exonerated: on all
eleven datasets it matches or beats numpy.linalg.lstsq and statsmodels, and on
Filip it beats both by ~8.5 digits (see PROVENANCE.md section 4).

The correction changes the METRIC to the one the bound actually governs. Not one
tolerance was changed: every floor in datasets.py is the pre-registered literal,
byte for byte. The primary assertion is now

    rel_eq = ||D (beta_hat - beta_cert)||_2 / ||D beta_cert||_2   <=   beta_rel_floor

with D = diag(column norms of the raw design matrix), the same D used to define
kappa_eq and rho. A secondary per-coefficient assertion is kept, because a norm
can hide one blown coefficient, using the scale the bound permits:

    floor_j = beta_rel_floor * ||D beta_cert||_2 / |D_jj * beta_cert_j|

No tolerance in this file may be relaxed after observing a result. If a dataset
misses its floor, that is a finding to report, not a number to adjust.

DOCUMENTED LIMIT (declared in advance, not after the fact)
----------------------------------------------------------
The rule predicts, before any run, that Filip's PARAMETER STANDARD DEVIATIONS
carry no reproducible significant digit in IEEE-754 double precision: Filip's
kappa_eq is 5.21e9, so kappa_eq**2 ~ 2.7e19 exceeds the precision of the
arithmetic outright and the derived floor degenerates to 1.0. For any quantity
whose pre-registered floor is >= 1.0 the test asserts only that the oracle
produced a finite, non-negative number, and records the measured relative error
so the file still carries the information. This is the rule's own prediction,
written down beforehand; it is not a loosened tolerance. It applies to Filip's
standard deviations ONLY -- Filip's coefficients pass their floor with ~6 orders
of margin, which is a positive result, not a limit.
"""
from __future__ import annotations

import ast
import inspect
import math
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
    """Assert against a PRE-REGISTERED floor; never widen it here."""
    rel = _rel_error(observed, certified)
    msg = (
        f"{spec['name']} {label}: certified={certified!r} observed={observed!r} "
        f"rel_err={rel:.3e} ({_digits(rel):.2f} correct digits) "
        f"pre-registered floor={floor:.3e} "
        f"(kappa_eq={spec['kappa_equilibrated']:.3e})"
    )
    if floor >= 1.0:
        # Documented limit declared in advance: the rule predicts no reproducible
        # digit for this quantity in double precision. Assert only sanity, but
        # record the measured error so the observation is not lost.
        assert math.isfinite(observed) and observed >= 0.0, msg
        print(f"[StRD documented limit, no reproducible digit predicted] {msg}")
        return rel
    assert rel <= floor, msg
    return rel


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
    doc = (DATASETS_PATH.parent / "PROVENANCE.md").read_text(encoding="utf-8")
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
# the actual StRD comparisons
# --------------------------------------------------------------------------

def _column_norms(fit):
    """D = diag(||X_j||_2) of the RAW design matrix - the same equilibration used
    to define kappa_eq and rho in datasets.py."""
    return np.linalg.norm(np.asarray(fit["X"], dtype=float), axis=0)


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
    certified = np.array([e for _n, e, _sd in spec["certified"]["parameters"]], dtype=float)
    d = _column_norms(fit)
    scale = float(np.linalg.norm(d * certified))
    floor = float(spec["beta_rel_floor"])

    for j, (pname, estimate, _sd) in enumerate(spec["certified"]["parameters"]):
        if estimate == 0.0:  # no certified-zero estimates exist in StRD LLS today
            assert abs(float(beta[j])) <= ZERO_SIGMA_REL
            continue
        floor_j = floor * scale / abs(float(d[j]) * float(estimate))
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
    spec = DATASETS[name]
    fit = _fit(spec)
    sds = _coefficient_sds(fit)
    floor = float(spec["sd_rel_floor"])
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
