"""Analytic and metamorphic reference properties for the P04 OLS oracle (C06-A02).

Every expected value in this module comes from one of two sources:

1. **Closed-form algebra** written out in the test's docstring (normal
   equations solved by hand on a tiny design), or
2. **An invariance argument** -- a transformation of the input under which a
   correctly implemented estimator must move in an exactly predictable way.

No expected value is ever obtained by running the estimator and recording what
it said -- with one deliberate, labelled exception: the three FINDING tests
listed below do pin current behaviour, precisely because that behaviour is
wrong and the point is to make it visible. Every other test would fail over a
wrong implementation.

Measured condition numbers and observed error magnitudes quoted in docstrings
were taken on this host and are stated so the slack in each tolerance can be
judged; they are never used as expected values.

The system under test is `tests/fixtures/pro_workflow/ols_oracle.py`, which is
itself independent of `modules/`, `backend/` and `frontend/` (enforced by
`test_oracle_independence.py`).

SCOPE -- READ THIS BEFORE QUOTING COVERAGE
------------------------------------------
The numbered sections below are *this module's own enumeration* of properties
the author judged worth asserting. They are NOT checked against any external
property specification: no enumerated A02 property list exists anywhere in
this worktree. `docs/comercial/c06/aceites.md` does record an acceptance line
for A02, but it states the aceite's *intent* -- independent numeric reference
with tolerances fixed before the trial -- and does not enumerate which
properties must be covered. So nothing here should be read as "all N required
properties are covered": it is a list someone wrote, not a list someone was
given.

THREE OF THE TESTS BELOW ASSERT DEFECTS, NOT INVARIANTS
-------------------------------------------------------
The following tests pin *current, wrong* behaviour so that the defect is
visible in the campaign record. They are GREEN because the bug is present and
they go RED when it is fixed. Counting them as "properties satisfied" is
exactly backwards:

* `test_exactly_singular_design_escapes_the_absolute_rank_threshold_once_rescaled`
  -- FINDING: the rank gate is an absolute threshold, so column scaling
  defeats it.
* `test_genuinely_near_collinear_design_at_unit_scale_is_accepted`
  -- FINDING: designs with cond_2(X) up to ~2.2e13 are accepted without
  warning.
* `test_duplicated_observation_buys_spurious_precision`
  -- FINDING: a repeated property narrows the interval as if it were new
  information.

A FOURTH GAP IS NOT TESTABLE HERE AT ALL
----------------------------------------
FINDING: `ols_oracle.py` CONTAINS NO LOG-TARGET RETRANSFORMATION. There is no
`exp`/`log`, no smearing estimator and no half-variance correction anywhere in
the oracle; `fit_ols` and `predict_intervals` work on whatever scale the caller
hands them. Section 9 below therefore verifies what the oracle *does* do on
log-transformed data (the log-scale fit, its sigma^2 and its intervals) and
states the retransformation algebra as the consequence a *caller* must apply.
THE SMEARING / HALF-VARIANCE CORRECTION ITSELF IS UNVERIFIED BY THIS MODULE,
BECAUSE THERE IS NO CODE HERE TO VERIFY IT AGAINST.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from tests.fixtures.pro_workflow import ols_oracle as oracle

EPS = float(np.finfo(float).eps)

# ---------------------------------------------------------------------------
# The hand-solvable design used by several tests.
#
#   x = (1, 2, 3, 4)        y = (2, 4, 7, 9)
#
#   x_bar = 5/2             y_bar = 11/2
#   S_xx  = sum (x_i - x_bar)^2 = 2.25 + 0.25 + 0.25 + 2.25 = 5
#   S_xy  = sum (x_i - x_bar)(y_i - y_bar)
#         = (-1.5)(-3.5) + (-0.5)(-1.5) + (0.5)(1.5) + (1.5)(3.5)
#         = 5.25 + 0.75 + 0.75 + 5.25 = 12
#   beta_1 = S_xy / S_xx = 12 / 5 = 2.4
#   beta_0 = y_bar - beta_1 * x_bar = 5.5 - 2.4 * 2.5 = -0.5
#   fitted = (1.9, 4.3, 6.7, 9.1);  resid = (0.1, -0.3, 0.3, -0.1)
#   SSE    = 0.01 + 0.09 + 0.09 + 0.01 = 0.20
#   df     = n - p = 4 - 2 = 2
#   sigma^2 = SSE / df = 0.10
# ---------------------------------------------------------------------------
HAND_X = [1.0, 2.0, 3.0, 4.0]
HAND_Y = [2.0, 4.0, 7.0, 9.0]
HAND_SLOPE = 2.4
HAND_INTERCEPT = -0.5
HAND_SIGMA2 = 0.1
HAND_SSE = 0.2
HAND_DF = 2


def _t_quantile_df2(p: float) -> float:
    """Closed-form Student-t quantile for nu = 2.

    For two degrees of freedom the CDF inverts in elementary functions:

        t_p = (2p - 1) * sqrt( 2 / (4 p (1 - p)) )

    (Standard result; obtained by inverting F(t) = 1/2 + t / (2 sqrt(2 + t^2)).)
    This gives the campaign's 80% two-sided critical value without calling the
    same scipy routine the oracle uses.
    """
    return (2.0 * p - 1.0) * math.sqrt(2.0 / (4.0 * p * (1.0 - p)))


def _r_squared(fit) -> float:
    """Centred coefficient of determination, 1 - SSE / SST."""
    y = np.asarray(fit["y"], dtype=float)
    sst = float(((y - y.mean()) ** 2).sum())
    return 1.0 - float(fit["sse"]) / sst


def _conditioning_tolerance(fit, factor: float = 50.0) -> float:
    """Pre-stated relative tolerance = factor * eps * cond_2(X).

    The forward error of a least-squares solve is bounded, to first order, by
    the machine epsilon times the condition number of the design matrix. The
    rule is fixed *before* any number is observed: it is a function of the
    design alone, not of the answer. `factor` absorbs the constant hidden in
    the first-order bound.
    """
    return factor * EPS * float(np.linalg.cond(np.asarray(fit["X"], dtype=float)))


# ---------------------------------------------------------------------------
# 1. Exact analytic OLS
# ---------------------------------------------------------------------------
def test_exact_analytic_ols_on_hand_solvable_design():
    """Slope 12/5, intercept -1/2, sigma^2 = 1/10 on the design in the header.

    Justification: the normal equations for simple regression with intercept
    reduce to beta_1 = S_xy / S_xx and beta_0 = y_bar - beta_1 x_bar. Both
    sums are integers here, so the algebra is exact and is written out in the
    module header. The variance of the slope is sigma^2 / S_xx = 0.1/5 = 0.02,
    and the leverage at x0 = x_bar is exactly 1/n = 1/4, so
    se_mean(x_bar) = sqrt(0.1 * 0.25) = sqrt(0.025).
    """
    fit = oracle.fit_ols(HAND_Y, {"x": HAND_X})

    assert fit["coefficients"]["x"] == pytest.approx(HAND_SLOPE, rel=1e-12)
    assert fit["coefficients"]["const"] == pytest.approx(HAND_INTERCEPT, rel=1e-12)
    assert fit["sse"] == pytest.approx(HAND_SSE, rel=1e-12)
    assert fit["df"] == HAND_DF
    assert fit["sigma2"] == pytest.approx(HAND_SIGMA2, rel=1e-12)

    # Var(beta_1) = sigma^2 * (X'X)^{-1}[1,1] = sigma^2 / S_xx = 0.02
    xtx_inv = np.asarray(fit["xtx_inv"], dtype=float)
    assert fit["sigma2"] * xtx_inv[1, 1] == pytest.approx(0.02, rel=1e-10)

    pred = oracle.predict_intervals(fit, {"x": 2.5}, level=0.80)
    # yhat(x_bar) = y_bar exactly, for any OLS fit that contains an intercept.
    assert pred["point"] == pytest.approx(5.5, rel=1e-12)
    assert pred["leverage"] == pytest.approx(0.25, rel=1e-10)
    assert pred["se_mean"] == pytest.approx(math.sqrt(0.025), rel=1e-10)
    assert pred["se_pred"] == pytest.approx(math.sqrt(0.1 * 1.25), rel=1e-10)

    t_star = _t_quantile_df2(0.90)
    assert pred["t_critical"] == pytest.approx(t_star, rel=1e-10)
    assert pred["mean_ci"]["lower"] == pytest.approx(5.5 - t_star * math.sqrt(0.025), rel=1e-10)
    assert pred["mean_ci"]["upper"] == pytest.approx(5.5 + t_star * math.sqrt(0.025), rel=1e-10)


# ---------------------------------------------------------------------------
# 2. Intercept vs no intercept
# ---------------------------------------------------------------------------
def test_with_and_without_intercept_give_different_predictable_coefficients():
    """Regression through the origin gives sum(xy)/sum(x^2) = 67/30, not 12/5.

    Justification: dropping the constant column changes the projection space
    from span{1, x} to span{x}. The single normal equation becomes
    beta = <x, y> / <x, x>. On the header design,
        <x, y> = 1*2 + 2*4 + 3*7 + 4*9 = 67
        <x, x> = 1 + 4 + 9 + 16 = 30
    so beta = 67/30 = 2.2333..., while the with-intercept slope is 12/5 = 2.4.
    Both are exactly predictable and they are not equal: an implementation that
    silently forced an intercept (or silently dropped one) would move one of
    these two numbers onto the other.

    The residual degrees of freedom also differ: n - 2 = 2 with intercept,
    n - 1 = 3 without.
    """
    with_int = oracle.fit_ols(HAND_Y, {"x": HAND_X}, intercept=True)
    no_int = oracle.fit_ols(HAND_Y, {"x": HAND_X}, intercept=False)

    assert with_int["coefficients"]["x"] == pytest.approx(12.0 / 5.0, rel=1e-12)
    assert no_int["coefficients"]["x"] == pytest.approx(67.0 / 30.0, rel=1e-12)
    assert "const" not in no_int["coefficients"]
    assert no_int["names"] == ["x"]

    assert with_int["df"] == 2
    assert no_int["df"] == 3
    assert with_int["p"] == 2
    assert no_int["p"] == 1

    # The two slopes are genuinely distinct (|2.4 - 2.2333| = 1/6).
    delta = abs(with_int["coefficients"]["x"] - no_int["coefficients"]["x"])
    assert delta == pytest.approx(1.0 / 6.0, rel=1e-10)

    # Without an intercept the residuals need not sum to zero; with one they must.
    assert float(np.sum(with_int["residuals"])) == pytest.approx(0.0, abs=1e-12)
    assert abs(float(np.sum(no_int["residuals"]))) > 1e-3


# ---------------------------------------------------------------------------
# 3. Treatment coding: an unseen level is unsupported, not folded
# ---------------------------------------------------------------------------
def test_unseen_category_is_unsupported_not_folded_into_reference():
    """A level absent from training must be refused, not encoded as all-zero dummies.

    Justification: in treatment (dummy) coding the reference level is the row
    whose dummies are all zero. A category never seen in training has no
    estimated effect, so writing zeros for it is *numerically identical* to
    asserting it behaves exactly like the reference level -- a claim the data
    cannot support. The invariance being tested is therefore structural: the
    encoder must mark such a row unsupported, and the all-zero row it would
    otherwise produce must be shown to coincide with the reference prediction
    (proving the fold is not a harmless default but a substantive, wrong claim
    worth `beta_level` reais).
    """
    values = ["Centro", "Sul", "Centro", "Sul", "Centro", "Sul", "Industrial"]
    training_mask = [True] * 6 + [False]
    enc = oracle.encode_treatment(values, training_mask=training_mask, column="bairro")

    assert enc["reference"] == "Centro"  # lexicographic first training level
    assert enc["levels"] == ["Centro", "Sul"]
    assert "Industrial" not in enc["levels"]
    assert enc["dummy_names"] == ["bairro=Sul"]
    assert "bairro=Industrial" not in enc["columns"]
    assert enc["supported"] == [True, True, True, True, True, True, False]

    # The unseen row's dummy vector is all-zero -- i.e. exactly the reference row.
    assert enc["columns"]["bairro=Sul"][6] == 0.0

    # Fit on the six training rows only; y chosen so the Sul effect is large.
    y_train = [100.0, 160.0, 104.0, 166.0, 96.0, 154.0]
    area = [50.0, 50.0, 52.0, 52.0, 48.0, 48.0]
    fit = oracle.fit_ols(
        y_train,
        {"area": area, "bairro=Sul": enc["columns"]["bairro=Sul"][:6]},
        column_order=["area", "bairro=Sul"],
    )
    beta_sul = fit["coefficients"]["bairro=Sul"]
    assert abs(beta_sul) > 1.0  # the levels are not interchangeable

    # The x0 a naive caller would build for the unseen row, taken from the
    # encoder's own output for that row rather than hand-written here.
    naive_x0 = {"area": 50.0}
    naive_x0.update({name: enc["columns"][name][6] for name in enc["dummy_names"]})
    assert set(naive_x0) == {"area", "bairro=Sul"}

    naive_fold = oracle.predict_intervals(fit, naive_x0)
    as_reference = oracle.predict_intervals(fit, {"area": 50.0, "bairro=Sul": 0.0})
    as_sul = oracle.predict_intervals(fit, {"area": 50.0, "bairro=Sul": 1.0})

    # Folding the unseen level in is bit-for-bit the reference claim ...
    assert naive_fold["point"] == as_reference["point"]
    # ... and that claim is materially different from the other observed level,
    # so the fold is a real error of size |beta_sul|, not a rounding detail.
    assert as_sul["point"] - as_reference["point"] == pytest.approx(beta_sul, rel=1e-10)

    # An unsupported row must not be silently predictable: the design column is
    # mandatory, so a caller that omits it gets an error rather than a default.
    with pytest.raises(oracle.OracleError):
        oracle.predict_intervals(fit, {"area": 50.0})


# ---------------------------------------------------------------------------
# 4. Predictor scale invariance
# ---------------------------------------------------------------------------
def test_predictor_scale_invariance_of_fit_r2_and_interval_widths():
    """x -> 1000x divides beta_x by 1000 and changes nothing on the y scale.

    Justification: if X' = X D with D = diag(1, 1000) invertible, then
    beta' = D^{-1} beta, and the fitted values X' beta' = X D D^{-1} beta
    = X beta are identical. The hat matrix H = X(X'X)^{-1}X' is invariant
    under any right multiplication by an invertible D, so leverages, residuals,
    SSE, sigma^2, R^2 and hence every interval *width on the response scale*
    are invariant too. Only the coefficient attached to the rescaled column
    moves, and it moves by exactly the reciprocal factor.
    """
    k = 1000.0
    base = oracle.fit_ols(HAND_Y, {"x": HAND_X})
    scaled = oracle.fit_ols(HAND_Y, {"x": [v * k for v in HAND_X]})

    assert scaled["coefficients"]["x"] == pytest.approx(base["coefficients"]["x"] / k, rel=1e-12)
    assert scaled["coefficients"]["const"] == pytest.approx(base["coefficients"]["const"], rel=1e-10)
    assert scaled["sigma2"] == pytest.approx(base["sigma2"], rel=1e-12)
    assert _r_squared(scaled) == pytest.approx(_r_squared(base), rel=1e-12)

    x0 = 2.5
    p_base = oracle.predict_intervals(base, {"x": x0})
    p_scaled = oracle.predict_intervals(scaled, {"x": x0 * k})

    assert p_scaled["point"] == pytest.approx(p_base["point"], rel=1e-12)
    assert p_scaled["leverage"] == pytest.approx(p_base["leverage"], rel=1e-10)
    for key in ("mean_ci", "prediction_interval"):
        w_base = p_base[key]["upper"] - p_base[key]["lower"]
        w_scaled = p_scaled[key]["upper"] - p_scaled[key]["lower"]
        assert w_scaled == pytest.approx(w_base, rel=1e-10)
        assert p_scaled[key]["lower"] == pytest.approx(p_base[key]["lower"], rel=1e-10)
        assert p_scaled[key]["upper"] == pytest.approx(p_base[key]["upper"], rel=1e-10)


# ---------------------------------------------------------------------------
# 5. Response unit invariance
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("k", [1000.0, 0.001, -2.0])
def test_response_unit_invariance_scales_point_and_bounds_exactly(k):
    """y -> k*y scales beta, the point and both interval bounds by exactly k.

    Justification: OLS is linear in y. beta(k y) = (X'X)^{-1}X'(k y) = k beta,
    residuals scale by k, so sigma^2 scales by k^2 and sigma by |k|. The
    standard errors therefore scale by |k| and the bounds
    yhat +/- t* se scale by k, with the bounds swapping roles when k < 0
    (which is why the negative case compares the *set* {lower, upper}).
    Converting reais to thousands of reais must not change the analysis.
    """
    base = oracle.fit_ols(HAND_Y, {"x": HAND_X})
    scaled = oracle.fit_ols([v * k for v in HAND_Y], {"x": HAND_X})

    assert scaled["coefficients"]["x"] == pytest.approx(base["coefficients"]["x"] * k, rel=1e-12)
    assert scaled["sigma2"] == pytest.approx(base["sigma2"] * k * k, rel=1e-12)
    assert scaled["sigma"] == pytest.approx(base["sigma"] * abs(k), rel=1e-12)

    p_base = oracle.predict_intervals(base, {"x": 3.0})
    p_scaled = oracle.predict_intervals(scaled, {"x": 3.0})
    assert p_scaled["point"] == pytest.approx(p_base["point"] * k, rel=1e-12)
    assert p_scaled["leverage"] == pytest.approx(p_base["leverage"], rel=1e-10)

    for key in ("mean_ci", "prediction_interval"):
        expected = sorted([p_base[key]["lower"] * k, p_base[key]["upper"] * k])
        observed = sorted([p_scaled[key]["lower"], p_scaled[key]["upper"]])
        assert observed[0] == pytest.approx(expected[0], rel=1e-10)
        assert observed[1] == pytest.approx(expected[1], rel=1e-10)


# ---------------------------------------------------------------------------
# 6. Row-order invariance
# ---------------------------------------------------------------------------
def test_row_order_invariance_up_to_floating_point():
    """Permuting rows leaves the fit unchanged except for rounding.

    Justification: OLS depends on the data only through the Gram matrix X'X
    and the cross product X'y, both of which are sums over rows and therefore
    symmetric functions of the row index. Any permutation P satisfies
    (PX)'(PX) = X'X and (PX)'(Py) = X'y, so beta, sigma^2 and every interval
    are mathematically identical.

    Tolerance: 1e-12 relative, AND ITS SLACK IS ON THE RECORD. The permutation
    changes the order of the floating-point additions inside the QR
    factorisation, so agreement is not bit-exact. The design here (a `const`
    column alongside area in [30, 140]) has cond_2(X) = 251.7, measured and
    asserted below, so the first-order forward-error bound is
    eps * cond = 5.6e-14 and 1e-12 sits ~18x above it. The *observed* worst
    relative disagreement across every quantity asserted below, measured on
    this host, is 2.1e-15 -- so the assertion is running with about 475x more
    headroom than the run actually needs. The bound is kept at the analytic
    figure rather than tightened to the observed one, because a tolerance
    fitted to an observation is no longer a prediction; but a reader should
    know that this test would still pass if the permuted fit were ~475 times
    noisier than it is.
    """
    rng = np.random.default_rng(20260912)
    x = np.linspace(30.0, 140.0, 25)
    y = 3200.0 * x + 18000.0 + rng.normal(0.0, 4000.0, size=x.shape)

    base = oracle.fit_ols(y.tolist(), {"area": x.tolist()})
    p_base = oracle.predict_intervals(base, {"area": 85.0})

    # The conditioning figure the tolerance above is justified by.
    cond = float(np.linalg.cond(np.asarray(base["X"], dtype=float)))
    assert cond < 1e3, f"tolerance justification assumes cond_2(X) ~ 2.5e2, got {cond}"
    assert EPS * cond < 1e-13

    order = rng.permutation(x.shape[0])
    assert not np.array_equal(order, np.arange(x.shape[0]))
    shuffled = oracle.fit_ols(y[order].tolist(), {"area": x[order].tolist()})
    p_shuffled = oracle.predict_intervals(shuffled, {"area": 85.0})

    assert shuffled["n"] == base["n"]
    assert shuffled["df"] == base["df"]
    for name in base["coefficients"]:
        assert shuffled["coefficients"][name] == pytest.approx(
            base["coefficients"][name], rel=1e-12
        )
    assert shuffled["sigma2"] == pytest.approx(base["sigma2"], rel=1e-12)
    assert p_shuffled["point"] == pytest.approx(p_base["point"], rel=1e-12)
    for key in ("mean_ci", "prediction_interval"):
        assert p_shuffled[key]["lower"] == pytest.approx(p_base[key]["lower"], rel=1e-12)
        assert p_shuffled[key]["upper"] == pytest.approx(p_base[key]["upper"], rel=1e-12)


# ---------------------------------------------------------------------------
# 7. Extreme magnitudes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scale", [1e8, 1e-6])
def test_extreme_predictor_magnitudes_still_match_the_analytic_answer(scale):
    """At 1e8 and 1e-6 the hand-solved answer must survive, within eps*cond.

    Justification: the analytic answer is the one in the module header,
    transported by the scale-invariance argument of
    `test_predictor_scale_invariance_...`: beta_x = 2.4 / scale, beta_0 = -0.5,
    sigma^2 = 0.1, and the point at x0 = 2.5*scale is 5.5.

    Tolerance is *pre-stated as a function of the design only*:
    rel_tol = 50 * eps * cond_2(X), the first-order forward-error bound for a
    least-squares solve. It is computed from X before any coefficient is read,
    so it cannot be tuned to the observed error. Scaling a single column by
    1e8 inflates cond_2(X) to 6.71e8, giving rel_tol = 7.45e-6; at 1e-6 the
    condition number is 8.94e5, giving rel_tol = 9.93e-9.

    THE SLACK IN THAT BOUND IS LARGE AND IS ON THE RECORD. Measured on this
    host, the worst relative error across every quantity asserted below is
    3.55e-15 at scale 1e8 and 2.22e-15 at scale 1e-6 -- i.e. the pre-stated
    tolerance at 1e8 is about 2.1e9 times looser than the run needs, because
    the first-order bound assumes the worst-case alignment of rounding errors
    and a QR solve on a 4x2 design does not come close to it. The pre-stated
    bound is kept as the primary contract (it is a prediction, not a fit), but
    a second assertion below pins the error to 1e-11 -- a round number roughly
    three orders above the observed floor, chosen so that a real numerical
    regression cannot hide in nine orders of unused headroom.
    """
    x_scaled = [v * scale for v in HAND_X]
    fit = oracle.fit_ols(HAND_Y, {"x": x_scaled})
    rel_tol = _conditioning_tolerance(fit)
    assert rel_tol < 1e-4, f"design too ill-conditioned to assert anything: rel_tol={rel_tol}"

    assert fit["coefficients"]["x"] == pytest.approx(HAND_SLOPE / scale, rel=rel_tol)
    assert fit["coefficients"]["const"] == pytest.approx(HAND_INTERCEPT, rel=rel_tol)
    assert fit["sigma2"] == pytest.approx(HAND_SIGMA2, rel=max(rel_tol, 1e-9))

    pred = oracle.predict_intervals(fit, {"x": 2.5 * scale})
    assert pred["point"] == pytest.approx(5.5, rel=rel_tol)
    assert pred["leverage"] == pytest.approx(0.25, rel=max(rel_tol, 1e-9))
    t_star = _t_quantile_df2(0.90)
    half = t_star * math.sqrt(0.025)
    assert pred["mean_ci"]["lower"] == pytest.approx(5.5 - half, rel=max(rel_tol, 1e-9))
    assert pred["mean_ci"]["upper"] == pytest.approx(5.5 + half, rel=max(rel_tol, 1e-9))

    # Empirical floor check: the analytic bound above is up to 2.1e9 times
    # looser than the observed error (3.55e-15 at scale 1e8). This second gate
    # is deliberately much tighter so that the test can actually fail.
    tight = 1e-11
    worst = max(
        abs(fit["coefficients"]["x"] - HAND_SLOPE / scale) / abs(HAND_SLOPE / scale),
        abs(fit["coefficients"]["const"] - HAND_INTERCEPT) / abs(HAND_INTERCEPT),
        abs(fit["sigma2"] - HAND_SIGMA2) / HAND_SIGMA2,
        abs(pred["point"] - 5.5) / 5.5,
        abs(pred["leverage"] - 0.25) / 0.25,
    )
    assert worst < tight, (
        f"scale={scale}: worst relative error {worst:.3g} exceeds the empirical "
        f"floor gate {tight:.0e} (analytic bound was {rel_tol:.3g})"
    )


# ---------------------------------------------------------------------------
# 8. Singularity: exact rank deficiency, genuine near-collinearity,
#    and the absolute-threshold gap
# ---------------------------------------------------------------------------
def test_exact_singularity_is_detected_and_refused():
    """A duplicated column makes X'X singular; the fit must refuse, not pseudo-invert.

    Justification: if column b equals column a, then X has rank p-1 and the
    normal equations have an affine *family* of solutions
    (beta_a + t, beta_b - t) for every real t. No member of that family is
    "the" estimate, and the standard errors are undefined (X'X has a zero
    eigenvalue). A pseudo-inverse would silently pick the minimum-norm member
    and report finite standard errors for it -- a confident answer to a
    question with no unique answer.
    """
    x = np.linspace(1.0, 12.0, 12)
    y = (2.0 * x + 1.0).tolist()
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols(y, {"a": x.tolist(), "b": x.tolist()})

    # An exact linear combination (not just a copy) is equally singular.
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols(y, {"a": x.tolist(), "b": (3.0 * x + 7.0).tolist()})

    # And the intercept-plus-constant-column case, which is the one a dummy
    # encoder produces when it forgets to drop the reference level.
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols(y, {"a": x.tolist(), "ones": [1.0] * 12})


def test_scalar_multiple_columns_are_refused_at_unit_scale():
    """b = a*(1+delta) is an EXACT multiple of a, hence exactly rank deficient.

    This is the scalar-multiple case of the test above, written with a factor
    very close to 1 so that the rejection cannot be attributed to a large
    numeric gap between the columns. It is NOT a near-singularity test: for
    any real delta, span{1, a, a(1+delta)} = span{1, a}, so the design has
    mathematical rank 2 with p = 3 whatever delta is.

    Correcting an earlier, wrong justification: it is not true that the
    smallest singular value is of order delta*||a|| here. Because the third
    column is a scaled copy of the second, the third diagonal of R is pure
    floating-point residue and does not track delta at all. Measured on this
    host (numpy QR, 12 rows):

        delta = 1e-8   ->  min |diag(R)| = 2.4e-15,  cond_2(X) = 2.2e16
        delta = 1e-10  ->  min |diag(R)| = 1.8e-15,  cond_2(X) = 2.8e16
        delta = 1e-12  ->  min |diag(R)| = 4.0e-15,  cond_2(X) = 1.3e16

    -- all three at the same rounding floor, in no monotone relation to delta.
    What the test actually establishes is that the absolute gate
    `min |diag(R)| < 1e-12` does catch exact rank deficiency *at unit column
    scale*, where that floor sits three orders below the threshold. The
    following two tests show the two ways that guarantee fails: rescale the
    columns, or make the collinearity approximate instead of exact.
    """
    x = np.linspace(1.0, 12.0, 12)
    y = (2.0 * x + 1.0).tolist()
    for delta in (1e-8, 1e-10, 1e-12):
        near = (x * (1.0 + delta)).tolist()
        X = np.column_stack([np.ones(12), x, np.asarray(near)])
        # The stated premise, asserted rather than assumed: the floor is the
        # floor, not a function of delta.
        floor = float(np.min(np.abs(np.diag(np.linalg.qr(X, mode="reduced")[1]))))
        # Below the oracle's own absolute gate of 1e-12 -- that, and not any
        # relation to delta, is why the refusal below happens.
        assert floor < 1e-12, f"delta={delta}: min|diag(R)|={floor}"
        with pytest.raises(oracle.OracleError):
            oracle.fit_ols(y, {"a": x.tolist(), "b": near})


def test_genuinely_near_collinear_design_at_unit_scale_is_accepted():
    """DOCUMENTED GAP (FINDING): A GENUINELY NEAR-COLLINEAR DESIGN AT UNIT SCALE
    IS ACCEPTED. The absolute rank gate only ever catches *exact* rank
    deficiency; approximate collinearity, which is what real valuation data
    produces, passes straight through.

    Here b = a + eps * noise with independent noise, so the columns are
    linearly independent as real vectors but nearly parallel. Measured on this
    host for exactly the loop below (12 rows, a = linspace(1, 12), noise from
    `default_rng(20260912)` drawn in the order the loop draws it):

        eps = 1e-8   ->  cond_2(X) = 2.38e9,   min |diag(R)| = 2.15e-8  accepted
        eps = 1e-10  ->  cond_2(X) = 2.16e11,  min |diag(R)| = 2.37e-10 accepted
        eps = 1e-12  ->  cond_2(X) = 2.18e13,  min |diag(R)| = 2.35e-12 accepted

    (Every one of those `min |diag(R)|` values clears the oracle's absolute
    1e-12 gate, which is why all three are accepted.)

    At cond_2(X) = 2.2e13 the relative forward error of the solve is bounded
    only by eps_machine * cond ~ 4e-3, i.e. the coefficients carry roughly two
    correct significant figures, and the reported standard errors carry no
    warning of it. A relative criterion -- `min |diag(R)| < tol * max |diag(R)|`
    with tol ~ 1e-8, or a condition-number ceiling -- would refuse the last two
    rows at least.

    THIS TEST ASSERTS THE DEFECT. It is green because the gate is absolute and
    goes RED as soon as a relative rank criterion is adopted, at which point it
    must be rewritten as a `pytest.raises` assertion rather than repaired.
    """
    x = np.linspace(1.0, 12.0, 12)
    y = (2.0 * x + 1.0).tolist()
    rng = np.random.default_rng(20260912)

    accepted_conds = []
    for eps_col in (1e-8, 1e-10, 1e-12):
        b = x + eps_col * rng.normal(0.0, 1.0, size=x.shape)
        # Genuinely independent columns: not a scalar multiple of x.
        ratios = b / x
        assert float(ratios.max() - ratios.min()) > 0.0

        cond = float(np.linalg.cond(np.column_stack([np.ones(12), x, b])))
        assert cond > 1e9, f"eps={eps_col} did not produce a near-collinear design"

        # FINDING: no OracleError. The design is accepted at cond up to ~1e13.
        fit = oracle.fit_ols(y, {"a": x.tolist(), "b": b.tolist()})
        assert math.isfinite(fit["coefficients"]["a"])
        assert math.isfinite(fit["coefficients"]["b"])
        accepted_conds.append(cond)

    assert max(accepted_conds) > 1e12, (
        "FINDING: fit_ols accepted a design with cond_2(X) = "
        f"{max(accepted_conds):.3g} without error or warning; the rank gate "
        "is absolute (min|diag(R)| < 1e-12) and cannot see relative "
        "ill-conditioning"
    )


def test_exactly_singular_design_escapes_the_absolute_rank_threshold_once_rescaled():
    """DOCUMENTED GAP (FINDING): the rank test is an absolute threshold, so it is
    not scale invariant, and an exactly rank-deficient design at monetary scale
    is accepted with an arbitrary answer.

    The design used here is the same EXACTLY rank-deficient one as in
    `test_scalar_multiple_columns_are_refused_at_unit_scale`: b = a*(1 + 1e-10)
    is a scalar multiple of a, so span{1, a, b} = span{1, a} for any factor.
    The only thing that changes between the two tests is the *units* of the
    columns -- and that is the whole point.

    `fit_ols` rejects a design when `min |diag(R)| < 1e-12`, an *absolute*
    bound. Rank deficiency is a property of the column space and is invariant
    under column scaling, so the test ought to be relative -- e.g.
    `min |diag(R)| < tol * max |diag(R)|`, or a condition-number bound. It is
    not. The rounding residue that forms the last diagonal of R scales with the
    columns: multiplying both by 1e4 (and Brazilian valuation columns routinely
    carry magnitudes of 1e4 to 1e6 in reais) lifts a floor of ~2e-15 to ~2e-11,
    above the absolute threshold, so the *same* mathematically singular design
    is now accepted.

    That the accepted answer is meaningless is demonstrated here *without*
    reference to any recorded value: two runs of the same rank-deficient
    problem that differ only by a perturbation far below any physical
    significance return coefficient splits that differ by a large fraction of
    the total effect. A well-posed estimator cannot do that.

    This test asserts the gap as it currently stands so that the campaign
    record is honest. It is expected to FAIL -- and must then be rewritten as a
    `pytest.raises` assertion -- once the rank test is made scale relative.

    Which assertion means what, if this test ever goes red:

    * `fit_ols` returning at all, and `cond_2(X) > 1e15`, are deterministic and
      are *the finding*. If those two stop holding, the rank test has been
      fixed and this test should be rewritten, not repaired.
    * The `split_shift` line is an illustration of the noise magnitude. At
      cond ~ 1e16 the a/b split is decided by rounding, so its size depends on
      the LAPACK/BLAS build, not on the mathematics. If only that line fails,
      the cause is a different linear-algebra backend on the host -- not a
      change in the oracle. Do not widen the 0.05 gate to make it pass;
      re-derive it on the host in question or split it out.
    """
    x = np.linspace(1.0, 12.0, 12)
    y = (2.0 * x + 1.0).tolist()
    scale = 1e4

    a = (x * scale).tolist()
    b1 = (x * scale * (1.0 + 1e-10)).tolist()
    b2 = (x * scale * (1.0 + 2e-10)).tolist()

    # Unit-scale twin of the same design, refused; only the units differ.
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols(y, {"a": x.tolist(), "b": (x * (1.0 + 1e-10)).tolist()})

    fit1 = oracle.fit_ols(y, {"a": a, "b": b1})
    fit2 = oracle.fit_ols(y, {"a": a, "b": b2})

    # The gap: no OracleError was raised even though the design is exactly
    # rank deficient. The rounding floor was simply lifted over the absolute
    # threshold by the change of units.
    r1 = np.linalg.qr(np.asarray(fit1["X"], dtype=float), mode="reduced")[1]
    assert float(np.min(np.abs(np.diag(r1)))) > 1e-12
    assert np.linalg.cond(np.asarray(fit1["X"], dtype=float)) > 1e15

    # The "answer" is not a function of the problem: an imperceptible change in
    # the input moves the a/b split by an appreciable fraction of the total.
    total = fit1["coefficients"]["a"] + fit1["coefficients"]["b"]
    assert total == pytest.approx(
        fit2["coefficients"]["a"] + fit2["coefficients"]["b"], rel=1e-6
    ), "the identified quantity (the sum) is stable, as theory requires"
    split_shift = abs(fit1["coefficients"]["a"] - fit2["coefficients"]["a"])
    assert split_shift > 0.05 * abs(total), (
        "FINDING: rank-deficient design accepted; the individual coefficients "
        "are rounding noise, not estimates"
    )


# ---------------------------------------------------------------------------
# 9. Log target: what the oracle actually does, and what it does NOT do
# ---------------------------------------------------------------------------
def test_log_scale_fit_is_exact_and_pins_the_sigma2_that_any_retransform_needs():
    """FINDING: `ols_oracle.py` IMPLEMENTS NO LOG-TARGET RETRANSFORMATION AT ALL.

    There is no `exp(`, no `log(`, no smearing estimator and no half-variance
    correction anywhere in the oracle. `fit_ols` and `predict_intervals` work
    on whatever scale they are handed, so THE SMEARING / HALF-VARIANCE
    CORRECTION CANNOT BE VERIFIED AGAINST THIS ORACLE. An earlier version of
    this test asserted `arithmetic / geometric == exp(sigma2/2)` where the test
    itself had defined `arithmetic = exp(point + sigma2/2)` and
    `geometric = exp(point)`; that is the identity exp(a+b)/exp(a) = exp(b) and
    is true of any two numbers. It tested nothing.

    What CAN be verified is the log-scale fit the oracle returns, and that is
    what is asserted here -- against hand algebra, not against the oracle.
    Taking log y = (2, 4, 7, 9) at x = (1, 2, 3, 4), the module header's
    closed form applies verbatim on the log scale:

        beta_1 = S_xy / S_xx = 12/5 = 2.4      (per unit x, on the log scale)
        beta_0 = -1/2
        SSE = 0.20, df = 2, sigma^2 = 0.10
        at x0 = 2.5 (= x_bar): log-point = y_bar = 5.5 exactly, leverage = 1/4

    Every number below is one of those, so corrupting sigma^2, the fitted
    values or the leverage inside `fit_ols` makes this test red.

    The retransformation algebra is then stated as the consequence a *caller*
    must apply, with CONCRETE numbers rather than symbols: if
    log Y | x ~ N(mu, sigma^2), the naive exp() of the point is the conditional
    median / geometric mean exp(5.5) = 244.69, while the conditional mean is
    exp(5.5 + 0.10/2) = exp(5.55) = 257.24 -- 5.127% higher. Those constants
    come from the hand algebra above; if the oracle's sigma^2 drifts away from
    0.10 the assertions fail, which is precisely what the old formulation could
    not do. What is NOT asserted, because there is no code for it, is that the
    product applies the correction: that remains an open gap.

    The interval retransforms exactly -- exp() is strictly increasing, so the
    endpoints map to the endpoints and coverage is preserved -- but it is no
    longer symmetric about the point, which is asserted from the hand-computed
    t critical value.
    """
    x = [1.0, 2.0, 3.0, 4.0]
    log_y = [2.0, 4.0, 7.0, 9.0]  # = HAND_Y, read as log-reais

    fit = oracle.fit_ols(log_y, {"x": x})
    pred = oracle.predict_intervals(fit, {"x": 2.5}, level=0.80)

    # (a) The log-scale fit is the hand-solved one, independently of any exp().
    assert fit["coefficients"]["x"] == pytest.approx(2.4, rel=1e-12)
    assert fit["coefficients"]["const"] == pytest.approx(-0.5, rel=1e-12)
    assert fit["sse"] == pytest.approx(0.20, rel=1e-12)
    assert fit["df"] == 2
    # The load-bearing number: the correction is exp(sigma2/2) and sigma2 is
    # pinned to hand algebra, so a corrupted variance cannot hide here.
    assert fit["sigma2"] == pytest.approx(0.10, rel=1e-12)
    assert pred["point"] == pytest.approx(5.5, rel=1e-12)
    assert pred["leverage"] == pytest.approx(0.25, rel=1e-10)

    # (b) The two retransformed point estimates, as absolute hand-computed
    # amounts. Both are functions of the oracle's own output, but the values
    # they are compared against are not.
    geometric = math.exp(pred["point"])
    arithmetic = math.exp(pred["point"] + fit["sigma2"] / 2.0)
    assert geometric == pytest.approx(math.exp(5.5), rel=1e-12)
    assert arithmetic == pytest.approx(math.exp(5.55), rel=1e-12)
    # exp(0.05) - 1 = 5.1271096e-2, from sigma^2 = 0.10 and nothing else.
    assert arithmetic / geometric - 1.0 == pytest.approx(0.051271096376, rel=1e-9)
    assert arithmetic > geometric
    # A naive exp() therefore understates the conditional mean by ~12.5 units
    # of price on a 244.7 base -- a real monetary error, not a rounding detail.
    assert arithmetic - geometric == pytest.approx(
        math.exp(5.55) - math.exp(5.5), rel=1e-9
    )

    # (c) The retransformed 80% mean interval: endpoints are the exp() of the
    # hand-computed log-scale endpoints, and it is asymmetric about the point.
    t_star = _t_quantile_df2(0.90)
    half = t_star * math.sqrt(0.10 * 0.25)
    lower = math.exp(pred["mean_ci"]["lower"])
    upper = math.exp(pred["mean_ci"]["upper"])
    assert lower == pytest.approx(math.exp(5.5 - half), rel=1e-10)
    assert upper == pytest.approx(math.exp(5.5 + half), rel=1e-10)
    assert lower < geometric < upper
    assert (upper - geometric) == pytest.approx(
        math.exp(5.5) * (math.exp(half) - 1.0), rel=1e-10
    )
    assert (geometric - lower) == pytest.approx(
        math.exp(5.5) * (1.0 - math.exp(-half)), rel=1e-10
    )
    assert (upper - geometric) > (geometric - lower)
    # ... and the arithmetic-mean point is not the centre of it either.
    assert not oracle.close(
        arithmetic, 0.5 * (lower + upper), abs_tol=1e-9, rel_tol=1e-9
    )


# ---------------------------------------------------------------------------
# 10. Missing target values are never imputed
# ---------------------------------------------------------------------------
def test_missing_target_is_dropped_from_the_fit_and_n_reflects_it():
    """A row with no price is removed; n = 5, not 6, and nothing is imputed.

    Justification: OLS conditions on the observed response. A row with a
    missing y contributes no residual and no information about beta, so the
    correct n is the count of observed targets. Imputing the mean (or any
    constant) would add a synthetic point lying exactly on the response mean,
    which mechanically deflates SSE and therefore narrows every interval --
    fabricated precision. The test asserts that (a) the oracle refuses a
    non-finite target outright rather than filling it, (b) the count helper
    reports 5, and (c) the honest listwise-deletion fit differs from the
    mean-imputed fit, so the two are not interchangeable.
    """
    rows = [
        {"id": "A", "area": 50.0, "preco": 100.0},
        {"id": "B", "area": 60.0, "preco": 130.0},
        {"id": "C", "area": 70.0, "preco": None},
        {"id": "D", "area": 80.0, "preco": 175.0},
        {"id": "E", "area": 90.0, "preco": 190.0},
        {"id": "F", "area": 100.0, "preco": 215.0},
    ]

    assert oracle.count_observed_target(rows, "preco") == 5
    assert len(rows) == 6

    # (a) A non-finite target is refused, never filled in.
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols(
            [r["preco"] if r["preco"] is not None else float("nan") for r in rows],
            {"area": [r["area"] for r in rows]},
        )
    # The same holds for the string sentinels a CSV import produces.
    for sentinel in ("", "nan", "NULL"):
        marked = [dict(r) for r in rows]
        marked[2]["preco"] = sentinel
        assert oracle.count_observed_target(marked, "preco") == 5

    observed = [r for r in rows if r["preco"] is not None]
    fit = oracle.fit_ols(
        [r["preco"] for r in observed], {"area": [r["area"] for r in observed]}
    )
    assert fit["n"] == 5
    assert fit["df"] == 3

    # (c) Mean imputation is a different, narrower model -- not an equivalent one.
    mean_price = sum(r["preco"] for r in observed) / 5.0
    imputed_y = [r["preco"] if r["preco"] is not None else mean_price for r in rows]
    imputed = oracle.fit_ols(imputed_y, {"area": [r["area"] for r in rows]})
    assert imputed["n"] == 6
    assert imputed["coefficients"]["area"] != pytest.approx(
        fit["coefficients"]["area"], rel=1e-6
    )


# ---------------------------------------------------------------------------
# 11. Duplicated observations and the independence assumption
# ---------------------------------------------------------------------------
def test_duplicated_observation_buys_spurious_precision():
    """DOCUMENTED GAP (FINDING): the oracle has no grouping, so the same property
    entered twice narrows the interval as if it were two independent sales.

    Justification: the interval formula
    yhat +/- t_{1-a/2, n-p} * sigma * sqrt(x0 (X'X)^{-1} x0')
    assumes n *independent* error draws. Recording one property twice supplies
    a second row whose error is perfectly correlated with the first
    (correlation 1, not 0), so it carries no new information about sigma or
    beta. A correct treatment would either deduplicate, or use a
    cluster-robust / random-effects variance in which the effective sample
    size stays at the number of distinct properties.

    `ols_oracle.fit_ols` takes no group argument and offers no cluster-robust
    option, so the duplicate is counted as a genuine extra observation: n
    rises by one, the residual degrees of freedom rise (shrinking t*), the
    leverage at x0 falls, and the interval gets *narrower* on data that
    contains no new information. This test asserts that narrowing explicitly,
    so the gap is visible in the campaign record rather than assumed away. It
    is expected to FAIL -- and to be rewritten as an equality assertion --
    once group-aware variance is available.
    """
    x = [50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    y = [100.0, 130.0, 152.0, 175.0, 190.0, 215.0]

    distinct = oracle.fit_ols(y, {"area": x})
    p_distinct = oracle.predict_intervals(distinct, {"area": 75.0})

    # Row index 2 is the same property, keyed in a second time.
    with_dup = oracle.fit_ols(y + [y[2]], {"area": x + [x[2]]})
    p_dup = oracle.predict_intervals(with_dup, {"area": 75.0})

    assert distinct["n"] == 6
    assert with_dup["n"] == 7, "the duplicate is counted as an independent row"
    assert with_dup["df"] == distinct["df"] + 1

    w_distinct = p_distinct["mean_ci"]["upper"] - p_distinct["mean_ci"]["lower"]
    w_dup = p_dup["mean_ci"]["upper"] - p_dup["mean_ci"]["lower"]
    assert w_dup < w_distinct, (
        "FINDING: duplicating one observation narrowed the 80% mean CI from "
        f"{w_distinct:.6f} to {w_dup:.6f} without adding any information"
    )

    # The number of *distinct* properties, which is what the interval should be
    # governed by, is unchanged.
    assert len({(a, b) for a, b in zip(x + [x[2]], y + [y[2]])}) == 6


# ---------------------------------------------------------------------------
# 12. A percentage band is not a statistical interval
# ---------------------------------------------------------------------------
def test_percentage_band_is_provably_not_a_statistical_interval():
    """point +/- 10% cannot be a CI: its width is a function of the point alone.

    Justification: a Student-t mean interval has half-width
    t* * sigma * sqrt(x0 (X'X)^{-1} x0'), which depends on the residual
    scatter, the sample size and the *leverage* of x0 -- it widens as x0 moves
    away from the centroid. A percentage band has half-width 0.10 * yhat,
    which depends on none of those. Two consequences are asserted:

    (1) On one dataset, at a central x0 and a far-out x0, the ratio
        (CI half-width / point) changes, while the band's ratio is identically
        0.10 by construction. So no choice of percentage reproduces the CI at
        both points at once.
    (2) Holding the design fixed and inflating the residual noise tenfold
        widens the CI by roughly tenfold and leaves the band unchanged when
        the point is unchanged -- a band therefore cannot encode uncertainty.
    """
    x = [50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    y = [100.0, 130.0, 152.0, 175.0, 190.0, 215.0]
    fit = oracle.fit_ols(y, {"area": x})

    central = oracle.predict_intervals(fit, {"area": 75.0})
    far = oracle.predict_intervals(fit, {"area": 100.0})
    assert far["leverage"] > central["leverage"]

    def band(point, pct=0.10):
        return {"lower": point * (1.0 - pct), "upper": point * (1.0 + pct)}

    for pred in (central, far):
        assert not oracle.interval_close(
            band(pred["point"]), pred["mean_ci"], abs_tol=1e-9, rel_tol=0.0
        )
        assert not oracle.interval_close(
            band(pred["point"]), pred["prediction_interval"], abs_tol=1e-9, rel_tol=0.0
        )

    # (1) The CI's relative half-width is not constant across x0; the band's is.
    rel_central = (central["mean_ci"]["upper"] - central["point"]) / central["point"]
    rel_far = (far["mean_ci"]["upper"] - far["point"]) / far["point"]
    assert rel_central != pytest.approx(rel_far, rel=1e-6)

    # (2) Ten times the residual scatter, same design, same point -> ten times
    # the CI half-width; the band cannot move because the point did not.
    resid = np.asarray(fit["residuals"], dtype=float)
    fitted = np.asarray(fit["fitted"], dtype=float)
    noisy = oracle.fit_ols((fitted + 10.0 * resid).tolist(), {"area": x})
    p_noisy = oracle.predict_intervals(noisy, {"area": 75.0})

    assert p_noisy["point"] == pytest.approx(central["point"], rel=1e-10)
    half_central = central["mean_ci"]["upper"] - central["point"]
    half_noisy = p_noisy["mean_ci"]["upper"] - p_noisy["point"]
    assert half_noisy == pytest.approx(10.0 * half_central, rel=1e-9)
    assert band(p_noisy["point"]) == pytest.approx(band(central["point"]), rel=1e-10)
