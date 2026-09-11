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
        if self.path.endswith("/revisions"):
            # BASE_SHA: this path is POST-only → GET is 405 unless a list is published.
            if scenario.get("revision_list") is not None:
                self._json(200, {"revisions": scenario["revision_list"]})
                return
            if scenario.get("revisions_missing"):
                self._json(404, {"error": "no list route"})
                return
            self._json(405, {"detail": "Method Not Allowed"})
            return
        if self.path.startswith("/jobs/") and self.path.endswith("/result"):
            job_id = self.path.split("/")[2]
            snapshots = scenario.get("snapshots") or {}
            if job_id in snapshots:
                self._json(200, snapshots[job_id])
                return
            if job_id == "job-1":
                self._json(200, scenario.get("snapshot") or SNAPSHOT_CLASSIFIED)
                return
            if job_id == "batch-1":
                self._json(200, {
                    "batch": True,
                    "items": [
                        {"subject_id": "ok", "status": "succeeded", "value": {"point": 10}},
                        {"subject_id": "no", "status": "unsupported"},
                        {"subject_id": "wait", "status": "pending"},
                    ],
                })
                return
            self._json(404, {"error": self.path})
            return
        if self.path.startswith("/jobs/") and "/artifacts/" not in self.path and self.path.count("/") == 2:
            job_id = self.path.rsplit("/", 1)[-1]
            self._json(200, {
                "job_id": job_id,
                "state": scenario.get("job_state", "succeeded"),
                "result_available": True,
                "artifact_states": scenario.get("artifact_states") or {
                    "report.pdf": {"state": "failed", "error": {"message": "PDF falhou"}},
                    "frozen_project.json": {"state": "ready"},
                },
            })
            return
        if self.path.startswith("/jobs/") and "/artifacts/" in self.path:
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


def test_get_revisions_405_is_handoff_not_error():
    from frontend.components.workflow import list_route_unavailable

    assert list_route_unavailable(405) is True
    assert list_route_unavailable(404) is True
    assert list_route_unavailable(501) is True
    assert list_route_unavailable(200) is False
    assert list_route_unavailable(500) is False

    frozen = dict(SNAPSHOT_CLASSIFIED)
    frozen["job_id"] = "job-1"
    server, url = _start({
        "projects": [{"project_id": "proj-1", "latest_revision_id": "rev-1"}],
        "snapshot": frozen,
    })
    try:
        client = JobClient(base_url=url, timeout=2)
        revs = client.list_revisions("proj-1")
        assert revs["list_route_available"] is False
        assert revs["http_status"] == 405
        assert revs["integration"] == "INTEGRATION_PENDING"
        assert revs["handoff"]["path"] == "/projects/proj-1/revisions"
        assert revs["revisions"][0]["revision_id"] == "rev-1"
        assert revs["revisions"][0]["job_id"] == "job-1"
    finally:
        server.shutdown()


def test_reopen_selected_revision_recovers_that_jobs_result_not_screen_text():
    old_snap = dict(SNAPSHOT_CLASSIFIED)
    old_snap["job_id"] = "job-old"
    old_snap["value"] = dict(old_snap["value"])
    old_snap["value"]["point"] = 111111.0
    new_snap = dict(SNAPSHOT_CLASSIFIED)
    new_snap["job_id"] = "job-1"
    server, url = _start({
        "revision_list": [
            {"revision_id": "rev-old", "job_id": "job-old", "snapshot_ref": {"job_id": "job-old"}},
            {"revision_id": "rev-1", "job_id": "job-1", "snapshot_ref": {"job_id": "job-1"}},
        ],
        "snapshots": {"job-old": old_snap, "job-1": new_snap},
        "revision": {
            "revision_id": "rev-1",
            "job_id": "job-1",
            "snapshot_ref": {"job_id": "job-1"},
        },
    })
    try:
        client = JobClient(base_url=url, timeout=2)
        listed = client.list_revisions("proj-1")
        assert listed["list_route_available"] is True
        outcome = client.reopen_revision("proj-1", "rev-old", listed)
        assert outcome["recovered"] is True
        assert outcome["from_screen_text"] is False
        assert outcome["via"] == "GET /jobs/job-old/result"
        assert outcome["job_id"] == "job-old"
        assert outcome["snapshot"]["value"]["point"] == old_snap["value"]["point"]
        assert client.last_snapshot["value"]["point"] == 111111.0
        latest = client.reopen_revision("proj-1", "rev-1", listed)
        assert latest["snapshot"]["value"]["point"] == new_snap["value"]["point"]
        assert latest["snapshot"]["value"]["point"] != old_snap["value"]["point"]
    finally:
        server.shutdown()


def test_reopen_latest_after_405_uses_get_project_and_job_result():
    frozen = dict(SNAPSHOT_CLASSIFIED)
    frozen["job_id"] = "job-1"
    server, url = _start({"snapshot": frozen})
    try:
        client = JobClient(base_url=url, timeout=2)
        revs = client.list_revisions("proj-1")
        assert revs["http_status"] == 405
        outcome = client.reopen_revision("proj-1", "rev-1", revs)
        assert outcome["recovered"] is True
        assert outcome["from_screen_text"] is False
        assert "GET /jobs/job-1/result" in outcome["via"]
        assert outcome["snapshot"]["value"]["point"] == frozen["value"]["point"]
    finally:
        server.shutdown()


def test_app_wires_revision_button_to_reopen_revision():
    from pathlib import Path

    app_src = (Path(__file__).resolve().parents[3] / "frontend" / "app.py").read_text(encoding="utf-8")
    layout_src = (Path(__file__).resolve().parents[3] / "frontend" / "components" / "layout.py").read_text(encoding="utf-8")
    assert 'pressed["open_revision_id"]' in layout_src
    assert "Reabrir esta revisão" in layout_src
    assert 'project_actions.get("open_revision_id")' in app_src
    assert "client.reopen_revision(" in app_src
