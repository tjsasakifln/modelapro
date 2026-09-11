"""C04-A03: constant, intercept, dummy trap, duplicate ids, singular, insufficient n."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from modules.model_builder import fit_candidate
from tests.c04_fitting.conftest import make_prepared_dataset, make_request, make_spec


SEED = 20260911


def test_constant_already_present_is_not_added_twice():
    rng = np.random.default_rng(SEED)
    x = np.linspace(1.0, 10.0, 25)
    y = 4.0 * x + 7.0 + rng.normal(0.0, 0.2, 25)
    X = pd.DataFrame({"const": np.ones(25), "x": x})
    prepared = make_prepared_dataset(X, y)
    fit = fit_candidate(prepared, make_spec("const-in-x", ["const", "x"], intercept=True), make_request())
    assert fit.status == "fitted"
    assert fit.diagnostics["constant_already_present"] is True
    assert fit.diagnostics["intercept_added"] is False
    assert fit.diagnostics["constant_counted_twice"] is False
    const_cols = [c for c in fit.diagnostics["design_columns"] if c == "const" or c in fit.diagnostics["constant_columns_in_features"]]
    assert len(set(fit.diagnostics["design_columns"])) == len(fit.diagnostics["design_columns"])
    assert sum(1 for c in fit.diagnostics["design_columns"] if c == "const") == 1
    assert fit.diagnostics["k"] == 1
    assert fit.diagnostics["n_design_columns"] == 2
    assert fit.diagnostics["rank"] == 2
    assert any(i["code"] == "constant_already_present" for i in fit.issues)
    # Independent check: adding another constant would raise in statsmodels.
    raised = False
    try:
        sm.add_constant(X, has_constant="raise")
    except ValueError:
        raised = True
    assert raised is True


def test_intercept_false_does_not_add_constant():
    rng = np.random.default_rng(SEED)
    x = np.linspace(1.0, 8.0, 20)
    y = 2.0 * x + rng.normal(0.0, 0.15, 20)
    X = pd.DataFrame({"x": x})
    prepared = make_prepared_dataset(X, y)
    fit = fit_candidate(prepared, make_spec("no-intercept", ["x"], intercept=False), make_request())
    assert fit.status == "fitted"
    assert fit.diagnostics["intercept_added"] is False
    assert fit.diagnostics["has_intercept"] is False
    assert "const" not in fit.coefficients
    assert fit.diagnostics["k"] == 1
    assert fit.diagnostics["n_design_columns"] == 1
    assert any(i["code"] == "no_intercept" for i in fit.issues)


def test_collinear_dummy_group_is_rejected_as_rank_deficient():
    n = 24
    tipo = np.array(["A"] * 8 + ["B"] * 8 + ["C"] * 8)
    X = pd.DataFrame(
        {
            "tipo_A": (tipo == "A").astype(float),
            "tipo_B": (tipo == "B").astype(float),
            "tipo_C": (tipo == "C").astype(float),
        }
    )
    y = pd.Series(np.linspace(10.0, 40.0, n))
    prepared = make_prepared_dataset(X, y)
    spec = make_spec(
        "dummies-full",
        ["tipo_A", "tipo_B", "tipo_C"],
        intercept=True,
        feature_groups={"tipo": ["tipo_A", "tipo_B", "tipo_C"]},
    )
    fit = fit_candidate(prepared, spec, make_request())
    assert fit.status == "rejected"
    assert fit.diagnostics["rank_deficient"] is True
    assert fit.diagnostics["singular"] is True
    assert fit.diagnostics["pinv_used"] is False
    assert fit.model_object is None
    assert fit.coefficients == {}
    assert fit.diagnostics["rank"] < fit.diagnostics["n_design_columns"]
    assert any(i["code"] == "collinear_dummy_group" for i in fit.issues)
    assert any(i["code"] == "rank_deficient" for i in fit.issues)


def test_duplicate_row_ids_rejected_and_duplicate_index_diagnosed():
    x = np.linspace(1.0, 10.0, 12)
    y = 3.0 * x + 1.0
    X = pd.DataFrame({"x": x}, index=[0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    prepared = make_prepared_dataset(X, y, row_ids=[f"r{i}" for i in range(12)])
    prepared["X"].index = X.index
    # Re-inject duplicate index labels through X while keeping unique row_ids.
    prepared["X"] = pd.DataFrame({"x": x}, index=[0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    fit_unique_ids = fit_candidate(prepared, make_spec("dup-index", ["x"]), make_request())
    assert fit_unique_ids.status == "fitted"
    assert fit_unique_ids.diagnostics["duplicate_index_count"] >= 1
    assert any(i["code"] == "duplicate_index_labels" for i in fit_unique_ids.issues)

    prepared_dup_ids = make_prepared_dataset(
        pd.DataFrame({"x": x}),
        y,
        row_ids=["a", "b", "b", "c"] + [f"r{i}" for i in range(4, 12)],
    )
    fit_dup_ids = fit_candidate(prepared_dup_ids, make_spec("dup-ids", ["x"]), make_request())
    assert fit_dup_ids.status == "rejected"
    assert any(i["code"] == "duplicate_row_ids" for i in fit_dup_ids.issues)


def test_singular_matrix_rejected_without_pinv_coefficients():
    rng = np.random.default_rng(SEED)
    x1 = np.linspace(1.0, 20.0, 30)
    x2 = 2.0 * x1
    y = 5.0 + 1.5 * x1 + rng.normal(0.0, 0.3, 30)
    X = pd.DataFrame({"x1": x1, "x2": x2})
    prepared = make_prepared_dataset(X, y)
    fit = fit_candidate(prepared, make_spec("singular", ["x1", "x2"]), make_request())
    assert fit.status == "rejected"
    assert fit.diagnostics["singular"] is True
    assert fit.diagnostics["rank_deficient"] is True
    assert fit.diagnostics["pinv_used"] is False
    assert fit.diagnostics["rank"] < fit.diagnostics["n_design_columns"]
    assert fit.model_object is None
    assert fit.coefficients == {}
    # pinv would produce a split of the slope; we must not.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pinv_model = sm.OLS(y, sm.add_constant(X)).fit(method="pinv")
    assert "x1" in pinv_model.params.index
    assert fit.status != "fitted"


def test_insufficient_n_after_preparation_is_structured_rejection():
    X = pd.DataFrame({"x": [1.0, 2.0]})
    y = pd.Series([3.0, 5.0])
    prepared = make_prepared_dataset(X, y, row_ids=["a", "b"])
    fit = fit_candidate(prepared, make_spec("tiny", ["x"], intercept=True), make_request())
    assert fit.status == "rejected"
    assert any(i["code"] == "insufficient_n" for i in fit.issues)
    assert fit.diagnostics["n"] == 2
    assert fit.diagnostics["n_design_columns"] == 2
    assert fit.model_object is None
    assert fit.diagnostics["numerical_failure"] is False


def test_numerical_failure_is_distinct_from_normative_non_enquadramento(monkeypatch):
    from modules import model_builder as mb

    def boom(arr):
        return 0, "rank_numerical_failure:simulated"

    monkeypatch.setattr(mb, "_design_rank", boom)
    X = pd.DataFrame({"x": np.linspace(1.0, 10.0, 15)})
    y = pd.Series(2.0 * X["x"] + 1.0)
    prepared = make_prepared_dataset(X, y)
    fit = fit_candidate(prepared, make_spec("num-fail", ["x"]), make_request())
    assert fit.status == "error"
    assert fit.diagnostics["numerical_failure"] is True
    assert any(i["code"] == "numerical_failure" for i in fit.issues)
    assert fit.diagnostics.get("not_enquadramento") is True
    # Rejection of NBR enquadramento is C03, not this status.
    assert fit.status != "rejected"
