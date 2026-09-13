"""HTTP / compose helpers for P04. Drive the shipped FastAPI app and worker."""
from __future__ import annotations

import json
import time
from typing import Any, Mapping, Optional

from fastapi.testclient import TestClient

from backend.api import app
from backend.worker import compose_valuation_job, peer_kind, resolve_peers
from tests.fixtures.pro_workflow.corpus import pinned_identity_spec

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


def client() -> TestClient:
    return TestClient(app)


def production_peers():
    peers = resolve_peers()
    for name, fn in peers.items():
        kind, ref = peer_kind(fn)
        assert kind != "simulator", f"{name} resolved to labeled simulator {ref}"
    return peers


def post_job(
    test_client: TestClient,
    *,
    file_bytes: bytes,
    filename: str = "mercado.csv",
    spec: Optional[Mapping[str, Any]] = None,
    subject: Optional[Mapping[str, Any]] = None,
    content_type: str = "text/csv",
    project_id: Optional[str] = None,
):
    data = {"request_json": json.dumps(spec or pinned_identity_spec())}
    if subject is not None:
        data["subject_json"] = json.dumps(subject)
    if project_id is not None:
        data["project_id"] = project_id
    return test_client.post(
        "/jobs",
        files={"file": (filename, file_bytes, content_type)},
        data=data,
    )


def wait_job(test_client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = test_client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("state") in TERMINAL:
            return last
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not reach a terminal state: {last}")


def get_result(test_client: TestClient, job_id: str):
    return test_client.get(f"/jobs/{job_id}/result")


def run_job(
    test_client: TestClient,
    file_bytes: bytes,
    *,
    filename: str = "mercado.csv",
    spec: Optional[Mapping[str, Any]] = None,
    subject: Optional[Mapping[str, Any]] = None,
    content_type: str = "text/csv",
    project_id: Optional[str] = None,
    require_success: bool = True,
):
    t0 = time.perf_counter()
    resp = post_job(
        test_client,
        file_bytes=file_bytes,
        filename=filename,
        spec=spec,
        subject=subject,
        content_type=content_type,
        project_id=project_id,
    )
    if require_success:
        assert resp.status_code == 202, resp.text
    job_id = resp.json().get("job_id")
    status = wait_job(test_client, job_id) if job_id else {"state": "http", "http_status": resp.status_code}
    result = get_result(test_client, job_id) if job_id else resp
    elapsed = time.perf_counter() - t0
    snap = result.json() if result.status_code == 200 else None
    if require_success and snap is None:
        raise AssertionError(
            f"job {job_id} produced no snapshot: status={status} result={result.status_code} {result.text[:800]}"
        )
    return {
        "response": resp,
        "job_id": job_id,
        "status": status,
        "result": result,
        "snapshot": snap,
        "compute_time_s": elapsed,
        "idempotent_replay": bool((resp.json() or {}).get("idempotent_replay")),
    }


def compose_job(store, file_bytes: bytes, *, filename="mercado.csv", spec=None, subject=None, project_id=None):
    rec = store.create(payload={"filename": filename})
    ctx = compose_valuation_job(
        job_id=rec["job_id"],
        file_bytes=file_bytes,
        filename=filename,
        request_spec=spec or pinned_identity_spec(),
        subject_raw=subject,
        project_id=project_id,
        peers=production_peers(),
        job_store=store,
    )
    return rec["job_id"], ctx
