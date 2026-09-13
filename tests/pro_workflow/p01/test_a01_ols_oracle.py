"""P01-A01: identity OLS vs numpy.linalg.lstsq + independent t-interval.

The oracle does not call production interval helpers. Documented DGP lives in conftest.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.worker import build_frozen_project
from modules.model_builder import CandidateSpec, fit_candidate
from modules.pro_workflow.residual_state import (
    XTX_INV_KIND_NORMALIZED,
    extract_residual_state,
    residual_state_is_complete,
)
from modules.valuation_batch import builtin_evaluate_fitted, restore_candidate_fit
from tests.pro_workflow.p01.conftest import (
    BETA_AREA,
    BETA_CONST,
    BETA_SUL,
    MEAN_CI_LEVEL,
    N,
    SEED,
    SYNTHETIC_LABEL,
    documented_identity_ols_frame,
    documented_request_spec,
    independent_ols_oracle,
)

ABS_TOL = 1e-8
REL_TOL = 1e-8
SCRATCH = Path("/tmp/grok-goal-c8528f369173/implementer")


def _close(a, b):
    return np.isclose(a, b, atol=ABS_TOL, rtol=REL_TOL)


def _prepared(frame: pd.DataFrame):
    X = frame[["area", "bairro_Sul"]].reset_index(drop=True)
    y = frame["preco"].reset_index(drop=True)
    row_ids = list(frame["id"])
    schema = {
        "version": 1,
        "columns": {
            "area": {
                "original_name": "area",
                "role": "predictor",
                "kind": "numeric",
                "unit": "m2",
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
            "bairro_Sul": {
                "original_name": "bairro",
                "role": "predictor",
                "kind": "categorical",
                "unit": None,
                "group_id": "bairro",
                "categories": ["Centro", "Sul"],
                "reference_category": "Centro",
            },
        },
        "groups": {"bairro": {"columns": ["bairro_Sul"], "base_variable": "bairro"}},
        "target": {"column": "preco", "unit": "BRL"},
    }
    return {
        "schema_version": "MP/1",
        "X": X,
        "y": y,
        "row_ids": row_ids,
        "feature_schema": schema,
        "encoder_state": {
            "base_variables": ["area", "bairro"],
            "dummy_columns": {"bairro": ["bairro_Sul"]},
            "reference_category": {"bairro": "Centro"},
            "synthetic": SYNTHETIC_LABEL,
        },
        "sample_ledger": {
            "used_row_ids": row_ids,
            "excluded_row_ids": [],
            "exclusion_reasons": {},
        },
        "issues": [],
        "dataset_sha256": "p01-a01-synthetic",
        "base_frame": frame.reset_index(drop=True),
        "contract_fixture": True,
        "contract_fixture_for": "P01-A01",
    }


def test_p01_a01_identity_ols_matches_independent_lstsq_and_t_interval(tmp_path):
    frame = documented_identity_ols_frame()
    assert len(frame) >= 30
    assert set(frame["bairro"].unique()) == {"Centro", "Sul"}

    # Independent design (oracle). Column order: intercept, area, bairro_Sul.
    X_oracle = np.column_stack(
        [np.ones(len(frame)), frame["area"].to_numpy(dtype=float), frame["bairro_Sul"].to_numpy(dtype=float)]
    )
    y_oracle = frame["preco"].to_numpy(dtype=float)
    x0 = np.array([1.0, 100.0, 1.0], dtype=float)
    oracle = independent_ols_oracle(X_oracle, y_oracle, x0)
    assert oracle["df"] > 0
    assert oracle["rank"] == 3
    # Non-degenerate: noise is present; coefficients near DGP but not a tautology.
    assert abs(oracle["beta"][1] - BETA_AREA) < 50.0
    assert abs(oracle["beta"][0] - BETA_CONST) < 20000.0
    assert abs(oracle["beta"][2] - BETA_SUL) < 5000.0

    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="p01-a01-identity",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    fit = fit_candidate(prepared, spec, documented_request_spec())
    assert fit.status == "fitted"
    assert fit.model_object is not None

    residual = extract_residual_state(fit)
    assert residual_state_is_complete(residual)
    assert residual["xtx_inv_kind"] == XTX_INV_KIND_NORMALIZED
    assert residual["scale_convention"] == "statsmodels.scale"
    order = residual["feature_order"]
    assert order[0] in {"const", "Intercept"}
    assert "area" in order
    assert "bairro_Sul" in order
    # normalized_cov is not sigma^2 * (X'X)^{-1}
    xtx_inv = np.asarray(residual["xtx_inv"], dtype=float)
    cov_if_scaled = float(residual["residual_scale"]) * xtx_inv
    assert not np.allclose(xtx_inv, cov_if_scaled) or residual["residual_scale"] == 1.0

    frozen = build_frozen_project(
        project_id="p01-a01",
        revision_id="rev-a01",
        request_spec=documented_request_spec(),
        input_bundle={"input_sha256": "p01-a01-input", "raw_frame": frame},
        prepared_dataset=prepared,
        winner_fit=fit,
        subject_design={
            "subject_id": "s1",
            "raw_values": {"area": 100.0, "bairro": "Sul", "bairro_Sul": 1.0},
            "supported": True,
        },
        normative={"edition": "NBR 14653-2:2011"},
        artifact_refs={},
        sample_ledger=prepared["sample_ledger"],
    )
    dumped = json.dumps(frozen, allow_nan=False)
    assert "model_object" not in dumped
    assert "pickle" not in dumped.lower()
    state = frozen["model_state"]
    assert state["residual_std"] is not None
    assert state["xtx_inv"] is not None
    assert state["xtx_inv_kind"] == XTX_INV_KIND_NORMALIZED

    restored = restore_candidate_fit(frozen)
    assert restored.get("model_object") in (None, restored.get("model_object"))
    assessment = builtin_evaluate_fitted(
        restored,
        {
            "subject_id": "s1",
            "raw_values": {"area": 100.0, "bairro": "Sul", "bairro_Sul": 1.0},
            "X": {"const": 1.0, "area": 100.0, "bairro_Sul": 1.0},
            "supported": True,
            "issues": [],
        },
        documented_request_spec(),
    )
    point = assessment["value"]["point"]
    mean_ci = assessment["value"]["mean_ci80"]
    pred = assessment["value"]["prediction_interval"]
    assert point is not None and math.isfinite(point)
    assert mean_ci is not None and pred is not None
    assert _close(point, oracle["point"])
    assert _close(mean_ci["lower"], oracle["mean_ci80"]["lower"])
    assert _close(mean_ci["upper"], oracle["mean_ci80"]["upper"])
    assert _close(pred["lower"], oracle["prediction_interval"]["lower"])
    assert _close(pred["upper"], oracle["prediction_interval"]["upper"])
    # Mean CI is not the prediction interval; ±15% is not a statistical interval.
    assert mean_ci["lower"] != pred["lower"] or mean_ci["upper"] != pred["upper"]
    width_mean = mean_ci["upper"] - mean_ci["lower"]
    width_pred = pred["upper"] - pred["lower"]
    assert width_pred > width_mean
    arb = assessment["value"]["arbitration_interval"]
    if arb:
        arb_width = arb["upper"] - arb["lower"]
        assert not _close(width_mean, arb_width)

    payload = {
        "label": SYNTHETIC_LABEL,
        "n": int(N),
        "seed": SEED,
        "feature_order": order,
        "oracle_point": oracle["point"],
        "shipped_point": point,
        "diff_point": abs(point - oracle["point"]),
        "oracle_mean_ci80": oracle["mean_ci80"],
        "shipped_mean_ci80": mean_ci,
        "oracle_prediction_interval": oracle["prediction_interval"],
        "shipped_prediction_interval": pred,
        "xtx_inv_kind": state["xtx_inv_kind"],
        "scale_convention": state["scale_convention"],
        "residual_std_oracle": oracle["sigma"],
        "residual_std_shipped": state["residual_std"],
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "p01-a01-ols.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    (tmp_path / "p01-a01-ols.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
