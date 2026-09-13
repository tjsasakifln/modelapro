"""C09-A03/A04: cliente HTTP contra stub de rede das rotas C11 — não contra um mock do cliente."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from frontend.components.forms import (
    ApiConnectionError,
    ApiResponseError,
    DuplicateExecutionError,
    JobClient,
    build_request_spec,
    may_start_execution,
    persist_client_to_session,
    restore_client_from_session,
)
from frontend.components.layout import present_artifacts, present_job_status
from tests.c09_frontend.fixtures import SNAPSHOT_CLASSIFIED


class C11Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json(self, code: int, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, code: int, payload: bytes, content_type: str = "application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        self._body()
        scenario = self.server.scenario
        if self.path == "/preview":
            if scenario.get("preview_closed"):
                self.close_connection = True
                self.connection.close()
                return
            self._json(200, scenario.get("preview") or {"column_map": {}})
            return
        if self.path == "/jobs":
            self.server.jobs_posted += 1
            if scenario.get("jobs_closed"):
                self.close_connection = True
                self.connection.close()
                return
            self._json(202, {"job_id": "job-1", "status_url": "/jobs/job-1"})
            return
        if self.path == "/jobs/job-1/cancel":
            self.server.cancelled += 1
            scenario["job_state"] = "cancelled"
            scenario["result_available"] = False
            self._json(200, {"job_id": "job-1", "state": "cancelled", "result_available": False})
            return
        if self.path.endswith("/revisions"):
            self._json(200, {"revision_id": "rev-1"})
            return
        if self.path.endswith("/batch"):
            self._json(202, {"job_id": "batch-1", "status_url": "/jobs/batch-1"})
            return
        self._json(404, {"error": self.path})

    def do_GET(self):
        scenario = self.server.scenario
        if scenario.get("close_get"):
            self.close_connection = True
            self.connection.close()
            return
        if scenario.get("slow_get"):
            time.sleep(float(scenario.get("slow_seconds", 1.5)))
        if self.path == "/jobs/job-1":
            self._json(
                200,
                {
                    "schema_version": "MP/1",
                    "job_id": "job-1",
                    "project_id": None,
                    "state": scenario.get("job_state", "succeeded"),
                    "stage": scenario.get("stage", "done"),
                    "progress": scenario.get("progress", 1.0),
                    "result_available": scenario.get("result_available", True),
                    "artifact_states": scenario.get("artifact_states") or {},
                    "issues": scenario.get("job_issues") or [],
                },
            )
            return
        if self.path == "/jobs/job-1/result":
            if not scenario.get("result_available", True):
                self._json(409, {"state": scenario.get("job_state", "running")})
                return
            self._json(200, scenario.get("snapshot") or SNAPSHOT_CLASSIFIED)
            return
        if self.path.startswith("/jobs/job-1/artifacts/"):
            name = self.path.rsplit("/", 1)[-1]
            states = scenario.get("artifact_states") or {}
            meta = states.get(name) or {}
            if meta.get("state") == "failed":
                self._json(404, {"error": "failed"})
                return
            self._bytes(200, b"CALC-BYTES")
            return
        if self.path == "/projects":
            self._json(200, [])
            return
        self._json(404, {"error": self.path})


def _start(scenario=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), C11Stub)
    server.scenario = scenario or {}
    server.jobs_posted = 0
    server.cancelled = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _spec():
    return build_request_spec(
        target_col="preco",
        candidate_cols=["bairro", "area"],
        roles={"preco": "target", "bairro": "predictor", "area": "predictor"},
        target_unit="BRL",
        reference_date="2024-01-15",
    )


def test_post_jobs_keeps_job_id_without_websocket():
    server, url = _start({"job_state": "succeeded", "result_available": True})
    try:
        client = JobClient(base_url=url, timeout=2)
        accepted = client.submit_job(b"col\n1", "a.csv", _spec())
        assert accepted["job_id"] == "job-1"
        assert client.job_id == "job-1"
        status = client.recover()
        assert status["job_id"] == "job-1"
        assert status["result_available"] is True
        snap = client.get_result()
        assert snap["value"]["point"] == 250000.5
        assert server.jobs_posted == 1
    finally:
        server.shutdown()


def test_closed_get_after_accept_keeps_job_id_and_later_recover_works():
    scenario = {"job_state": "succeeded", "result_available": True, "close_get": True}
    server, url = _start(scenario)
    try:
        client = JobClient(base_url=url, timeout=2)
        client.submit_job(b"col\n1", "a.csv", _spec())
        assert client.job_id == "job-1"
        with pytest.raises(ApiConnectionError):
            client.get_status()
        assert client.job_id == "job-1"
        scenario["close_get"] = False
        status = client.recover(client.job_id)
        assert status["result_available"] is True
        assert client.last_snapshot["value"]["point"] == 250000.5
    finally:
        server.shutdown()


def test_timeout_surfaces_and_preserves_job_id():
    scenario = {"slow_get": True, "slow_seconds": 1.2, "job_state": "running", "result_available": False}
    server, url = _start(scenario)
    try:
        client = JobClient(base_url=url, timeout=0.2)
        client.job_id = "job-1"
        with pytest.raises(ApiConnectionError):
            client.get_status()
        assert client.job_id == "job-1"
    finally:
        server.shutdown()


def test_preview_connection_error_does_not_invent_payload():
    client = JobClient(base_url="http://127.0.0.1:1", timeout=0.3)
    with pytest.raises(ApiConnectionError):
        client.preview(b"x", "a.csv", _spec())
    assert client.last_snapshot is None


def test_rerun_does_not_post_second_job_while_running():
    scenario = {"job_state": "running", "result_available": False}
    server, url = _start(scenario)
    try:
        client = JobClient(base_url=url, timeout=2)
        client.submit_job(b"col\n1", "a.csv", _spec())
        client.last_status = {"job_id": "job-1", "state": "running"}
        assert may_start_execution(client.last_status) is False
        with pytest.raises(DuplicateExecutionError):
            client.submit_job(b"col\n1", "a.csv", _spec())
        assert server.jobs_posted == 1
        assert client.job_id == "job-1"
    finally:
        server.shutdown()


def test_cancel_save_and_artifacts_reflect_real_state():
    scenario = {
        "job_state": "running",
        "result_available": False,
        "artifact_states": {
            "laudo.pdf": {"state": "failed", "error": {"message": "PDF falhou"}},
            "calculo.json": {"state": "ready", "error": None},
        },
    }
    server, url = _start(scenario)
    try:
        client = JobClient(base_url=url, timeout=2)
        client.submit_job(b"col\n1", "a.csv", _spec())
        status = client.get_status()
        job_view = present_job_status(status)
        assert job_view["can_cancel"] is True
        assert job_view["can_rerun"] is False
        art = present_artifacts(status["artifact_states"])
        assert art["pdf_failed"] is True
        assert art["offer_calculation_download"] is True
        assert any(item["name"] == "calculo.json" and item["can_download"] for item in art["items"])
        cancelled = client.cancel()
        assert cancelled["state"] == "cancelled"
        assert server.cancelled == 1
        scenario["job_state"] = "succeeded"
        scenario["result_available"] = True
        done = client.get_status()
        done_view = present_job_status(done)
        assert done_view["can_save"] is True
        assert done_view["can_rerun"] is True
        payload = client.get_artifact("calculo.json")
        assert payload == b"CALC-BYTES"
        saved = client.save_revision("proj-1", {"job_id": "job-1"})
        assert saved["revision_id"] == "rev-1"
    finally:
        server.shutdown()


def test_session_restore_recovers_job_id_after_rerun():
    session = {}
    client = JobClient(base_url="http://example.invalid", timeout=1)
    client.job_id = "job-1"
    client.last_status = {"job_id": "job-1", "state": "running"}
    persist_client_to_session(session, client)
    restored = restore_client_from_session(session, base_url="http://example.invalid")
    assert restored.job_id == "job-1"
    assert restored.last_status["state"] == "running"
    assert may_start_execution(restored.last_status) is False


def _recovery_client(handler):
    http = httpx.Client(
        base_url="http://localhost:8000",
        transport=httpx.MockTransport(handler),
    )
    return JobClient(base_url="http://localhost:8000", timeout=1, client=http)


def test_recovering_another_pending_job_clears_state_from_previous_job():
    def handler(request):
        assert request.url.path == "/jobs/job-new"
        return httpx.Response(
            200,
            json={"job_id": "job-new", "state": "running", "result_available": False},
        )

    client = _recovery_client(handler)
    client.job_id = "job-old"
    client.access_token = "old-token"
    client.status_url = "/jobs/job-old"
    client.last_status = {"job_id": "job-old", "state": "succeeded"}
    client.last_snapshot = {"job_id": "job-old", "value": {"point": 1}}
    client.last_request_spec = {"applicant": "OLD SCREEN STATE"}
    client.last_submit_fingerprint = "old-fingerprint"

    status = client.recover("job-new")

    assert status == {"job_id": "job-new", "state": "running", "result_available": False}
    assert client.job_id == "job-new"
    assert client.status_url == "/jobs/job-new"
    assert client.access_token is None
    assert client.last_snapshot is None
    assert client.last_request_spec is None
    assert client.last_submit_fingerprint is None


def test_recover_result_error_is_blocking_and_keeps_new_job_without_old_state():
    def handler(request):
        if request.url.path == "/jobs/job-new":
            return httpx.Response(
                200,
                json={"job_id": "job-new", "state": "succeeded", "result_available": True},
            )
        if request.url.path == "/jobs/job-new/result":
            return httpx.Response(503, json={"code": "RESULT_READ_FAILED"})
        raise AssertionError(request.url.path)

    client = _recovery_client(handler)
    client.job_id = "job-old"
    client.last_status = {"job_id": "job-old", "state": "succeeded"}
    client.last_snapshot = {"job_id": "job-old", "value": {"point": 1}}
    client.last_request_spec = {"applicant": "OLD SCREEN STATE"}

    with pytest.raises(ApiResponseError, match="Resultado ainda não disponível"):
        client.recover("job-new")

    assert client.job_id == "job-new"
    assert client.last_status["job_id"] == "job-new"
    assert client.last_snapshot is None
    assert client.last_request_spec is None


def test_recover_restores_request_spec_only_from_canonical_frozen_project():
    canonical_spec = {
        "schema_version": "MP/1",
        "applicant": "CANONICAL FROZEN PROJECT",
        "target_col": "preco",
    }

    def handler(request):
        if request.url.path == "/jobs/job-new":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-new",
                    "state": "succeeded",
                    "result_available": True,
                    "artifact_states": {"frozen_project.json": {"state": "ready"}},
                },
            )
        if request.url.path == "/jobs/job-new/result":
            return httpx.Response(200, json={"job_id": "job-new", "value": {"point": 2}})
        if request.url.path == "/jobs/job-new/artifacts/frozen_project.json":
            return httpx.Response(
                200,
                content=json.dumps({"request_spec": canonical_spec}).encode("utf-8"),
            )
        raise AssertionError(request.url.path)

    client = _recovery_client(handler)
    client.job_id = "job-old"
    client.last_request_spec = {"applicant": "CURRENT FORM MUST NOT WIN"}

    client.recover("job-new")

    assert client.last_snapshot["value"]["point"] == 2
    assert client.last_request_spec == canonical_spec
