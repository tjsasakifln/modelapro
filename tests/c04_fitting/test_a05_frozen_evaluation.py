"""C04-A05: frozen fit, C03 callback on effective sample, safe cancel/progress."""

from __future__ import annotations

import copy

import pandas as pd

from modules.model_builder import evaluate_fitted, fit_candidate
from tests.c04_fitting.conftest import make_prepared_dataset, make_request, make_spec, linear_market


def test_second_subject_does_not_change_coefficients_encoder_or_sample():
    X, y, row_ids = linear_market(n=32, extra_influence=True)
    encoder = {"contract_fixture": True, "categories": {"padrao": ["alto"]}, "imputer": {"area": 30.0}}
    prepared = make_prepared_dataset(X, y, row_ids, encoder_state=encoder)
    fit = fit_candidate(prepared, make_spec("m", ["area", "quartos"]), make_request())
    coef_0 = dict(fit.coefficients)
    encoder_0 = copy.deepcopy(fit.encoder_state)
    used_0 = list(fit.used_row_ids)
    sha_0 = fit.model_sha256

    a = evaluate_fitted(
        fit,
        {
            "subject_id": "A",
            "raw_values": {"area": 25.0, "quartos": 2.0},
            "X": pd.DataFrame([{"area": 25.0, "quartos": 2.0}]),
            "supported": True,
        },
        make_request(),
    )
    b = evaluate_fitted(
        fit,
        {
            "subject_id": "B",
            "raw_values": {"area": 48.0, "quartos": 4.0},
            "X": pd.DataFrame([{"area": 48.0, "quartos": 4.0}]),
            "supported": True,
        },
        make_request(),
    )
    assert a.value["point"] != b.value["point"]
    assert fit.coefficients == coef_0
    assert fit.encoder_state == encoder_0
    assert fit.used_row_ids == used_0
    assert fit.model_sha256 == sha_0
    assert a.used_row_ids == b.used_row_ids == used_0
    assert row_ids[-1] in a.used_row_ids


def test_predict_original_callback_uses_effective_sample_and_same_pipeline(monkeypatch):
    captured = {}

    def fake_assess(context):
        captured["n"] = context["n"]
        captured["k"] = context["k"]
        captured["used"] = list(context["used_row_ids"])
        captured["effective"] = context["effective_sample"]["used_row_ids"]
        captured["axes"] = context.get("axes") or []
        pred = context["predict_original"]({"area": 30.0, "quartos": 3.0})
        captured["callback_point"] = pred["point"]
        return {
            "edition": None,
            "rule_sources": [],
            "verification_status": "pending",
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
            "documentary": {},
            "issues": [{"code": "contract_fixture_c03", "severity": "info", "origin": "C03", "message": "labeled fixture", "affected_ids": [], "evidence": {"contract_fixture": True}}],
        }

    monkeypatch.setattr("modules.model_builder._load_assess_normative", lambda: fake_assess)
    X, y, row_ids = linear_market(n=30, extra_influence=True)
    prepared = make_prepared_dataset(X, y, row_ids)
    request = make_request(
        outlier_policy={
            "mode": "reviewed_exclusions",
            "scenario": "principal",
            "reviewed_exclusions": [
                {
                    "row_id": row_ids[-1],
                    "reason": "revisão documental da origem",
                    "author": "perito",
                    "origin": "human_review",
                }
            ],
        }
    )
    fit = fit_candidate(prepared, make_spec("m", ["area", "quartos"]), request)
    subject = {
        "subject_id": "A",
        "raw_values": {"area": 30.0, "quartos": 3.0},
        "X": pd.DataFrame([{"area": 30.0, "quartos": 3.0}]),
        "supported": True,
    }
    assessment = evaluate_fitted(fit, subject, request)
    assert captured["n"] == fit.diagnostics["n"]
    assert captured["k"] == fit.diagnostics["k"]
    assert captured["used"] == fit.used_row_ids
    assert captured["effective"] == fit.used_row_ids
    assert captured["callback_point"] is not None
    assert abs(captured["callback_point"] - assessment.value["point"]) < 1e-8
    area_axis = next(a for a in captured["axes"] if a["variable"] == "area")
    assert row_ids[-1] not in fit.used_row_ids
    assert area_axis["sample_max"] < 100.0
    assert area_axis["n"] == len(fit.used_row_ids)
    # Builder must not invent Tabela grades.
    assert assessment.normative["fundamentacao"]["grade"] is None
    assert not any("tabela" in (i.get("message") or "").lower() for i in fit.issues)


def test_c03_pending_when_assess_normative_missing(monkeypatch):
    monkeypatch.setattr("modules.model_builder._load_assess_normative", lambda: None)
    X, y, row_ids = linear_market(n=20, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    fit = fit_candidate(prepared, make_spec("m", ["area"]), make_request())
    assessment = evaluate_fitted(
        fit,
        {
            "subject_id": "A",
            "raw_values": {"area": 20.0},
            "X": pd.DataFrame([{"area": 20.0}]),
            "supported": True,
        },
        make_request(),
    )
    assert assessment.normative["verification_status"] == "pending"
    assert assessment.normative["precisao"]["status"] == "not_computed"
    assert any(i["code"] == "c03_not_available" for i in assessment.normative["issues"])


def test_cancel_at_safe_point_does_not_mutate_fit():
    X, y, row_ids = linear_market(n=20, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    fit = fit_candidate(prepared, make_spec("m", ["area"]), make_request())
    coef = dict(fit.coefficients)
    used = list(fit.used_row_ids)
    encoder = copy.deepcopy(fit.encoder_state)

    cancelled = evaluate_fitted(
        fit,
        {
            "subject_id": "A",
            "raw_values": {"area": 20.0},
            "X": pd.DataFrame([{"area": 20.0}]),
            "supported": True,
        },
        make_request(),
        cancel_requested=lambda: True,
    )
    assert cancelled.model_eligibility["status"] == "error"
    assert any(i["code"] == "cancelled" for i in cancelled.issues)
    assert fit.coefficients == coef
    assert fit.used_row_ids == used
    assert fit.encoder_state == encoder
    assert fit.status == "fitted"

    progress = []
    fit_candidate(
        prepared,
        make_spec("m2", ["area"]),
        make_request(),
        progress_callback=lambda p: progress.append(p),
        cancel_requested=lambda: False,
    )
    assert progress
    assert all(item["progress"] is None or 0.0 <= item["progress"] <= 1.0 for item in progress)
    assert progress[-1]["progress"] == 1.0


def test_fit_cancel_before_work_returns_error_without_model():
    X, y, row_ids = linear_market(n=16, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    fit = fit_candidate(
        prepared,
        make_spec("m", ["area"]),
        make_request(),
        cancel_requested=lambda: True,
    )
    assert fit.status == "error"
    assert fit.model_object is None
    assert fit.coefficients == {}
    assert any(i["code"] == "cancelled" for i in fit.issues)
