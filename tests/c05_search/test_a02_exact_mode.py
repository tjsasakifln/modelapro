"""C05-A02: exact mode matches an independent itertools enumerator."""
import itertools

import numpy as np
import pandas as pd
import pytest

from modules.optimal_combination import (
    OptimalCombinationFinder,
    evaluate_search_candidate,
    ranking_tuple,
    search_models,
)
from modules.search_space import (
    build_candidate_spec,
    domain_valid_include_options,
    search_units_from_prepared,
)

from tests.c05_search.helpers import make_prepared, request_spec


def _small_df():
    area = np.array([50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0])
    ruido = np.array([12.0, 3.0, 27.0, 8.0, 19.0, 2.0, 15.0, 6.0, 22.0])
    noise = np.array([15.0, -8.0, 22.0, -30.0, 5.0, -12.0, 18.0, -3.0, 9.0])
    preco = 1000 * area + 20000 + noise
    return pd.DataFrame({"area": area, "ruido": ruido, "preco": preco})


def _independent_specs(prepared):
    units, _ = search_units_from_prepared(prepared, ["area", "ruido"])
    n = len(prepared["y"])
    max_vars = max(1, n // 3 - 1)
    max_vars = min(max_vars, len(units))
    specs = []
    for k in range(1, max_vars + 1):
        for subset in itertools.combinations(tuple(units), k):
            for choice in itertools.product(*[u.options for u in subset]):
                specs.append(build_candidate_spec(subset, choice))
    return specs, units, max_vars


def test_exact_mode_matches_independent_enumerator_twice():
    df = _small_df()
    prepared = make_prepared(df, "preco")
    spec = request_spec("preco", search_policy={"mode": "exact", "budget": 10_000, "seed": 0})

    independent_specs, units, max_vars = _independent_specs(prepared)
    assert len(independent_specs) == 63

    scored = [
        evaluate_search_candidate(prepared, s, spec) for s in independent_specs
    ]
    scored.sort(key=lambda r: r["candidate_id"])
    scored.sort(key=lambda r: r["_rank_tuple"], reverse=True)
    independent_ids = {s["candidate_id"] for s in independent_specs}
    independent_winner = next(
        r for r in scored if (r.get("admissibility") or {}).get("label") == "admissible"
    )

    result_a = search_models(prepared, None, spec)
    result_b = search_models(prepared, None, spec)

    for result in (result_a, result_b):
        audit = result["search_audit"]
        assert audit["possible"] == 63
        assert audit["generated"] == 63
        assert audit["evaluated"] == 63
        assert audit["coverage"]["enumeration"] == "exhaustive"
        assert audit["coverage"]["exact_optimum_guaranteed"] is True
        assert result["winner"] is not None
        history_ids = {h["candidate_id"] for h in audit["history"]}
        assert history_ids == independent_ids
        assert result["winner"]["candidate_id"] == independent_winner["candidate_id"]
        assert result["winner"]["candidate_spec"]["features"] == independent_winner["candidate_spec"]["features"]
        assert result["winner"]["metrics"]["original_rmse"] == pytest.approx(
            independent_winner["metrics"]["original_rmse"], abs=1e-9
        )
        assert result["winner"]["ranking"]["tie_break"] == "candidate_id_lexicographic_asc"

    assert result_a["winner"]["candidate_id"] == result_b["winner"]["candidate_id"]
    if result_a["winner"]["value"]["point"] is not None:
        assert result_a["winner"]["value"]["point"] == pytest.approx(
            result_b["winner"]["value"]["point"]
        )


def test_deterministic_tie_break_by_candidate_id():
    """Construct two records with identical ranking metrics; lower candidate_id wins."""
    rec_b = {
        "candidate_id": "b|y:identity|int:1",
        "candidate_spec": {"features": ["b"], "candidate_id": "b|y:identity|int:1"},
        "status": "fitted",
        "admissibility": {"numeric_technical": True, "framing": True, "label": "admissible"},
        "metrics": {"original_rmse": 1.0, "complexity": 1},
    }
    rec_a = {
        "candidate_id": "a|y:identity|int:1",
        "candidate_spec": {"features": ["a"], "candidate_id": "a|y:identity|int:1"},
        "status": "fitted",
        "admissibility": {"numeric_technical": True, "framing": True, "label": "admissible"},
        "metrics": {"original_rmse": 1.0, "complexity": 1},
    }
    key_a = ranking_tuple(rec_a)
    key_b = ranking_tuple(rec_b)
    assert key_a == key_b
    recs = [rec_b, rec_a]
    recs.sort(key=lambda r: r["candidate_id"])
    recs.sort(key=lambda r: ranking_tuple(r), reverse=True)
    assert recs[0]["candidate_id"] == "a|y:identity|int:1"


def test_find_best_model_delegates_to_search_models():
    df = _small_df()
    finder = OptimalCombinationFinder()
    legacy = finder.find_best_model(df, "preco", degree=1)
    prepared = make_prepared(df, "preco")
    spec = request_spec(
        "preco",
        search_policy={
            "mode": "auto",
            "budget": 200_000,
            "seed": 0,
            "retain_legacy_model": True,
        },
        evaluation_policy={"sample_size_rule": "nbr_item2_grau1", "remove_outliers": False},
    )
    mp1 = search_models(prepared, None, spec)
    assert legacy.success is True
    assert mp1["winner"] is not None
    winning_legacy = {
        OptimalCombinationFinder._base_name(c)
        for c in legacy.best_model.coefficients
        if c != "const"
    }
    winning_mp1 = set(mp1["winner"]["candidate_spec"]["base_variables"])
    assert winning_legacy == winning_mp1
    assert legacy.exhaustive is True
    assert legacy.combinations_tested == mp1["search_audit"]["evaluated"]
    assert mp1["search_audit"]["coverage"]["exact_optimum_guaranteed"] is True


def test_partial_coverage_is_never_labeled_global_optimum():
    rng = np.random.RandomState(0)
    n = 24
    data = {f"x{i}": rng.uniform(1.0, 9.0, n) for i in range(5)}
    data["y"] = data["x0"] * 4 + rng.normal(0, 0.2, n)
    df = pd.DataFrame(data)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "approximate", "budget": 20})
    result = search_models(prepared, None, spec)
    assert result["search_audit"]["coverage"]["exact_optimum_guaranteed"] is False
    assert result["search_audit"]["coverage"]["enumeration"] == "partial"


def test_insufficient_model_is_exploratory_not_implicitly_admissible():
    rec = {
        "candidate_id": "x|y:identity|int:1",
        "status": "fitted",
        "metrics": {"original_rmse": 1.0, "complexity": 1, "grau_fundamentacao": 3},
        "diagnostics": {},
        "coefficients": {"const": 1.0, "x": 2.0},
    }
    from modules.optimal_combination import classify_admissibility

    adm = classify_admissibility(
        rec, {"required_diagnostics": ["stability"], "min_fundamentacao_grade": 1}
    )
    assert adm["label"] == "exploratory"
    assert adm["eligibility_status"] == "exploratory"
    assert any("missing_required_diagnostic" in r for r in adm["reasons"])


def test_domain_options_match_transformer_for_small_space():
    df = _small_df()
    opts, dropped = domain_valid_include_options(df["area"])
    assert "linear" in opts
    assert not dropped
    assert len(opts) == 7
