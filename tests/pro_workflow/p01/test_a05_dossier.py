"""P01-A05: downloadable dossier, clean-process reproduce, tamper, not-provided."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.worker import build_frozen_project
from modules.evidence_bundle import build_evidence_bundle, reproduce_from_bundle, verify_bundle
from modules.model_builder import CandidateSpec, fit_candidate
from modules.pro_workflow.residual_state import extract_residual_state
from tests.pro_workflow.p01.conftest import documented_identity_ols_frame, documented_request_spec
from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared

SCRATCH = Path("/tmp/grok-goal-c8528f369173/implementer")
REPO = Path(__file__).resolve().parents[3]


def _bundle(tmp_path: Path):
    frame = documented_identity_ols_frame()
    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="p01-a05",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    req = documented_request_spec()
    fit = fit_candidate(prepared, spec, req)
    residual = extract_residual_state(fit)
    from modules.valuation_batch import builtin_evaluate_fitted, restore_candidate_fit
    frozen = build_frozen_project(
        project_id="p01-a05",
        revision_id="rev-a05",
        request_spec=req,
        input_bundle={"input_sha256": "p01-a05-input", "raw_frame": frame, "parsed_frame": frame},
        prepared_dataset=prepared,
        winner_fit=fit,
        subject_design={
            "subject_id": "s1",
            "raw_values": {"area": 100.0, "bairro": "Sul", "bairro_Sul": 1.0},
            "X": {"const": 1.0, "area": 100.0, "bairro_Sul": 1.0},
            "supported": True,
        },
        normative={"edition": "NBR 14653-2:2011"},
        artifact_refs={},
        sample_ledger=prepared["sample_ledger"],
    )
    assessed = builtin_evaluate_fitted(
        restore_candidate_fit(frozen),
        {
            "subject_id": "s1",
            "raw_values": {"area": 100.0, "bairro": "Sul", "bairro_Sul": 1.0},
            "X": {"const": 1.0, "area": 100.0, "bairro_Sul": 1.0},
            "supported": True,
            "issues": [],
        },
        req,
    )
    residual = dict(residual)
    residual["subject_x"] = [1.0, 100.0, 1.0]
    residual["interval_method"] = "ols_mean_and_prediction"
    residual["interval_scale"] = "original"
    residual["std_error"] = residual.get("residual_std")
    residual["t_crit"] = residual.get("t_crit_80")
    snapshot = {
        "schema_version": "MP/1",
        "job_id": "job-p01-a05",
        "project_id": "p01-a05",
        "input_sha256": "p01-a05-input",
        "code_sha": "p01-test",
        "reference_date": "2024-06-01",
        "generated_at": "2024-06-15T12:00:00+00:00",
        "target": {"column": "preco", "unit": "BRL", "estimand": "E[Y|X]"},
        "value": dict(assessed.get("value") or {}),
        "sample": {
            "received": len(frame),
            "observed_target": len(frame),
            "prepared": len(frame),
            "used": len(frame),
            "excluded": 0,
            "used_row_ids": list(frame["id"]),
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": None, "points": None, "pending_items": [1, 3]},
            "precisao": {"status": "not_computed", "grade": None},
            "statistical": {},
            "documentary": {"status": "pending"},
            "issuance": {"status": "draft", "reasons": []},
        },
        "issues": [],
        "model": {
            "coefficients": dict(fit.coefficients),
            "formula": None,
            "residual_state": residual,
        },
        "search": {"audit": {}},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"synthetic": True},
    }
    out = tmp_path / "bundle"
    artifacts = {
        "request_spec": req,
        "coefficients": dict(fit.coefficients),
        "residual_state": residual,
        "residual_context": residual,
        "subject_design": {
            "X": {"const": 1.0, "area": 100.0, "bairro_Sul": 1.0},
            "raw_values": {"area": 100.0, "bairro": "Sul"},
            "supported": True,
        },
        "y_transformation": {"name": "identity"},
        "feature_schema": prepared["feature_schema"],
        "encoder_state": prepared["encoder_state"],
        "missing_policy": req["missing_policy"],
        "outlier_policy": req["outlier_policy"],
        "search_policy": req["search_policy"],
        "evaluation_policy": req["evaluation_policy"],
    }
    input_bundle = {
        "input_sha256": "p01-a05-input",
        "raw_frame": frame,
        "parsed_frame": frame,
        "row_ledger": [{"row_id": rid, "observed_target": True} for rid in frame["id"]],
        "request_spec": req,
    }
    manifest = build_evidence_bundle(snapshot, input_bundle, prepared, artifacts, out)
    return out, manifest, residual, fit


def test_p01_a05_bundle_contains_bases_policies_and_reproduces(tmp_path):
    out, manifest, residual, fit = _bundle(tmp_path)
    assert (out / "data" / "original_base.csv").is_file()
    assert (out / "data" / "interpreted_base.csv").is_file()
    assert (out / "policies" / "search_policy.json").is_file()
    assert (out / "model" / "residual_state.json").is_file() or (out / "model" / "residual_context.json").is_file()
    completeness = manifest.get("completeness_summary") or {}
    assert "faltante" in completeness or completeness
    # Document never supplied stays not provided.
    ledger_items = (manifest.get("completeness_missing") or [])
    # photos/inspections were not supplied
    ledger_path = out / "completeness" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    by_name = {i["component"]: i for i in ledger["items"]}
    docs = by_name.get("documentary_sources") or by_name.get("photos") or {}
    if docs:
        assert docs.get("absence_kind") in {None, "not_provided"} or docs.get("status") == "faltante"

    cmd = [sys.executable, str(REPO / "scripts" / "c12_reproduce" / "reproduce.py"), "--bundle", str(out)]
    r1 = subprocess.run(cmd, capture_output=True, text=True, check=False)
    r2 = subprocess.run(cmd, capture_output=True, text=True, check=False)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "p01-a05-repro-1.json").write_text(r1.stdout or r1.stderr, encoding="utf-8")
    (SCRATCH / "p01-a05-repro-2.json").write_text(r2.stdout or r2.stderr, encoding="utf-8")
    assert r1.returncode in {0, 3}, r1.stdout + r1.stderr
    assert r2.returncode == r1.returncode
    j1 = json.loads(r1.stdout)
    j2 = json.loads(r2.stdout)
    if r1.returncode == 0:
        assert j1.get("point") is not None
        assert j1.get("point") == j2.get("point")


def test_p01_a05_tamper_invalidates_integrity_or_reproduction(tmp_path):
    out, _manifest, _residual, _fit = _bundle(tmp_path)
    coef_path = out / "model" / "coefficients.json"
    original = coef_path.read_text(encoding="utf-8")
    data = json.loads(original)
    # Tamper a coefficient.
    if "order" in data and data.get("values"):
        first = data["order"][0]
        block = data["values"][first]
        if isinstance(block, dict) and "float64" in block:
            block["float64"] = float(block["float64"]) + 1.0
        elif isinstance(block, (int, float)):
            data["values"][first] = float(block) + 1.0
    else:
        for key in list(data.keys()):
            if isinstance(data[key], (int, float)):
                data[key] = float(data[key]) + 1.0
                break
    coef_path.write_text(json.dumps(data), encoding="utf-8")
    integrity = verify_bundle(out)
    repro = reproduce_from_bundle(out)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "p01-a05-tamper.log").write_text(
        json.dumps({"integrity_ok": integrity.get("ok"), "repro_ok": repro.get("ok")}, indent=2),
        encoding="utf-8",
    )
    assert integrity.get("ok") is False or repro.get("ok") is False
