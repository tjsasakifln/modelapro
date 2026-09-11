"""C05-A03: original-scale ranking, no sample-removal bonus, shortlist disclosure."""
import numpy as np
import pandas as pd
import pytest

from modules.optimal_combination import classify_admissibility, ranking_tuple, search_models

from tests.c05_search.helpers import make_prepared, request_spec


def test_ranking_does_not_compare_r2_across_target_scales():
    """ln(y) can have higher R² on the transformed scale while losing on original RMSE."""
    rng = np.random.RandomState(4)
    n = 40
    x = np.linspace(1.0, 4.0, n)
    y = 200 + 30 * x + rng.normal(0, 2.0, n)
    df = pd.DataFrame({"x": x, "y": y})
    prepared = make_prepared(df, "y")

    def inverse_ln(pred, state, residual_context=None):
        return np.exp(np.asarray(pred, dtype=float))

    spec = request_spec(
        "y",
        search_policy={
            "mode": "exact",
            "budget": 500,
            "y_transformations": ["identity", "ln"],
            "peer_hooks": {
                "labeled": "CONTRACT_FIXTURE",
                "fit_candidate": None,
                "evaluate_fitted": None,
                "inverse_target": inverse_ln,
            },
        },
        evaluation_policy={"sample_size_rule": "nbr_item2_grau1", "remove_outliers": False},
    )
    result = search_models(prepared, None, spec)
    winner = result["winner"]
    assert winner is not None
    y_name = (winner["candidate_spec"].get("y_transformation") or {}).get("name")
    assert y_name in ("identity", "linear")
    assert winner["metrics"].get("y_transformation") in ("identity", "linear")
    assert "original_rmse" in winner["metrics"]
    # Transformed-target R² must not be the ranking key.
    assert "r2_across_transformed_vs_original_scales" in (
        result["search_audit"]["objective"].get("does_not_use") or []
    )


def test_ranking_tuple_ignores_automatic_row_removal_and_transformed_r2():
    better_full = {
        "candidate_id": "keep|y:identity|int:1",
        "status": "fitted",
        "admissibility": {"numeric_technical": True, "framing": True, "label": "admissible"},
        "metrics": {
            "original_rmse": 10.0,
            "r2_adjusted": 0.50,
            "complexity": 1,
            "n_outliers_removed": 0,
        },
        "candidate_spec": {"features": ["x"]},
    }
    removal_winner_on_r2 = {
        "candidate_id": "drop|y:identity|int:1",
        "status": "fitted",
        "admissibility": {"numeric_technical": True, "framing": True, "label": "admissible"},
        "metrics": {
            "original_rmse": 20.0,
            "r2_adjusted": 0.99,
            "complexity": 1,
            "n_outliers_removed": 8,
        },
        "candidate_spec": {"features": ["x"]},
    }
    key_keep = ranking_tuple(better_full)
    key_drop = ranking_tuple(removal_winner_on_r2)
    assert key_keep > key_drop
    transformed = {
        "candidate_id": "logy|y:ln|int:1",
        "status": "fitted",
        "admissibility": {"numeric_technical": True, "framing": True, "label": "admissible"},
        "metrics": {
            "original_rmse": 50.0,
            "r2_adjusted": 0.999,
            "r2_adjusted_scale": "transformed_target",
            "complexity": 1,
        },
        "candidate_spec": {"features": ["x"]},
    }
    assert ranking_tuple(better_full) > ranking_tuple(transformed)


def test_search_does_not_prefer_candidate_that_only_wins_by_dropping_rows():
    rng = np.random.RandomState(5)
    n = 36
    x = np.linspace(10.0, 40.0, n)
    y = 5 * x + 20 + rng.normal(0, 1.0, n)
    y[0] = y[0] + 400
    df = pd.DataFrame({"x": x, "y": y})
    prepared = make_prepared(df, "y")
    spec_no_drop = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 200},
        evaluation_policy={"remove_outliers": False},
    )
    spec_drop = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 200, "use_cache": False},
        evaluation_policy={"remove_outliers": True},
    )
    no_drop = search_models(prepared, None, spec_no_drop)
    dropped = search_models(prepared, None, spec_drop)
    assert no_drop["winner"] is not None
    # Ranking key never includes n_outliers_removed; both winners are scored on original RMSE.
    assert "n_outliers_removed" not in (
        no_drop["search_audit"]["objective"].get("required_criteria") or []
    )
    assert dropped["winner"] is not None
    assert "original_rmse" in no_drop["winner"]["metrics"]
    assert "automatic_sample_row_removal" in (
        no_drop["search_audit"]["objective"].get("does_not_use") or []
    )


def test_shortlist_discloses_full_objective_only_on_shortlist():
    rng = np.random.RandomState(6)
    n = 20
    df = pd.DataFrame(
        {
            "x1": rng.uniform(1, 8, n),
            "x2": rng.uniform(1, 8, n),
            "y": rng.uniform(20, 40, n),
        }
    )
    # Make y depend on x1 so ranking is not degenerate.
    df["y"] = 10 + 4 * df["x1"] + rng.normal(0, 0.3, n)
    prepared = make_prepared(df, "y")
    calls = {"n": 0, "ids": []}

    def extra_objective(record):
        calls["n"] += 1
        calls["ids"].append(record["candidate_id"])
        return {"extra_objective_score": 1.0 / (1.0 + record["metrics"].get("original_rmse", 1.0))}

    spec = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 500},
        evaluation_policy={
            "shortlist_size": 3,
            "extra_objective": extra_objective,
        },
    )
    result = search_models(prepared, None, spec)
    audit = result["search_audit"]
    assert audit["evaluated"] > 3
    assert calls["n"] == 3
    assert audit["objective"]["full_objective_evaluated_on"] == "shortlist"
    assert audit["coverage"]["ranking_objective"] == "shortlist_only"
    assert audit["coverage"]["exact_optimum_guaranteed"] is False
    codes = [i["code"] for i in result["issues"]]
    assert "full_objective_shortlist_only" in codes


def test_higher_grade_does_not_waive_required_diagnostics():
    high_grade_no_diag = {
        "candidate_id": "g3",
        "status": "fitted",
        "metrics": {
            "original_rmse": 3.0,
            "complexity": 2,
            "grau_fundamentacao": 3,
        },
        "diagnostics": {},
        "coefficients": {"const": 1.0, "x": 1.0},
    }
    adm = classify_admissibility(
        high_grade_no_diag,
        {
            "min_fundamentacao_grade": 1,
            "required_diagnostics": ["stability"],
            "require_precision": True,
        },
    )
    assert adm["label"] == "exploratory"
    assert adm["numeric_technical"] is True
    assert adm["framing"] is False
    assert "missing_required_diagnostic:stability" in adm["reasons"]
    assert "missing_required_precision" in adm["reasons"]


def test_c07_evaluate_procedure_is_not_imported_or_called():
    import modules.optimal_combination as oc

    assert not hasattr(oc, "evaluate_procedure")
    rng = np.random.RandomState(0)
    df = pd.DataFrame({"x": rng.uniform(1, 5, 18), "y": rng.uniform(10, 20, 18)})
    df["y"] = 2 * df["x"] + 3
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 50})
    result = search_models(prepared, None, spec)
    assert result["winner"] is not None
    assert "evaluate_procedure" not in oc.__dict__
