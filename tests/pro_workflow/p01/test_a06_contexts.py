"""P01-A06: workflow_context + report_context JSON round-trip; series = used_row_ids."""

from __future__ import annotations

import json
from pathlib import Path

from backend.worker import build_frozen_project, build_report_context
from modules.model_builder import CandidateSpec, fit_candidate
from modules.pro_workflow.report_context import formula_from_coefficients
from modules.pro_workflow.residual_state import extract_residual_state
from modules.pro_workflow.workflow_context import build_workflow_context
from modules.result_contract import dumps_strict
from tests.pro_workflow.p01.conftest import (
    SYNTHETIC_LABEL,
    documented_identity_ols_frame,
    documented_request_spec,
)
from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared

SCRATCH = Path("/tmp/grok-goal-c8528f369173/implementer")
DOCS = Path(__file__).resolve().parents[3] / "docs" / "campaigns" / "MP-PRO-20260911" / "P01"


def test_p01_a06_snapshot_and_report_context_json_roundtrip(tmp_path):
    frame = documented_identity_ols_frame()
    # Exclude one row so series must not include the pre-exclusion base.
    used_ids = list(frame["id"][:-1])
    excluded_ids = [str(frame["id"].iloc[-1])]
    used_frame = frame.iloc[:-1].reset_index(drop=True)
    prepared = _prepared(used_frame)
    prepared["sample_ledger"]["used_row_ids"] = used_ids
    prepared["sample_ledger"]["excluded_row_ids"] = excluded_ids
    spec = CandidateSpec(
        candidate_id="p01-a06",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    req = documented_request_spec()
    fit = fit_candidate(prepared, spec, req)
    assert list(fit.used_row_ids) == used_ids
    residual = extract_residual_state(fit)
    report = build_report_context(
        request_spec=req,
        input_bundle={"raw_frame": frame, "input_sha256": "p01-a06"},
        prepared_dataset=prepared,
        used_row_ids=used_ids,
        excluded_row_ids=excluded_ids,
        winner_fit=fit,
    )
    assert report["series_row_ids"] == used_ids
    assert str(frame["id"].iloc[-1]) not in report["series_row_ids"]
    assert report["fitted_values"] is not None
    assert len(report["fitted_values"]) == len(used_ids)
    assert len(report["residuals"]) == len(used_ids)
    assert len(report["observed_values"]) == len(used_ids)
    assert report["series_scale"] == "original"
    assert report["series_unit"] in {"BRL", "original", req["target_unit"]}
    formula = formula_from_coefficients(fit.coefficients, residual["feature_order"], target_name="preco")
    assert formula and "preco =" in formula
    wf = build_workflow_context(
        request_spec=req,
        subject_raw={"area": 100.0, "bairro": "Sul"},
        validation={"fundamentacao": {"grade": None, "pending_items": [1]}, "documentary": {"status": "pending"}},
        search_audit={"selection_scope": "population_model", "selection_conditioned_on_subject": False},
        frozen_project={"model_scope": "population_model", "selection_conditioned_on_subject": False},
        limitation_codes=list(residual.get("limitations") or []),
    )
    assert wf["schema_version"] == "MP-PRO/1"
    assert wf["requested_minimum_grade"] is None
    assert wf["grade_requirement_status"] == "not_requested"
    assert wf["selection_scope"] == "population_model"
    assert wf["selection_conditioned_on_subject"] is False
    assert isinstance(wf["limitation_codes"], list)
    snapshot = {
        "schema_version": "MP/1",
        "job_id": "job-p01-a06",
        "project_id": "p01-a06",
        "input_sha256": "p01-a06",
        "code_sha": "p01-test",
        "reference_date": "2024-06-01",
        "generated_at": "2024-06-15T12:00:00+00:00",
        "target": {"column": "preco", "unit": "BRL", "estimand": "E[Y|X]"},
        "value": {"point": 1.0, "mean_ci80": None, "prediction_interval": None, "arbitration_interval": None, "admissible_interval": None},
        "sample": {
            "received": len(frame),
            "observed_target": len(frame),
            "prepared": len(used_ids),
            "used": len(used_ids),
            "excluded": 1,
            "used_row_ids": used_ids,
            "excluded_row_ids": excluded_ids,
        },
        "validation": {"fundamentacao": {"grade": None}, "precisao": {"status": "not_computed"}, "statistical": {}, "documentary": {}, "issuance": {"status": "draft", "reasons": []}},
        "issues": [],
        "model": {"formula": formula, "coefficients": dict(fit.coefficients), "diagnostics": dict(fit.diagnostics)},
        "search": {"audit": {"selection_scope": "population_model"}},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"workflow_context": wf, "synthetic": SYNTHETIC_LABEL},
    }
    dumps_strict(snapshot)
    dumps_strict(report)
    dumps_strict(wf)
    example = {
        "label": SYNTHETIC_LABEL,
        "note": "Sanitized synthetic snapshot/context produced by P01. Not market evidence.",
        "snapshot": snapshot,
        "report_context": {
            k: report[k]
            for k in (
                "schema_version",
                "used_row_ids",
                "excluded_row_ids",
                "fitted_values",
                "residuals",
                "observed_values",
                "series_row_ids",
                "series_scale",
                "series_unit",
                "target_unit",
            )
        },
        "workflow_context": wf,
    }
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / "sanitized_snapshot_context.example.json"
    path.write_text(json.dumps(example, indent=2, allow_nan=False, ensure_ascii=False), encoding="utf-8")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "p01-a06-roundtrip.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["label"].startswith("SYNTHETIC")
    assert loaded["snapshot"]["model"]["formula"]
    assert loaded["report_context"]["series_row_ids"] == used_ids
    assert loaded["workflow_context"]["schema_version"] == "MP-PRO/1"
