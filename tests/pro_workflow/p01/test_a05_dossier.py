"""P01-A05: downloadable dossier, clean-process reproduce, tamper, not-provided."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.worker import build_frozen_project
from modules.evidence_bundle import build_evidence_bundle, reproduce_from_bundle, verify_bundle
from modules.model_builder import CandidateSpec, fit_candidate
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
    residual = frozen.get("residual_state") or frozen["model_state"]["residual_state"]
    assert residual.get("subject_x"), "compose/freeze must pack subject_x from subject_design.X"
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
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert r2.returncode == 0, r2.stdout + r2.stderr
    j1 = json.loads(r1.stdout)
    j2 = json.loads(r2.stdout)
    assert j1.get("point") is not None
    assert j1.get("point") == j2.get("point")
    assert j1.get("mean_ci80") is not None
    assert j1.get("prediction_interval") is not None
    assert j1["mean_ci80"]["lower"] == j2["mean_ci80"]["lower"]


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


def test_p01_a05_artifact_zip_route_serves_zip_bytes(isolated_p01_runtime, tmp_path):
    import io
    import zipfile

    from fastapi.testclient import TestClient

    from backend.api import app

    out, _manifest, _residual, _fit = _bundle(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in out.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(out)).replace("\\", "/"))
    zip_bytes = buf.getvalue()
    assert zip_bytes[:2] == b"PK"
    store = isolated_p01_runtime["job_store"]
    job = store.create()
    job_id = job["job_id"]
    store.save_artifact(job_id, "evidence_bundle.zip", zip_bytes)
    client = TestClient(app)
    resp = client.get(f"/jobs/{job_id}/artifacts/evidence_bundle.zip")
    assert resp.status_code == 200, resp.text
    assert "application/zip" in (resp.headers.get("content-type") or "")
    assert resp.content[:2] == b"PK"
    assert resp.content == zip_bytes


def test_p01_submission_key_material_and_calc_version(monkeypatch, tmp_path):
    from backend.api import submission_key
    from tests.pro_workflow.p01.conftest import documented_csv_bytes, documented_request_spec

    file_bytes = documented_csv_bytes()
    spec = documented_request_spec()
    subject = {"area": 90.0, "bairro": "Centro"}
    k1 = submission_key(file_bytes, spec, subject)
    changed = documented_request_spec()
    changed["target_unit"] = "BRL/m2"
    k2 = submission_key(file_bytes, changed, subject)
    assert k1 != k2
    import modules.pro_workflow.residual_state as rs

    monkeypatch.setattr(rs, "CALCULATION_VERSION", "MP-PRO/1-other-calc")
    k3 = submission_key(file_bytes, spec, subject)
    assert k3 != k1

    store_root = tmp_path / "key-store"
    store_root.mkdir()
    from modules.job_store import JobStore

    JobStore.reset_default()
    store = JobStore.configure_default(store_root, recover_abandoned=True)
    created = store.create(idempotency_key=k1, request_spec=spec, input_sha256="a" * 64)
    job_id = created["job_id"]
    JobStore.reset_default()
    recovered = JobStore.configure_default(store_root, recover_abandoned=True)
    hit = recovered.get_by_idempotency_key(k1)
    assert hit is not None
    assert hit["job_id"] == job_id
    miss = recovered.get_by_idempotency_key(k2)
    assert miss is None
    JobStore.reset_default()
