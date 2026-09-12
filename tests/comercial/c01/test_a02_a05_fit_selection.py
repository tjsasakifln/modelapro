"""C01-A02/A05: independent numeric reference and declared-objective ranking."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from modules.model_builder import CandidateSpec, fit_candidate
from modules.optimal_combination import ranking_tuple, search_models
from modules.target_transform import inverse_target_prediction
from tests.c05_search.helpers import make_prepared, request_spec
from tests.pro_workflow.p01.conftest import (
    documented_identity_ols_frame,
    documented_request_spec,
    independent_ols_oracle,
)
from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared


def test_identity_ols_matches_independent_lstsq_oracle():
    frame = documented_identity_ols_frame()
    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="c01-ols",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    fit = fit_candidate(prepared, spec, documented_request_spec())
    assert fit.status == "fitted"
    X = np.column_stack(
        [
            np.ones(len(frame)),
            frame["area"].to_numpy(dtype=float),
            frame["bairro_Sul"].to_numpy(dtype=float),
        ]
    )
    y = frame["preco"].to_numpy(dtype=float)
    x0 = np.array([1.0, 73.5, 0.0])
    oracle = independent_ols_oracle(X, y, x0)
    beta = fit.coefficients
    assert math.isclose(float(beta["const"]), float(oracle["beta"][0]), rel_tol=1e-8, abs_tol=1e-6)
    assert math.isclose(float(beta["area"]), float(oracle["beta"][1]), rel_tol=1e-8, abs_tol=1e-6)
    diag = fit.diagnostics or {}
    assert int(diag.get("df_resid") or 0) == int(oracle["df"])
    from modules.valuation_batch import builtin_evaluate_fitted

    design = {
        "subject_id": "s",
        "raw_values": {"area": 73.5, "bairro": "Centro"},
        "X": pd.DataFrame([{"area": 73.5, "bairro_Sul": 0.0}]),
        "supported": True,
        "issues": [],
    }
    got = builtin_evaluate_fitted(fit, design, documented_request_spec())
    value = got["value"]
    assert math.isclose(float(value["point"]), float(oracle["point"]), rel_tol=1e-8, abs_tol=1e-4)
    assert math.isclose(float(value["mean_ci80"]["lower"]), float(oracle["mean_ci80"]["lower"]), rel_tol=1e-6, abs_tol=1e-3)
    assert math.isclose(float(value["prediction_interval"]["lower"]), float(oracle["prediction_interval"]["lower"]), rel_tol=1e-6, abs_tol=1e-3)
    assert value.get("arbitration_interval") != value.get("mean_ci80")


def test_log_inverse_is_exp_not_product_helper():
    from modules.target_transform import fit_target_transform, transform_target

    y = np.array([100.0, 250.0, math.e])
    state = fit_target_transform(y, "log")
    z = transform_target(y, state)
    inverted = inverse_target_prediction(z, state)
    arr = np.asarray(inverted["point"], dtype=float).reshape(-1)
    assert np.allclose(arr, y, rtol=1e-12, atol=1e-9)
    assert np.allclose(arr, np.exp(np.asarray(z, dtype=float)), rtol=1e-12)


def test_singular_design_is_rejected_not_fitted_with_warning():
    df = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "x_copy": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "y": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
        }
    )
    prepared = _prepared_xy(df, "y")
    spec = CandidateSpec(
        candidate_id="c01-sing",
        features=["x", "x_copy"],
        base_variables=["x", "x_copy"],
        feature_groups={},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    fit = fit_candidate(prepared, spec, documented_request_spec())
    assert fit.status in {"rejected", "error"}
    assert fit.status != "fitted"
    codes = {i.get("code") for i in (fit.issues or [])}
    assert "rank_deficient" in codes or "ill_conditioned" in codes or "numerical_failure" in codes


def _prepared_xy(df: pd.DataFrame, target: str):
    X = df.drop(columns=[target]).reset_index(drop=True)
    y = df[target].reset_index(drop=True)
    row_ids = [f"r{i}" for i in range(len(df))]
    columns = {
        c: {
            "original_name": c,
            "role": "predictor",
            "kind": "numeric",
            "unit": None,
            "group_id": None,
            "categories": None,
            "reference_category": None,
        }
        for c in X.columns
    }
    return {
        "schema_version": "MP/1",
        "X": X,
        "y": y,
        "row_ids": row_ids,
        "feature_schema": {"version": 1, "columns": columns, "groups": {}, "target": {"column": target}},
        "encoder_state": {"column_order": list(X.columns), "base_variables": [
            {"original_name": c, "kind": "numeric"} for c in X.columns
        ]},
        "sample_ledger": {},
        "issues": [],
        "dataset_sha256": "synthetic-c01",
        "base_frame": X.copy(),
    }


def test_declared_aic_is_the_ranking_metric():
    rng = np.random.RandomState(3)
    n = 40
    x = np.linspace(1.0, 8.0, n)
    y = 10 + 2 * x + rng.normal(0, 0.4, n)
    df = pd.DataFrame({"x": x, "y": y})
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 200, "objective": "aic", "use_cache": False},
    )
    result = search_models(prepared, None, spec)
    audit = result["search_audit"]["objective"]
    assert audit["name"] == "aic"
    assert audit["metric"] == "aic"
    assert "aic" in (audit.get("required_criteria") or [])
    assert result["winner"] is not None
    assert "aic" in (result["winner"].get("metrics") or {})
    a = {"metrics": {"aic": 10.0, "original_rmse": 99.0}, "admissibility": {"numeric_technical": True, "framing": True}, "candidate_id": "a"}
    b = {"metrics": {"aic": 50.0, "original_rmse": 1.0}, "admissibility": {"numeric_technical": True, "framing": True}, "candidate_id": "b"}
    assert ranking_tuple(a, audit) > ranking_tuple(b, audit)


def test_declared_rmse_does_not_use_aic():
    spec = request_spec("y", search_policy={"objective": "original_scale_error"})
    from modules.optimal_combination import _objective_descriptor

    desc = _objective_descriptor(spec["search_policy"], spec["evaluation_policy"])
    assert desc["name"] == "original_scale_error"
    assert desc["metric"] == "original_rmse"
    assert desc.get("budget_is_not_global_optimum") is True


def test_holdout_policy_does_not_feed_search_ranking():
    rng = np.random.RandomState(8)
    n = 36
    x = np.linspace(10.0, 40.0, n)
    y = 5 * x + 20 + rng.normal(0, 1.0, n)
    df = pd.DataFrame({"x": x, "y": y})
    prepared = make_prepared(df, "y")
    spec_none = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 50, "use_cache": False, "objective": "original_scale_error"},
        evaluation_policy={"method": "none"},
    )
    spec_holdout = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 50, "use_cache": False, "objective": "original_scale_error"},
        evaluation_policy={"method": "holdout", "partitions": {"fraction": 0.3}, "seed": 1},
    )
    a = search_models(prepared, None, spec_none)
    b = search_models(prepared, None, spec_holdout)
    assert a["winner"] is not None and b["winner"] is not None
    assert a["winner"]["candidate_id"] == b["winner"]["candidate_id"]


def test_subject_specific_scope_is_recorded_as_fact():
    rng = np.random.RandomState(2)
    n = 30
    df = pd.DataFrame({"x": np.linspace(1, 10, n), "y": 3 * np.linspace(1, 10, n) + rng.normal(0, 0.2, n)})
    prepared = make_prepared(df, "y")
    spec = request_spec(
        "y",
        search_policy={
            "mode": "exact",
            "budget": 20,
            "use_cache": False,
            "model_scope": "subject_specific",
        },
    )
    subject = {"raw_values": {"x": 5.0}, "X": pd.DataFrame([{"x": 5.0}]), "supported": True}
    result = search_models(prepared, subject, spec)
    audit = result["search_audit"]
    assert audit["selection_scope"] == "subject_specific"
    assert audit["selection_conditioned_on_subject"] is True
