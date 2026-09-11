"""C11-A01: jobs and snapshots are queryable without WebSocket."""

from modules.job_store import JobStore
from modules.websocket_notifier import WebSocketNotifier

from tests.c11_persistence.conftest import sample_snapshot


class TestQueryableWithoutWebSocket:
    def test_create_save_get_snapshot_without_ws(self, job_store):
        created = job_store.create(project_id="proj_local", stage="search")
        assert created["job_id"]
        assert created["state"] == "queued"
        assert created["progress"] is None
        assert created["result_available"] is False
        assert created["access_token"]
        assert job_store.get_snapshot(created["job_id"]) is None

        snapshot = sample_snapshot(created["job_id"], project_id="proj_local")
        job_store.save_snapshot(created["job_id"], snapshot)

        loaded = job_store.get(created["job_id"])
        assert loaded["job_id"] == created["job_id"]
        assert loaded["result_available"] is True
        assert loaded["calculation_finished"] is True
        got = job_store.get_snapshot(created["job_id"])
        assert got is not None
        assert got["job_id"] == created["job_id"]
        assert got["value"]["point"] == snapshot["value"]["point"]
        assert got["schema_version"] == "MP/1"
        assert WebSocketNotifier().connections_for(created["job_id"]) == []

    def test_terminal_job_without_any_ws_connection_stays_queryable(self, job_store):
        job = job_store.create()
        job_store.update_transition(job["job_id"], "queued", "running")
        job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        finished = job_store.update_transition(
            job["job_id"],
            "running",
            "succeeded",
            patch={"progress": 1.0, "stage": "calculated"},
        )
        assert finished["state"] == "succeeded"
        assert finished["result_available"] is True

        reopened = JobStore(job_store.root, recover_abandoned=False)
        status = reopened.get(job["job_id"])
        snap = reopened.get_snapshot(job["job_id"])
        assert status["state"] == "succeeded"
        assert snap["value"]["point"] == 1234.5
        assert snap["job_id"] == job["job_id"]

    def test_submit_get_cancel_do_not_require_socket(self, job_store):
        from modules.local_task_runner import LocalTaskRunner

        job = job_store.create()
        runner = LocalTaskRunner(job_store, max_workers=1, recover_abandoned=False)
        try:
            seen = []

            def work(cancel_requested=None):
                seen.append(cancel_requested() if cancel_requested else False)
                job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
                return {"outcome": "succeeded"}

            runner.submit(job["job_id"], work)
            for _ in range(100):
                current = job_store.get(job["job_id"])
                if current["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                import time

                time.sleep(0.02)
            current = job_store.get(job["job_id"])
            assert current["state"] == "succeeded"
            assert job_store.get_snapshot(job["job_id"])["job_id"] == job["job_id"]
            after = runner.cancel(job["job_id"])
            assert after["state"] == "succeeded"
            assert any(i["code"] == "cancel_after_completion" for i in after["issues"])
            assert seen == [False]
        finally:
            runner.shutdown(wait=True)

    def test_snapshot_is_job_record_not_second_canonical_result_file(self, job_store):
        job = job_store.create()
        job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        snap_path = job_store.root / "jobs" / job["job_id"] / "snapshot.json"
        assert snap_path.is_file()
        stray = list(job_store.root.rglob("result.json"))
        assert stray == []
