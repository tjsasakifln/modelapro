"""P02-A04: projetos/revisões/lote contra stub HTTP das rotas reais, não mock do cliente."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from frontend.components.forms import JobClient, persist_client_to_session, restore_client_from_session
from frontend.components.workflow import present_batch_items, revision_recovery_plan
from tests.c09_frontend.fixtures import SNAPSHOT_CLASSIFIED
from tests.c09_frontend.test_job_client import _spec


class ProjectStub(BaseHTTPRequestHandler):
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

    def _bytes(self, code: int, payload: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = self._body()
        scenario = self.server.scenario
        if self.path == "/jobs":
            self.server.jobs_posted += 1
            self.server.last_job_body = body
            self._json(202, {"job_id": "job-1", "status_url": "/jobs/job-1"})
            return
        if self.path.endswith("/revisions"):
            payload = json.loads(body.decode("utf-8") or "{}")
            self.server.revisions.append(payload)
            rev_id = f"rev-{len(self.server.revisions)}"
            self._json(201, {"revision_id": rev_id, "project_id": self.path.split("/")[2]})
            return
        if self.path.endswith("/batch"):
            payload = json.loads(body.decode("utf-8") or "{}")
            self.server.batches.append(payload)
            self._json(202, {"job_id": "batch-1", "status_url": "/jobs/batch-1"})
            return
        self._json(404, {"error": self.path})

    def do_GET(self):
        scenario = self.server.scenario
        if self.path == "/projects":
            self._json(200, {"schema_version": "MP/1", "projects": scenario.get("projects") or []})
            return
        if self.path == "/projects/proj-1":
            self._json(200, {
                "schema_version": "MP/1",
                "project_id": "proj-1",
                "revision": scenario.get("revision") or {
                    "revision_id": "rev-1",
                    "job_id": "job-1",
                    "request_spec": {"schema_version": "MP/1", "target_col": "preco"},
                    "snapshot_ref": {"job_id": "job-1"},
                },
            })
            return
        if self.path == "/projects/proj-1/revisions":
            if scenario.get("revisions_missing"):
                self._json(404, {"error": "no list route"})
                return
            self._json(200, {"revisions": scenario.get("revision_list") or []})
            return
        if self.path == "/jobs/job-1":
            self._json(200, {
                "job_id": "job-1",
                "state": scenario.get("job_state", "succeeded"),
                "result_available": True,
                "artifact_states": scenario.get("artifact_states") or {
                    "report.pdf": {"state": "failed", "error": {"message": "PDF falhou"}},
                    "frozen_project.json": {"state": "ready"},
                },
            })
            return
        if self.path == "/jobs/job-1/result":
            self._json(200, scenario.get("snapshot") or SNAPSHOT_CLASSIFIED)
            return
        if self.path == "/jobs/batch-1":
            self._json(200, {"job_id": "batch-1", "state": "succeeded", "result_available": True})
            return
        if self.path == "/jobs/batch-1/result":
            self._json(200, {
                "batch": True,
                "items": [
                    {"subject_id": "ok", "status": "succeeded", "value": {"point": 10}},
                    {"subject_id": "no", "status": "unsupported"},
                    {"subject_id": "wait", "status": "pending"},
                ],
            })
            return
        if self.path.startswith("/jobs/job-1/artifacts/"):
            name = self.path.rsplit("/", 1)[-1]
            if name.endswith(".pdf"):
                self._json(404, {"error": "failed"})
                return
            self._bytes(200, b"FROZEN")
            return
        self._json(404, {"error": self.path})


def _start(scenario=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProjectStub)
    server.scenario = scenario or {}
    server.jobs_posted = 0
    server.revisions = []
    server.batches = []
    server.last_job_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_list_open_save_revision_recovers_canonical_snapshot_not_screen_text():
    frozen = dict(SNAPSHOT_CLASSIFIED)
    frozen["job_id"] = "job-1"
    server, url = _start({
        "projects": [{"project_id": "proj-1", "latest_revision_id": "rev-1"}],
        "snapshot": frozen,
        "revisions_missing": True,
    })
    try:
        client = JobClient(base_url=url, timeout=2)
        listed = client.list_projects()
        assert listed[0]["project_id"] == "proj-1"
        loaded = client.get_project("proj-1")
        plan = revision_recovery_plan(loaded)
        assert plan["from_screen_text"] is False
        assert plan["job_id"] == "job-1"
        recovered = client.recover(plan["job_id"])
        assert recovered["result_available"] is True
        assert client.last_snapshot["value"]["point"] == frozen["value"]["point"]
        saved = client.save_revision("proj-1", {"job_id": "job-1", "request_spec": _spec()})
        assert saved["revision_id"] == "rev-1"
        saved2 = client.save_revision("proj-1", {"job_id": "job-1", "request_spec": _spec()})
        assert saved2["revision_id"] != saved["revision_id"]
        assert len(server.revisions) == 2
        revs = client.list_revisions("proj-1")
        assert revs["list_route_available"] is False
        assert revs["integration"] == "INTEGRATION_PENDING"
        assert revs["handoff"]["producer"] == "P01"
        assert revs["handoff"]["path"] == "/projects/proj-1/revisions"
    finally:
        server.shutdown()


def test_session_reload_recovers_job_result_and_failed_pdf_keeps_calc():
    server, url = _start({})
    try:
        session = {}
        client = JobClient(base_url=url, timeout=2)
        client.submit_job(b"x", "a.csv", _spec())
        client.recover("job-1")
        persist_client_to_session(session, client)
        restored = restore_client_from_session(session, base_url=url)
        assert restored.job_id == "job-1"
        status = restored.recover()
        assert status["result_available"] is True
        assert restored.last_snapshot["value"]["point"] == SNAPSHOT_CLASSIFIED["value"]["point"]
        pdf = status["artifact_states"]["report.pdf"]
        assert pdf["state"] == "failed"
        calc = restored.get_artifact("frozen_project.json")
        assert calc == b"FROZEN"
    finally:
        server.shutdown()


def test_posted_job_body_contains_canonical_grade_and_chosen_method():
    server, url = _start({})
    try:
        client = JobClient(base_url=url, timeout=2)
        spec = _spec()
        spec["search_policy"]["minimum_fundamentacao_grade"] = 3
        spec["evaluation_policy"]["method"] = "holdout"
        client.submit_job(b"x", "a.csv", spec, subject={"area": "73,5"})
        assert server.jobs_posted == 1
        # multipart: look at raw body for the JSON field
        raw = server.last_job_body.decode("utf-8", errors="replace")
        assert "minimum_fundamentacao_grade" in raw
        assert "target_degree" not in raw
        assert "min_fundamentacao_grade" not in raw
        assert "holdout" in raw
        assert "73,5" in raw
    finally:
        server.shutdown()


def test_batch_payload_uses_real_route_and_item_states():
    server, url = _start({})
    try:
        client = JobClient(base_url=url, timeout=2)
        accepted = client.submit_batch("proj-1", {"subjects": [{"area": "73,5"}, {"bairro": "X"}]})
        assert accepted["job_id"] == "batch-1"
        assert server.batches[0]["subjects"]
        client.job_id = "batch-1"
        snap = client.get_result("batch-1")
        rows = present_batch_items(snap)
        statuses = {row["subject_id"]: row["ui_status"] for row in rows}
        assert statuses["ok"] == "valido"
        assert statuses["no"] == "nao_suportado"
        assert statuses["wait"] == "pendente"
    finally:
        server.shutdown()
