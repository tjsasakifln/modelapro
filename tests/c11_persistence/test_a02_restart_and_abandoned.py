"""C11-A02: process restart preserves revisions and interrupts abandoned running."""

from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore

from tests.c11_persistence.conftest import sample_snapshot


class TestRestartAndAbandoned:
    def test_reopen_reloads_immutable_revisions(self, job_store, project_store):
        payload = {
            "schema_version": "MP/1",
            "encoder_state": {"imputer": {"area": {"strategy": "median", "value": 80.0}}},
            "model_state": {"spec": {"features": ["area"], "intercept": True}},
            "model_scope": "population_model",
            "artifact_refs": {"coefficients": "artifacts/coefficients.json"},
        }
        revision_id = project_store.save_revision("proj_keep", payload)
        first = project_store.load_revision("proj_keep")
        assert first["revision_id"] == revision_id
        assert first["encoder_state"]["imputer"]["area"]["value"] == 80.0

        reopened_projects = ProjectStore(job_store.root)
        latest = reopened_projects.load_revision("proj_keep")
        by_id = reopened_projects.load_revision("proj_keep", revision_id)
        assert latest["revision_id"] == revision_id
        assert by_id["model_state"]["spec"]["features"] == ["area"]
        assert latest["schema_version"] == "MP/1"

    def test_abandoned_running_becomes_interrupted_without_fabricating_success(
        self, store_root
    ):
        store = JobStore(store_root, recover_abandoned=False)
        job = store.create()
        store.update_transition(job["job_id"], "queued", "running")
        assert store.get_snapshot(job["job_id"]) is None

        reopened = JobStore(store_root, recover_abandoned=True)
        recovered = reopened.get(job["job_id"])
        assert recovered["state"] == "interrupted"
        assert recovered["state"] != "succeeded"
        assert reopened.get_snapshot(job["job_id"]) is None
        assert any(i["code"] == "abandoned_running" for i in recovered["issues"])

    def test_abandoned_running_keeps_snapshot_but_does_not_mark_succeeded(
        self, store_root
    ):
        store = JobStore(store_root, recover_abandoned=False)
        job = store.create()
        store.update_transition(job["job_id"], "queued", "running")
        store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))

        reopened = JobStore(store_root, recover_abandoned=True)
        recovered = reopened.get(job["job_id"])
        snap = reopened.get_snapshot(job["job_id"])
        assert recovered["state"] == "interrupted"
        assert recovered["state"] != "succeeded"
        assert recovered["result_available"] is True
        assert snap["value"]["point"] == 1234.5

    def test_complete_idempotency_key_reuses_job_otherwise_creates_new(
        self, job_store, project_store
    ):
        revision_id = project_store.save_revision(
            "proj_idemp",
            {"schema_version": "MP/1", "encoder_state": {}, "model_state": {}},
        )
        spec = {"schema_version": "MP/1", "target_col": "preco", "candidate_cols": None}
        kwargs = dict(
            project_id="proj_idemp",
            revision_id=revision_id,
            request_spec=spec,
            input_sha256="1" * 64,
            dataset_sha256="2" * 64,
            code_sha="3" * 40,
        )
        first = job_store.create(**kwargs)
        job_store.update_transition(first["job_id"], "queued", "running")
        job_store.save_snapshot(first["job_id"], sample_snapshot(first["job_id"], "proj_idemp"))
        job_store.update_transition(first["job_id"], "running", "succeeded")

        reused = job_store.create(**kwargs)
        assert reused["job_id"] == first["job_id"]
        assert reused["state"] == "succeeded"
        assert job_store.get_snapshot(reused["job_id"])["job_id"] == first["job_id"]

        other = job_store.create(
            **dict(kwargs, request_spec={**spec, "target_col": "aluguel"})
        )
        assert other["job_id"] != first["job_id"]
        assert other["state"] == "queued"

        incomplete = job_store.create(project_id="proj_idemp", revision_id=revision_id)
        another_incomplete = job_store.create(
            project_id="proj_idemp", revision_id=revision_id
        )
        assert incomplete["job_id"] != another_incomplete["job_id"]

    def test_no_mid_search_resume_api(self):
        assert not hasattr(JobStore, "resume_search")
        assert not hasattr(LocalTaskRunner, "resume_search")
        assert not hasattr(LocalTaskRunner, "resume")
