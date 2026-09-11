"""C05-A01: possible count 262143, coverage labels, [] vs null."""
import numpy as np
import pandas as pd

from modules.optimal_combination import search_models
from modules.search_space import (
    count_exhaustive_candidates,
    derived_max_vars,
    possible_count_for_units,
    resolve_authorized_base_variables,
    search_units_from_prepared,
)

from tests.c05_search.helpers import make_prepared, request_spec


def test_six_variables_seven_options_possible_count_is_262143():
    counts = [7, 7, 7, 7, 7, 7]
    assert count_exhaustive_candidates(counts, max_vars=6) == 262143
    assert count_exhaustive_candidates(counts, max_vars=None) == 262143
    assert 8**6 - 1 == 262143


def test_search_audit_possible_is_262143_without_fitting_the_space():
    rng = np.random.RandomState(1)
    n = 30  # n//3 - 1 = 9, so max_vars is not truncated below 6
    data = {f"x{i}": rng.uniform(1.0, 20.0, n) for i in range(6)}
    data["y"] = 50 + 2 * data["x0"] + rng.normal(0, 0.5, n)
    df = pd.DataFrame(data)
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        candidate_cols=None,
        search_policy={"mode": "approximate", "budget": 40, "seed": 0},
    )
    result = search_models(prepared, None, spec)
    audit = result["search_audit"]
    assert audit["possible"] == 262143
    assert audit["evaluated"] <= 40
    assert audit["evaluated"] < audit["possible"]
    assert audit["coverage"]["enumeration"] == "partial"
    assert audit["coverage"]["exact_optimum_guaranteed"] is False
    assert audit["coverage"]["ranking_objective"] != "full"


def test_stopped_budget_does_not_claim_full_objective():
    rng = np.random.RandomState(2)
    n = 24
    data = {f"x{i}": rng.uniform(1.0, 8.0, n) for i in range(6)}
    data["y"] = 10 + data["x0"] + rng.normal(0, 0.3, n)
    df = pd.DataFrame(data)
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        search_policy={"mode": "auto", "budget": 25, "exact_count_threshold": 200_000},
    )
    result = search_models(prepared, None, spec)
    audit = result["search_audit"]
    assert audit["possible"] == 262143
    assert audit["evaluated"] <= 25
    assert audit["coverage"]["exact_optimum_guaranteed"] is False
    codes = {i["code"] for i in result["issues"]}
    assert "approximate_due_to_budget" in codes or audit["mode"] == "approximate"


def test_candidate_cols_empty_list_is_error_not_all_columns():
    df = pd.DataFrame({"a": np.arange(12) + 1.0, "b": np.arange(12) + 2.0, "y": np.arange(12) * 3.0 + 10})
    prepared = make_prepared(df, "y")
    spec = request_spec("y", candidate_cols=[])
    result = search_models(prepared, None, spec)
    assert result["winner"] is None
    codes = [i["code"] for i in result["issues"]]
    assert "no_authorized_variables" in codes
    assert result["search_audit"]["evaluated"] == 0


def test_candidate_cols_null_selects_by_role():
    df = pd.DataFrame(
        {
            "a": np.linspace(1, 10, 15),
            "b": np.linspace(2, 11, 15),
            "id_col": np.arange(15),
            "y": np.linspace(10, 40, 15),
        }
    )
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        candidate_cols=None,
        roles={"a": "predictor", "b": "predictor", "id_col": "identifier", "y": "target"},
    )
    authorized, issues = resolve_authorized_base_variables(
        spec, ["a", "b", "id_col"], target_col="y"
    )
    assert authorized == ["a", "b"]
    assert not any(i["severity"] == "error" for i in issues)
    result = search_models(prepared, None, spec)
    used = set()
    for entry in result["search_audit"]["history"]:
        used.update(entry["variables"])
    bases = set()
    for v in used:
        bases.add(v if "(" not in v else v[v.index("(") + 1 : -1])
    assert "id_col" not in bases
    assert "a" in bases or "b" in bases


def test_max_vars_not_truncated_when_sample_is_sufficient():
    n = 30
    units_n = 6
    cap = derived_max_vars(n, units_n, {}, {"sample_size_rule": "nbr_item2_grau1"})
    assert cap == 6
    cap_small = derived_max_vars(9, units_n, {}, {"sample_size_rule": "nbr_item2_grau1"})
    assert cap_small == 2


def test_units_from_positive_frame_have_seven_options_each():
    rng = np.random.RandomState(0)
    n = 30
    data = {f"x{i}": rng.uniform(1.0, 5.0, n) for i in range(6)}
    data["y"] = data["x0"] * 2
    prepared = make_prepared(pd.DataFrame(data), "y")
    units, _ = search_units_from_prepared(prepared, [f"x{i}" for i in range(6)])
    assert len(units) == 6
    assert all(len(u.options) == 7 for u in units)
    assert possible_count_for_units(units, 6) == 262143
