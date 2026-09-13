"""C05-A04: diverse approximate search, no false optimum, conditional weak predictor."""
import numpy as np
import pandas as pd

from modules.optimal_combination import search_models
from modules.search_space import parse_feature_name

from tests.c05_search.helpers import make_prepared, request_spec


def _bases_from_history(history):
    bases = set()
    for entry in history:
        for col in entry.get("variables") or []:
            _, base = parse_feature_name(col)
            bases.add(base)
    return bases


def test_approximate_search_covers_all_base_variables_not_top15_columns():
    rng = np.random.RandomState(11)
    n = 40
    # 12 strictly-positive variables: exhaustive space is huge; budget is small.
    data = {f"v{i}": rng.uniform(1.0, 20.0, n) for i in range(12)}
    data["y"] = 10 + 2 * data["v0"] + rng.normal(0, 0.5, n)
    df = pd.DataFrame(data)
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        search_policy={"mode": "approximate", "budget": 30, "seed": 11, "max_variables": 12},
        evaluation_policy={"sample_size_rule": None},
    )
    result = search_models(prepared, None, spec)
    audit = result["search_audit"]
    assert audit["mode"] == "approximate"
    assert audit["coverage"]["exact_optimum_guaranteed"] is False
    assert audit["coverage"]["pruning_proof"] is None
    assert audit["evaluated"] <= 30
    covered = _bases_from_history(audit["history"])
    # Diversity: every base variable appears (phase-1 singletons), not only 15 transformed columns.
    assert covered == {f"v{i}" for i in range(12)}
    assert "FALLBACK_TOP_N" not in str(audit.get("mode"))


def test_never_claims_optimum_without_pruning_proof():
    rng = np.random.RandomState(3)
    n = 24
    data = {f"v{i}": rng.uniform(1.0, 6.0, n) for i in range(8)}
    data["y"] = data["v0"] + rng.normal(0, 0.2, n)
    df = pd.DataFrame(data)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "approximate", "budget": 40})
    result = search_models(prepared, None, spec)
    cov = result["search_audit"]["coverage"]
    assert cov["exact_optimum_guaranteed"] is False
    assert cov["pruning_proof"] is None
    assert "optimum_disclaimer" in cov


def test_weak_conditional_predictor_is_not_dropped_for_univariate_correlation():
    """x_cond has weak marginal correlation but matters as x_signal * x_cond.

    Distractors have higher |corr| with y than x_cond. A top-N-by-|corr| prune
    of transformed columns would drop x_cond; diversity must keep it.
    """
    rng = np.random.RandomState(21)
    n = 80
    # Mean-zero factors so the moderator has weak marginal corr(y, x_cond);
    # y still depends on the product. Shifted copies stay domain-valid.
    s = rng.normal(0.0, 1.0, n)
    c = rng.normal(0.0, 1.0, n)
    y = 8 * s + 3.0 * s * c + rng.normal(0, 0.3, n)
    x_signal = s - s.min() + 1.0
    x_cond = c - c.min() + 1.0
    y_std = (y - y.mean()) / (y.std() + 1e-9)
    data = {"x_signal": x_signal, "x_cond": x_cond}
    for i in range(10):
        raw = 0.75 * y_std + 0.25 * rng.normal(0, 1.0, n)
        data[f"noise{i}"] = raw - raw.min() + 0.5
    data["y"] = y
    df = pd.DataFrame(data)
    corr_cond = abs(np.corrcoef(df["x_cond"], df["y"])[0, 1])
    stronger = sum(
        abs(np.corrcoef(df[f"noise{i}"], df["y"])[0, 1]) > corr_cond for i in range(10)
    )
    assert stronger >= 1
    assert corr_cond < abs(np.corrcoef(df["noise0"], df["y"])[0, 1])

    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        search_policy={"mode": "approximate", "budget": 80, "seed": 21, "max_variables": 12},
        evaluation_policy={"sample_size_rule": None},
    )
    result = search_models(prepared, None, spec)
    covered = _bases_from_history(result["search_audit"]["history"])
    assert "x_cond" in covered
    assert "x_signal" in covered
    assert result["search_audit"]["coverage"]["exact_optimum_guaranteed"] is False
    # Pair {x_signal, x_cond} must be generated (conditionally material).
    pair_seen = False
    for entry in result["search_audit"]["history"]:
        bases = {parse_feature_name(c)[1] for c in entry.get("variables") or []}
        if bases >= {"x_signal", "x_cond"}:
            pair_seen = True
            break
    assert pair_seen, "diversity search must generate the conditionally material pair"
