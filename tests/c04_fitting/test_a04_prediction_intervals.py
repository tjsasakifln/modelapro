"""C04-A04: stored point matches independent OLS; mean CI ≠ prediction interval; C06 limits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from modules.model_builder import evaluate_fitted, fit_candidate, _reset_dependency_caches
from tests.c04_fitting.conftest import make_prepared_dataset, make_request, make_spec, linear_market

SEED = 20260911
# Declared tolerance: independent QR-OLS on the same effective design.
ABS_TOL = 1e-8
REL_TOL = 1e-8


def _close(a, b):
    return np.isclose(a, b, atol=ABS_TOL, rtol=REL_TOL)


def test_independent_mean_prediction_matches_stored_point_and_mean_ci(monkeypatch):
    X, y, row_ids = linear_market(n=40, seed=SEED, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    spec = make_spec("area-quartos", ["area", "quartos"])
    fit = fit_candidate(prepared, spec, make_request())
    assert fit.status == "fitted"

    subject_x = {"area": 33.0, "quartos": 2.5}
    subject = {
        "subject_id": "s1",
        "raw_values": subject_x,
        "X": pd.DataFrame([subject_x]),
        "supported": True,
        "issues": [],
    }
    assessment = evaluate_fitted(fit, subject, make_request())

    used = list(fit.used_row_ids)
    pos = [row_ids.index(rid) for rid in used]
    X_used = X.iloc[pos][["area", "quartos"]].reset_index(drop=True)
    y_used = pd.Series(np.asarray(y.iloc[pos], dtype=float))
    X_design = sm.add_constant(X_used, has_constant="add", prepend=True)
    independent = sm.OLS(y_used, X_design).fit(method="qr", use_t=True)
    subj_row = pd.DataFrame([{"const": 1.0, "area": 33.0, "quartos": 2.5}], columns=list(X_design.columns))
    summary = independent.get_prediction(subj_row).summary_frame(alpha=0.20)

    point = assessment.value["point"]
    mean_ci = assessment.value["mean_ci80"]
    pred_int = assessment.value["prediction_interval"]
    assert point is not None
    assert np.isfinite(point)
    assert _close(point, float(summary["mean"].iloc[0]))
    assert mean_ci is not None
    assert pred_int is not None
    assert _close(mean_ci["lower"], float(summary["mean_ci_lower"].iloc[0]))
    assert _close(mean_ci["upper"], float(summary["mean_ci_upper"].iloc[0]))
    assert mean_ci["lower"] != pred_int["lower"] or mean_ci["upper"] != pred_int["upper"]
    assert set(mean_ci.keys()) >= {"lower", "upper"}
    assert set(pred_int.keys()) >= {"lower", "upper"}
    # Point is stored directly, not recovered from an interval midpoint if they drift.
    midpoint = 0.5 * (mean_ci["lower"] + mean_ci["upper"])
    assert _close(point, float(summary["mean"].iloc[0]))
    assert abs(point - midpoint) < abs(mean_ci["upper"] - mean_ci["lower"])
    assert assessment.used_row_ids == fit.used_row_ids
    assert assessment.excluded_row_ids == fit.excluded_row_ids
    assert assessment.value["arbitration_interval"] is None
    assert assessment.value["admissible_interval"] is None


def test_mean_ci_and_prediction_interval_are_distinct_fields():
    X, y, row_ids = linear_market(n=30, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    fit = fit_candidate(prepared, make_spec("area", ["area"]), make_request())
    assessment = evaluate_fitted(
        fit,
        {
            "subject_id": "s2",
            "raw_values": {"area": 20.0},
            "X": pd.DataFrame([{"area": 20.0}]),
            "supported": True,
        },
        make_request(),
    )
    value = assessment.value
    assert "mean_ci80" in value and "prediction_interval" in value
    assert value["mean_ci80"] is not value["prediction_interval"]
    width_mean = value["mean_ci80"]["upper"] - value["mean_ci80"]["lower"]
    width_obs = value["prediction_interval"]["upper"] - value["prediction_interval"]["lower"]
    assert width_obs > width_mean


def test_y_transform_without_c06_records_limitation(monkeypatch):
    _reset_dependency_caches()
    monkeypatch.setattr("modules.model_builder._load_c06", lambda: None)
    X, y, row_ids = linear_market(n=24, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    fit = fit_candidate(
        prepared,
        make_spec("log-y", ["area"], y_transformation="ln"),
        make_request(),
    )
    assert fit.status == "error"
    assert any(i["code"] == "c06_not_available" for i in fit.issues)
    assert any(i.get("evidence", {}).get("unmet_dependency") == "C06" for i in fit.issues)


def test_y_transform_calls_c06_and_does_not_declare_unvalidated_precision(monkeypatch):
    _reset_dependency_caches()
    calls = []

    def fake_fit(y_train, name, options=None):
        calls.append(("fit", name, int(len(y_train))))
        return {"name": name, "contract_fixture": True, "contract_fixture_for": "C06"}

    def fake_transform(y, state):
        calls.append(("transform", state["name"]))
        return np.log(np.asarray(y, dtype=float))

    def fake_inverse(prediction, state, residual_context=None):
        calls.append(("inverse", state["name"]))
        point = float(np.exp(prediction["point"]))
        return {
            "point": point,
            "mean_ci80": None,
            "prediction_interval": None,
            "estimand": "conditional_mean_original_unit",
            "limitations": ["interval_method_not_validated_for_log"],
            "interval_method_validated": False,
        }

    monkeypatch.setattr(
        "modules.model_builder._load_c06",
        lambda: {"fit": fake_fit, "transform": fake_transform, "inverse": fake_inverse},
    )
    rng = np.random.default_rng(SEED)
    x = np.linspace(10.0, 40.0, 30)
    y = np.exp(3.0 + 0.04 * x + rng.normal(0.0, 0.02, 30))
    prepared = make_prepared_dataset(pd.DataFrame({"area": x}), pd.Series(y, name="preco"))
    fit = fit_candidate(prepared, make_spec("logy", ["area"], y_transformation="ln"), make_request())
    assert fit.status == "fitted"
    assert calls[0][0] == "fit"
    assessment = evaluate_fitted(
        fit,
        {
            "subject_id": "s-log",
            "raw_values": {"area": 22.0},
            "X": pd.DataFrame([{"area": 22.0}]),
            "supported": True,
        },
        make_request(),
    )
    assert any(c[0] == "inverse" for c in calls)
    assert assessment.value["point"] is not None
    assert np.isfinite(assessment.value["point"])
    assert assessment.value["mean_ci80"] is None
    assert assessment.value["prediction_interval"] is None
    assert assessment.normative["precisao"]["status"] == "not_computed"
    assert assessment.normative["precisao"]["grade"] is None
    assert any(
        i["code"] in {"precisao_not_declared", "mean_ci_not_validated_on_original_unit", "target_transform_limitation"}
        for i in assessment.issues
    )
