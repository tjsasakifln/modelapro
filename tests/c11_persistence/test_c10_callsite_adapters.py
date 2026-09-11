"""Additive adapters that C10 already calls; frozen names stay unchanged."""

import pytest

from modules.job_store import JobStore, PathEscapeError, make_issue
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore


class TestC10CallsiteAdapters:
    def test_create_payload_and_explicit_idempotency_key(self, job_store):
        first = job_store.create(
            idempotency_key="subkey-" + "a" * 40,
            project_id="proj_c10",
            payload={
                "filename": "market.csv",
                "input_sha256": "1" * 64,
                "code_sha": "c" * 40,
                "request_spec": {"schema_version": "MP/1", "target_col": "preco"},
            },
        )
        assert first["created"] is True
        assert first["input_sha256"] == "1" * 64
        assert first["request_spec"]["target_col"] == "preco"
        second = job_store.create(
            idempotency_key="subkey-" + "a" * 40,
            project_id="proj_c10",
            payload={"filename": "market.csv"},
        )
        assert second["created"] is False
        assert second["job_id"] == first["job_id"]
        found = job_store.get_by_idempotency_key("subkey-" + "a" * 40)
        assert found["job_id"] == first["job_id"]

    def test_runner_zero_arg_construct_and_is_cancelled(self, job_store):
        runner = LocalTaskRunner()
        try:
            assert runner.store.root == job_store.root
            job = job_store.create()
            runner.cancel(job["job_id"])
            assert runner.is_cancelled(job["job_id"])
            assert job["job_id"] in runner.cancelled_ids() or job_store.get(job["job_id"])["state"] == "cancelled"
        finally:
            runner.shutdown(wait=True)

    def test_save_and_get_artifact_rejects_traversal(self, job_store):
        job = job_store.create()
        job_store.save_artifact(job["job_id"], "report.pdf", b"%PDF-fake")
        assert job_store.get_artifact(job["job_id"], "report.pdf") == b"%PDF-fake"
        assert job_store.get(job["job_id"])["artifact_states"]["report.pdf"]["state"] == "ready"
        with pytest.raises(PathEscapeError):
            job_store.save_artifact(job["job_id"], "../secret", b"nope")
        assert job_store.get_artifact(job["job_id"], "missing.bin") is None

    def test_same_state_patch_and_queued_to_failed(self, job_store):
        job = job_store.create()
        job_store.update_transition(job["job_id"], "queued", "running")
        patched = job_store.update_transition(
            job["job_id"],
            "running",
            "running",
            patch={"stage": "ingest", "calculation_state": "running"},
        )
        assert patched["state"] == "running"
        assert patched["stage"] == "ingest"
        done = job_store.update_transition(
            job["job_id"],
            "running",
            "succeeded",
            patch={"calculation_state": "succeeded", "result_available": True},
        )
        assert done["state"] == "succeeded"
        assert done["calculation_state"] == "succeeded"
        other = job_store.create()
        failed = job_store.update_transition(
            other["job_id"],
            "queued",
            "failed",
            patch={
                "calculation_state": "failed",
                "issues": [
                    make_issue(
                        code="JOB_CRASH",
                        message="peer failed before start",
                        severity="error",
                        origin="c10.worker",
                    )
                ],
            },
        )
        assert failed["state"] == "failed"

    def test_interrupt_stale_running_count(self, store_root):
        store = JobStore(store_root, recover_abandoned=False)
        job = store.create()
        store.update_transition(job["job_id"], "queued", "running")
        n = JobStore(store_root, recover_abandoned=False).interrupt_stale_running()
        assert n == 1
        assert store.list_by_state("interrupted")[0]["job_id"] == job["job_id"]

    def test_project_list_and_missing_revision_is_none(self, project_store):
        assert project_store.load_revision("missing_proj") is None
        assert project_store.list() == []
        rev = project_store.save_revision(
            "proj_list",
            {"schema_version": "MP/1", "encoder_state": {}, "model_state": {}},
        )
        items = project_store.list()
        assert items[0]["project_id"] == "proj_list"
        assert items[0]["latest_revision_id"] == rev
