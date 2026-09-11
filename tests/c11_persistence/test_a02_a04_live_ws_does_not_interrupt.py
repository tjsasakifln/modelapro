"""C11-A02 × C11-A04: a live running job must survive JobStore.default() and /ws.

The job_store fixture calls configure_default(), which hid a bug: JobStore()
did not become the process default, so /ws opened a recovering clone and
flipped running → interrupted.
"""

from fastapi.testclient import TestClient

from modules.job_store import JobStore
from modules.websocket_notifier import WebSocketNotifier


def test_jobstore_constructor_registers_default_without_configure(tmp_path, monkeypatch):
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
    root = tmp_path / "c11-live-default"
    root.mkdir()
    monkeypatch.setenv("MODELA_STORE_ROOT", str(root))

    store = JobStore()
    try:
        assert JobStore.default() is store
        job = store.create()
        store.update_transition(job["job_id"], "queued", "running")

        cloned = JobStore()
        via_default = JobStore.default()
        assert via_default is store
        assert store.get(job["job_id"])["state"] == "running"
        assert cloned.get(job["job_id"])["state"] == "running"
    finally:
        WebSocketNotifier().reset_connections()
        JobStore.reset_default()


def test_ws_connect_does_not_interrupt_live_running_job(tmp_path, monkeypatch):
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
    root = tmp_path / "c11-live-ws"
    root.mkdir()
    monkeypatch.setenv("MODELA_STORE_ROOT", str(root))

    store = JobStore()
    try:
        job = store.create()
        store.update_transition(job["job_id"], "queued", "running")
        assert store.get(job["job_id"])["state"] == "running"

        from backend.api import app

        client = TestClient(app)
        with client.websocket_connect(
            f"/ws?job_id={job['job_id']}&token={job['access_token']}"
        ) as ws:
            msg = ws.receive_json()
            assert msg["job_id"] == job["job_id"]
            assert msg.get("state") == "running"

        after_default = JobStore.default().get(job["job_id"])
        after_ctor = store.get(job["job_id"])
        assert after_default["state"] == "running"
        assert after_ctor["state"] == "running"
        assert after_ctor["state"] != "interrupted"
    finally:
        WebSocketNotifier().reset_connections()
        JobStore.reset_default()
