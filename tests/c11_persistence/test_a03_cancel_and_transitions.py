"""C11-A03: transitions, cancel, concurrency, artifacts, shutdown."""

import threading
import time

import pytest

from modules.job_store import (
    InvalidTransition,
    JobStore,
    StaleState,
    UnsafePayloadError,
)
from modules.local_task_runner import LocalTaskRunner, RunnerClosed

from tests.c11_persistence.conftest import sample_snapshot


class TestTransitionsAndCancel:
    def test_illegal_and_stale_transitions_are_rejected(self, job_store):
        job = job_store.create()
        job_id = job["job_id"]
        with pytest.raises(InvalidTransition):
            job_store.update_transition(job_id, "queued", "succeeded")
        job_store.update_transition(job_id, "queued", "running")
        with pytest.raises(StaleState):
            job_store.update_transition(job_id, "queued", "running")
        job_store.update_transition(job_id, "running", "succeeded")
        with pytest.raises(InvalidTransition):
            job_store.update_transition(job_id, "succeeded", "running")
        assert job_store.get(job_id)["state"] == "succeeded"

    def test_concurrent_cas_yields_one_terminal_state(self, job_store):
        job = job_store.create()
        job_store.update_transition(job["job_id"], "queued", "running")
        results = []
        errors = []

        def go(new_state):
            try:
                results.append(
                    job_store.update_transition(job["job_id"], "running", new_state)
                )
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=go, args=("succeeded",))
        t2 = threading.Thread(target=go, args=("cancelled",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        final = job_store.get(job["job_id"])
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], StaleState)
        assert final["state"] in {"succeeded", "cancelled"}
        assert final["state"] not in {"queued", "running"}

    def test_cancel_queued_never_starts_callable(self, job_store):
        runner = LocalTaskRunner(job_store, max_workers=1, recover_abandoned=False)
        try:
            blocker = threading.Event()
            first_started = threading.Event()
            second_started = []

            def occupy(cancel_requested=None):
                first_started.set()
                blocker.wait(timeout=5)
                first = occupy_job["job_id"]
                job_store.save_snapshot(first, sample_snapshot(first))
                return {"outcome": "succeeded"}

            def must_not_run(cancel_requested=None):
                second_started.append(True)
                raise AssertionError("queued-cancelled callable must not start")

            occupy_job = job_store.create()
            queued_job = job_store.create()
            runner.submit(occupy_job["job_id"], occupy)
            assert first_started.wait(timeout=2)
            runner.submit(queued_job["job_id"], must_not_run)
            cancelled = runner.cancel(queued_job["job_id"])
            assert cancelled["state"] == "cancelled"
            blocker.set()
            for _ in range(100):
                if job_store.get(occupy_job["job_id"])["state"] != "running":
                    break
                time.sleep(0.02)
            assert second_started == []
            assert job_store.get(queued_job["job_id"])["state"] == "cancelled"
            assert job_store.get(occupy_job["job_id"])["state"] == "succeeded"
        finally:
            runner.shutdown(wait=True)

    def test_cancel_running_reaches_callback(self, job_store):
        runner = LocalTaskRunner(job_store, max_workers=1, recover_abandoned=False)
        try:
            started = threading.Event()
            saw_cancel = threading.Event()
            job = job_store.create()

            def work(cancel_requested=None):
                started.set()
                deadline = time.time() + 5
                while not cancel_requested():
                    if time.time() > deadline:
                        raise TimeoutError("cancel_requested never became true")
                    time.sleep(0.01)
                saw_cancel.set()
                return {"outcome": "cancelled"}

            runner.submit(job["job_id"], work)
            assert started.wait(timeout=2)
            runner.cancel(job["job_id"])
            assert saw_cancel.wait(timeout=2)
            for _ in range(100):
                if job_store.get(job["job_id"])["state"] != "running":
                    break
                time.sleep(0.02)
            assert job_store.get(job["job_id"])["state"] == "cancelled"
            assert runner.live_job_ids() == set()
        finally:
            runner.shutdown(wait=True)

    def test_concurrent_cancel_and_complete_leave_one_legal_terminal(
        self, job_store
    ):
        runner = LocalTaskRunner(job_store, max_workers=1, recover_abandoned=False)
        try:
            started = threading.Event()
            barrier = threading.Barrier(2)
            job = job_store.create()

            def work(cancel_requested=None):
                started.set()
                barrier.wait(timeout=5)
                job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
                try:
                    job_store.update_transition(job["job_id"], "running", "succeeded")
                except (StaleState, InvalidTransition):
                    pass

            def do_cancel():
                started.wait(timeout=5)
                barrier.wait(timeout=5)
                runner.cancel(job["job_id"])

            cancel_thread = threading.Thread(target=do_cancel)
            runner.submit(job["job_id"], work)
            cancel_thread.start()
            cancel_thread.join(timeout=5)
            for _ in range(100):
                state = job_store.get(job["job_id"])["state"]
                if state not in {"queued", "running"} and not runner.live_job_ids():
                    break
                time.sleep(0.02)
            final = job_store.get(job["job_id"])
            assert final["state"] in {"succeeded", "cancelled"}
            assert runner.live_job_ids() == set()
            if final["state"] == "succeeded":
                assert job_store.get_snapshot(job["job_id"]) is not None
                assert final["calculation_finished"] is True
        finally:
            runner.shutdown(wait=True)

    def test_calculation_success_distinct_from_artifact_states(self, job_store):
        job = job_store.create()
        job_store.update_transition(
            job["job_id"],
            "queued",
            "running",
            patch={
                "artifact_states": {
                    "pdf": {"state": "pending", "error": None},
                    "evidence_bundle": {"state": "pending", "error": None},
                }
            },
        )
        job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        done = job_store.update_transition(
            job["job_id"],
            "running",
            "succeeded",
            patch={"progress": 1.0},
        )
        assert done["state"] == "succeeded"
        assert done["artifact_states"]["pdf"]["state"] == "pending"
        updated = job_store.patch_record(
            job["job_id"],
            {"artifact_states": {"pdf": {"state": "ready", "error": None}}},
        )
        assert updated["state"] == "succeeded"
        assert updated["artifact_states"]["pdf"]["state"] == "ready"
        assert updated["artifact_states"]["evidence_bundle"]["state"] == "pending"

    def test_progress_is_null_or_unit_interval_and_not_invented(self, job_store):
        job = job_store.create()
        assert job["progress"] is None
        job_store.update_transition(
            job["job_id"], "queued", "running", patch={"progress": 0.25}
        )
        with pytest.raises(UnsafePayloadError):
            job_store.patch_record(job["job_id"], {"progress": 1.5})
        with pytest.raises(UnsafePayloadError):
            job_store.patch_record(job["job_id"], {"progress": float("nan")})
        assert job_store.get(job["job_id"])["progress"] == 0.25

    def test_runner_bounds_concurrency_and_shuts_down_cleanly(self, job_store):
        runner = LocalTaskRunner(job_store, max_workers=1, recover_abandoned=False)
        try:
            current = []
            lock = threading.Lock()
            release = threading.Event()

            def make_work(jid):
                def work(cancel_requested=None):
                    with lock:
                        current.append(1)
                        peak = sum(current)
                    assert peak == 1
                    release.wait(timeout=2)
                    with lock:
                        current.pop()
                    job_store.save_snapshot(jid, sample_snapshot(jid))
                    return {"outcome": "succeeded"}

                return work

            jobs = [job_store.create() for _ in range(2)]
            for job in jobs:
                runner.submit(job["job_id"], make_work(job["job_id"]))
            time.sleep(0.1)
            with lock:
                assert sum(current) <= 1
            release.set()
            for job in jobs:
                for _ in range(100):
                    if job_store.get(job["job_id"])["state"] != "running":
                        break
                    time.sleep(0.02)
        finally:
            runner.shutdown(wait=True)
        with pytest.raises(RunnerClosed):
            runner.submit(job_store.create()["job_id"], lambda: None)
        assert runner.live_job_ids() == set()
