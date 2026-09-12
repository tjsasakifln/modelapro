"""C01-A08: real FastAPI POST/GET gold vs inapto. No c10 doubles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.worker import peer_kind, resolve_peers
from tests.comercial.c01.conftest import (
    SCRATCH,
    dump_bytes,
    dump_json,
    gold_csv_bytes,
    gold_spec,
    gold_subject,
)

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


@pytest.fixture(autouse=True)
def _runtime(isolated_c01_runtime):
    return isolated_c01_runtime


def _client() -> TestClient:
    return TestClient(app)


def _post(client, *, file_bytes, spec, subject, filename="mercado.csv"):
    data = {"request_json": json.dumps(spec)}
    if subject is not None:
        data["subject_json"] = json.dumps(subject)
    return client.post("/jobs", files={"file": (filename, file_bytes, "text/csv")}, data=data)


def _wait(client, job_id: str, timeout: float = 180.0):
    import time

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("state") in TERMINAL:
            return last
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not finish: {last}")


def test_production_peers_are_not_c10_doubles():
    peers = resolve_peers()
    for name, fn in peers.items():
        kind, ref = peer_kind(fn)
        assert kind != "simulator", f"{name}={kind}:{ref}"
        assert "doubles" not in (ref or "")


def test_gold_job_twice_and_inapto_refusal(tmp_path):
    log_lines = []
    client = _client()
    spec = gold_spec()
    bodies = []
    for i in range(2):
        resp = _post(client, file_bytes=gold_csv_bytes(), spec=spec, subject=gold_subject())
        log_lines.append(f"gold_{i+1} POST {resp.status_code}")
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        status = _wait(client, job_id)
        result = client.get(f"/jobs/{job_id}/result")
        log_lines.append(f"gold_{i+1} GET {result.status_code} state={status.get('state')}")
        assert result.status_code == 200, result.text
        snap = result.json()
        dump_json(f"a08_gold_{i+1}.json", snap)
        bodies.append(snap)
        assert snap["schema_version"] == "MP/1"
        assert snap["value"]["point"] is not None
        assert float(snap["value"]["point"]) > 0
        wf = (snap.get("provenance") or {}).get("workflow_context") or {}
        assert wf.get("grade_requirement_status") in {"met", "not_requested", "pending"}
        qc = (snap.get("provenance") or {}).get("qualification_context") or {}
        assert qc.get("schema_version") == "MP-QUAL/1"
        frozen_resp = client.get(f"/jobs/{job_id}/artifacts/frozen_project.json")
        log_lines.append(f"gold_{i+1} frozen {frozen_resp.status_code}")
        assert frozen_resp.status_code == 200, frozen_resp.text
        frozen = json.loads(frozen_resp.content.decode("utf-8"))
        dump_json(f"a08_gold_{i+1}_frozen.json", frozen)
        assert frozen.get("schema_version") == "MP/1"
        assert isinstance(frozen.get("model_state"), dict) and frozen["model_state"]
        frozen_point = (frozen.get("value") or {}).get("point")
        assert frozen_point == snap["value"]["point"]
        bundle_resp = client.get(f"/jobs/{job_id}/artifacts/evidence_bundle.zip")
        log_lines.append(f"gold_{i+1} evidence_bundle {bundle_resp.status_code} bytes={len(bundle_resp.content)}")
        assert bundle_resp.status_code == 200, bundle_resp.text
        assert len(bundle_resp.content) > 4
        assert bundle_resp.content[:2] == b"PK"
        dump_bytes(f"a08_gold_{i+1}_evidence_bundle.zip", bundle_resp.content)
    assert bodies[0]["value"]["point"] == bodies[1]["value"]["point"]

    inapto_spec = gold_spec(candidate_cols=[])
    rejects = []
    for i in range(2):
        resp = _post(client, file_bytes=gold_csv_bytes(), spec=inapto_spec, subject=gold_subject())
        log_lines.append(f"reject_{i+1} POST {resp.status_code} body={resp.text[:500]}")
        assert resp.status_code == 400, resp.text
        assert resp.status_code != 500
        body = resp.json()
        dump_json(f"a08_reject_{i+1}.json", body)
        rejects.append(body)
        issues = body.get("issues") or (body.get("detail") or {}).get("issues") or []
        codes = {i.get("code") for i in issues if isinstance(i, dict)}
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        if not codes and isinstance(detail, dict):
            codes = {i.get("code") for i in (detail.get("issues") or []) if isinstance(i, dict)}
        assert "CANDIDATE_COLS_EMPTY" in codes
        assert "NO_WINNER" not in codes
    token_job = _post(client, file_bytes=gold_csv_bytes(), spec=spec, subject=gold_subject())
    assert token_job.status_code == 202
    job_id = token_job.json()["job_id"]
    _wait(client, job_id)
    bad_token = client.get(f"/jobs/{job_id}/result", params={"access_token": "not-the-token"})
    log_lines.append(f"bad_token GET {bad_token.status_code}")
    assert bad_token.status_code == 403
    codes = {i.get("code") for i in (bad_token.json().get("issues") or [])}
    assert "INVALID_ACCESS_TOKEN" in codes
    bad_fp = client.get(
        f"/jobs/{job_id}/result",
        params={"expected_fingerprint": "0" * 64},
    )
    log_lines.append(f"bad_fp GET {bad_fp.status_code}")
    assert bad_fp.status_code == 409
    codes = {i.get("code") for i in (bad_fp.json().get("issues") or [])}
    assert "FINGERPRINT_MISMATCH" in codes

    bad_profile = gold_spec()
    bad_profile["qualification_profile"] = {"id": ""}
    resp = _post(client, file_bytes=gold_csv_bytes(), spec=bad_profile, subject=gold_subject())
    log_lines.append(f"bad_profile POST {resp.status_code}")
    assert resp.status_code == 400

    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "a08_http.log").write_text("\n".join(log_lines), encoding="utf-8")
