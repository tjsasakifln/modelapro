"""C10-A05: traversal, invalid payload, degree, oversized file, peers vs simulators."""

import ast
import json
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from backend.api import app, reset_runtime
from backend.worker import MP1_PEERS, peer_kind, resolve_peers
from tests.c10_pipeline.doubles import SIMULATOR_MARK, install_labeled_runtime, make_peers, CallLog
from tests.c10_pipeline.fixtures import complete_request_spec, market_csv_bytes


def _issues(resp):
    body = resp.json()
    if "issues" in body:
        return body["issues"]
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("issues") or []
    return []


def test_artifact_path_traversal_rejected():
    from fastapi import HTTPException

    from backend.api import _safe_artifact_name

    install_labeled_runtime()
    client = TestClient(app)
    created = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("T"), "text/csv")},
        data={"request_json": json.dumps(complete_request_spec())},
    )
    job_id = created.json()["job_id"]
    for name in ("not-allowed.bin", ".hidden"):
        resp = client.get(f"/jobs/{job_id}/artifacts/{name}")
        assert resp.status_code == 400, (name, resp.status_code, resp.text)
    for name in ("../etc/passwd", "..\\secret", "/etc/passwd", ".."):
        try:
            _safe_artifact_name(name)
            raise AssertionError(f"{name!r} should be rejected")
        except HTTPException as exc:
            assert exc.status_code == 400
    for name in ("../etc/passwd", "..\\secret", "/etc/passwd"):
        encoded = client.get(f"/jobs/{job_id}/artifacts/{quote(name, safe='')}")
        assert encoded.status_code in (400, 404), (name, encoded.status_code, encoded.text)
    allowed = client.get(f"/jobs/{job_id}/artifacts/report.pdf")
    assert allowed.status_code == 200


def test_oversized_file_is_413(monkeypatch):
    monkeypatch.setenv("MP_MAX_UPLOAD_BYTES", "64")
    install_labeled_runtime()
    client = TestClient(app)
    big = market_csv_bytes("BIG") + b"x" * 200
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", big, "text/csv")},
        data={"request_json": json.dumps(complete_request_spec())},
    )
    assert resp.status_code == 413
    assert any(i["code"] == "FILE_TOO_LARGE" for i in _issues(resp))


def test_empty_file_is_400():
    install_labeled_runtime()
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", b"", "text/csv")},
        data={"request_json": json.dumps(complete_request_spec())},
    )
    assert resp.status_code == 400
    assert any(i["code"] == "EMPTY_FILE" for i in _issues(resp))


def test_impossible_result_is_not_200_empty_json():
    install_labeled_runtime(auto_run=False)
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("Z"), "text/csv")},
        data={"request_json": json.dumps(complete_request_spec())},
    )
    job_id = resp.json()["job_id"]
    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 409
    body = result.json()
    assert body != {}
    assert body.get("result_available") is False


def test_labeled_simulators_are_distinct_from_real_imports():
    log = CallLog()
    sim = make_peers(log)["ingest_market"]
    kind, ref = peer_kind(sim)
    assert kind == "simulator"
    assert SIMULATOR_MARK in ref
    real_peers = resolve_peers()
    for name, fn in real_peers.items():
        kind, ref = peer_kind(fn)
        if fn is None:
            assert kind == "missing"
        else:
            assert kind == "real"
            assert SIMULATOR_MARK not in ref


def test_production_modules_do_not_ship_unlabeled_standins():
    root = Path(__file__).resolve().parents[2]
    for rel in ("backend/api.py", "backend/worker.py", "modules/result_contract.py", "modules/results.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in {
                "JobStore",
                "ProjectStore",
                "LocalTaskRunner",
            }:
                raise AssertionError(f"{rel} defines {node.name} — C11 ownership")
            if isinstance(node, ast.FunctionDef) and node.name in {
                "ingest_market",
                "fit_dataset",
                "search_models",
                "evaluate_batch",
                "render_report",
            }:
                raise AssertionError(f"{rel} defines peer body {node.name}")


def test_frozen_peer_import_paths_match_contract():
    assert MP1_PEERS["ingest_market"] == ("modules.data_loader", "ingest_market")
    assert MP1_PEERS["fit_dataset"] == ("modules.preprocessing", "fit_dataset")
    assert MP1_PEERS["search_models"] == ("modules.optimal_combination", "search_models")
    assert MP1_PEERS["assess_normative"] == ("modules.nbr14653_validation", "assess_normative")
    assert MP1_PEERS["evaluate_fitted"] == ("modules.model_builder", "evaluate_fitted")
    assert MP1_PEERS["recommend_next_actions"] == ("modules.decision_support", "recommend_next_actions")
    assert MP1_PEERS["render_report"] == ("modules.results_generator", "render_report")
    assert MP1_PEERS["build_evidence_bundle"] == ("modules.evidence_bundle", "build_evidence_bundle")
    assert MP1_PEERS["evaluate_batch"] == ("modules.valuation_batch", "evaluate_batch")


def test_missing_c11_fails_closed_not_unlabeled_fake(monkeypatch):
    reset_runtime()
    monkeypatch.setattr(
        "backend.api._import_c11",
        lambda: (
            {"JobStore": None, "ProjectStore": None, "LocalTaskRunner": None},
            [("modules.job_store.JobStore", "forced-absent")],
        ),
    )
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("N"), "text/csv")},
        data={"request_json": json.dumps(complete_request_spec())},
    )
    assert resp.status_code == 503
    body = resp.json()
    detail = body.get("detail", body)
    issues = detail.get("issues") if isinstance(detail, dict) else body.get("issues")
    assert issues
    assert any(i["code"] == "PEER_UNAVAILABLE" for i in issues)
    assert (detail.get("integration") if isinstance(detail, dict) else body.get("integration")) == "INTEGRATION_PENDING"
