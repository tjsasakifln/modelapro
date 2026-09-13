"""C11-A04: /ws is scoped to job_id+token; dead sockets are pruned."""

import asyncio
import json

from fastapi.testclient import TestClient

from backend.api import app
from modules.websocket_notifier import WebSocketNotifier, light_progress_payload

from tests.c11_persistence.conftest import sample_snapshot


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def send_text(self, text):
        self.sent.append(text)

    async def close(self, code=None):
        self.closed = code


class DeadWebSocket(FakeWebSocket):
    async def send_text(self, text):
        raise RuntimeError("broken pipe")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestWebsocketIsolation:
    def test_two_jobs_never_see_each_others_payloads(self, job_store):
        notifier = WebSocketNotifier()
        notifier.reset_connections()
        job_a = job_store.create()
        job_b = job_store.create()
        ws_a = FakeWebSocket()
        ws_b = FakeWebSocket()
        assert _run(
            notifier.attach(
                ws_a, job_id=job_a["job_id"], token=job_a["access_token"], job_store=job_store
            )
        )
        assert _run(
            notifier.attach(
                ws_b, job_id=job_b["job_id"], token=job_b["access_token"], job_store=job_store
            )
        )
        _run(
            notifier.send_progress(
                job_a["job_id"],
                {
                    "state": "running",
                    "progress": 0.4,
                    "report_pdf_base64": "SHOULD_NOT_LEAK",
                    "snapshot": sample_snapshot(job_a["job_id"]),
                },
            )
        )
        _run(
            notifier.send_progress(
                job_b["job_id"],
                {"state": "running", "progress": 0.7, "model_metrics": {"r2": 0.9}},
            )
        )
        texts_a = [json.loads(t) for t in ws_a.sent]
        texts_b = [json.loads(t) for t in ws_b.sent]
        assert all(m.get("job_id") == job_a["job_id"] for m in texts_a)
        assert all(m.get("job_id") == job_b["job_id"] for m in texts_b)
        assert any(m.get("progress") == 0.4 for m in texts_a)
        assert any(m.get("progress") == 0.7 for m in texts_b)
        assert all("report_pdf_base64" not in m for m in texts_a + texts_b)
        assert all("snapshot" not in m for m in texts_a + texts_b)
        assert all("model_metrics" not in m for m in texts_a + texts_b)

    def test_dead_socket_is_removed_and_does_not_raise(self, job_store):
        notifier = WebSocketNotifier()
        notifier.reset_connections()
        job = job_store.create()
        dead = DeadWebSocket()
        live = FakeWebSocket()
        assert _run(
            notifier.attach(
                dead, job_id=job["job_id"], token=job["access_token"], job_store=job_store
            )
        )
        assert _run(
            notifier.attach(
                live, job_id=job["job_id"], token=job["access_token"], job_store=job_store
            )
        )
        _run(notifier.send_progress(job["job_id"], {"state": "running", "progress": 0.1}))
        assert dead not in notifier.connections_for(job["job_id"])
        assert live in notifier.connections_for(job["job_id"])
        notifier.disconnect(live)
        notifier.disconnect(live)
        assert notifier.connections_for(job["job_id"]) == []

    def test_unscoped_send_notification_does_not_broadcast(self, job_store):
        notifier = WebSocketNotifier()
        notifier.reset_connections()
        job = job_store.create()
        ws = FakeWebSocket()
        _run(
            notifier.attach(
                ws, job_id=job["job_id"], token=job["access_token"], job_store=job_store
            )
        )
        before = list(ws.sent)
        _run(
            notifier.send_notification(
                {
                    "status": "completed",
                    "progress": 1.0,
                    "report_pdf_base64": "AAA",
                    "model_metrics": {"r2": 0.9},
                }
            )
        )
        assert ws.sent == before
        _run(
            notifier.send_notification(
                {
                    "job_id": job["job_id"],
                    "status": "running",
                    "progress": 0.2,
                    "report_pdf_base64": "AAA",
                }
            )
        )
        last = json.loads(ws.sent[-1])
        assert last["job_id"] == job["job_id"]
        assert last["progress"] == 0.2
        assert "report_pdf_base64" not in last

    def test_real_ws_route_requires_local_token_and_isolates_jobs(self, job_store):
        notifier = WebSocketNotifier()
        notifier.reset_connections()
        job_a = job_store.create()
        job_b = job_store.create()
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws_a:
            ws_a.send_json({"job_id": job_a["job_id"], "token": job_a["access_token"]})
            msg_a = ws_a.receive_json()
            with client.websocket_connect("/ws") as ws_b:
                ws_b.send_json({"job_id": job_b["job_id"], "token": job_b["access_token"]})
                msg_b = ws_b.receive_json()
                assert msg_a["job_id"] == job_a["job_id"]
                assert msg_b["job_id"] == job_b["job_id"]
                assert msg_a["job_id"] != msg_b["job_id"]
                assert "report_pdf_base64" not in msg_a
                assert "snapshot" not in msg_b
                _run(
                    notifier.send_progress(
                        job_a["job_id"],
                        {
                            "state": "running",
                            "progress": 0.55,
                            "report_pdf_base64": "nope",
                        },
                    )
                )
                follow = ws_a.receive_json()
                assert follow["job_id"] == job_a["job_id"]
                assert follow["progress"] == 0.55
                assert "report_pdf_base64" not in follow
            assert notifier.connections_for(job_b["job_id"]) == []
        assert notifier.connections_for(job_a["job_id"]) == []

    def test_wrong_token_is_rejected(self, job_store):
        job = job_store.create()
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"job_id": job["job_id"], "token": "not-the-token"})
            msg = ws.receive_json()
            assert msg["status"] == "error"
        assert WebSocketNotifier().connections_for(job["job_id"]) == []

    def test_light_payload_drops_heavy_fields(self):
        light = light_progress_payload(
            {
                "job_id": "job_x",
                "state": "running",
                "progress": 0.3,
                "report_pdf_base64": "pdf",
                "charts": {"a": 1},
                "snapshot": {"value": 1},
            }
        )
        assert light["job_id"] == "job_x"
        assert light["progress"] == 0.3
        assert "report_pdf_base64" not in light
        assert "charts" not in light
        assert "snapshot" not in light
