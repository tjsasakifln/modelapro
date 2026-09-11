"""C11-A05: interrupted writes, unknown schema, traversal, pickle."""

import json
import pickle
import sqlite3

import pytest

from modules.job_store import (
    JobStore,
    PathEscapeError,
    SchemaVersionError,
    STORE_DB_NAME,
    UnsafePayloadError,
)
from modules.project_store import ProjectStore, RevisionImmutableError

from tests.c11_persistence.conftest import sample_snapshot


class TestDurabilityAndSafety:
    def test_storage_lives_only_under_temp_root(self, job_store, store_root):
        job = job_store.create()
        job_store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        assert job_store.root == store_root.resolve()
        snap = job_store.root / "jobs" / job["job_id"] / "snapshot.json"
        assert snap.is_file()
        assert store_root.resolve() in snap.resolve().parents

    def test_truncated_write_does_not_corrupt_existing_snapshot(self, job_store):
        job = job_store.create()
        original = sample_snapshot(job["job_id"])
        original["value"]["point"] = 99.0
        job_store.save_snapshot(job["job_id"], original)
        dest = job_store.root / "jobs" / job["job_id"] / "snapshot.json"
        crash = dest.parent / "c11-crash.tmp"
        crash.write_text("{this is not complete JSON", encoding="utf-8")
        dest.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")
        loaded = job_store.get_snapshot(job["job_id"])
        assert loaded["value"]["point"] == 99.0
        assert job_store.get(job["job_id"])["result_available"] is True

    def test_unknown_schema_version_refuses_to_mutate_store(self, store_root):
        store = JobStore(store_root, recover_abandoned=False)
        job = store.create()
        store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE meta SET value = '99' WHERE key = 'storage_schema_version'"
        )
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            JobStore(store_root, recover_abandoned=False)
        conn = sqlite3.connect(str(store_root / STORE_DB_NAME))
        row = conn.execute(
            "SELECT state, result_available FROM jobs WHERE job_id = ?",
            (job["job_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "queued"
        assert row[1] == 1
        snap = json.loads(
            (store_root / "jobs" / job["job_id"] / "snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        assert snap["job_id"] == job["job_id"]

    def test_path_traversal_is_rejected(self, job_store, project_store):
        with pytest.raises(PathEscapeError):
            job_store.create(job_id="../outside")
        with pytest.raises(PathEscapeError):
            project_store.save_revision(
                "proj_safe",
                {
                    "schema_version": "MP/1",
                    "encoder_state": {},
                    "model_state": {},
                    "artifact_refs": {"leak": "../../etc/passwd"},
                },
            )
        with pytest.raises(PathEscapeError):
            project_store.save_revision(
                "proj_safe",
                {
                    "schema_version": "MP/1",
                    "encoder_state": {},
                    "model_state": {},
                    "artifact_refs": {"abs": "/tmp/evil.json"},
                },
            )
        assert not (job_store.root.parent / "outside").exists()

    def test_pickle_and_model_object_are_not_deserialized(self, job_store, project_store):
        with pytest.raises(UnsafePayloadError):
            project_store.save_revision(
                "proj_pickle",
                {
                    "schema_version": "MP/1",
                    "model_object": pickle.dumps({"coef": 1.0}),
                    "encoder_state": {},
                    "model_state": {},
                },
            )
        with pytest.raises(UnsafePayloadError):
            job_store.save_snapshot(
                job_store.create()["job_id"],
                {"schema_version": "MP/1", "model_object": {"__pickle__": "gASV"}},
            )
        job = job_store.create()
        dest = job_store.root / "jobs" / job["job_id"] / "snapshot.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pickle.dumps({"executed": True}))
        assert job_store.get_snapshot(job["job_id"]) is None
        with pytest.raises(UnsafePayloadError):
            project_store.save_revision(
                "proj_pickle",
                {
                    "schema_version": "MP/1",
                    "candidate_fit": {"model_object": "nope"},
                    "encoder_state": {},
                    "model_state": {},
                },
            )

    def test_unknown_revision_schema_is_rejected_and_revisions_are_immutable(
        self, project_store
    ):
        with pytest.raises(SchemaVersionError):
            project_store.save_revision(
                "proj_schema",
                {"schema_version": "MP/999", "encoder_state": {}, "model_state": {}},
            )
        revision_id = project_store.save_revision(
            "proj_schema",
            {"schema_version": "MP/1", "encoder_state": {"v": 1}, "model_state": {}},
        )
        with pytest.raises(RevisionImmutableError):
            project_store.save_revision(
                "proj_schema",
                {
                    "schema_version": "MP/1",
                    "revision_id": revision_id,
                    "encoder_state": {"v": 2},
                    "model_state": {},
                },
            )
        loaded = project_store.load_revision("proj_schema", revision_id)
        assert loaded["encoder_state"]["v"] == 1

    def test_non_finite_numbers_are_rejected_in_snapshot(self, job_store):
        job = job_store.create()
        with pytest.raises(UnsafePayloadError):
            job_store.save_snapshot(
                job["job_id"],
                {"schema_version": "MP/1", "value": {"point": float("nan")}},
            )
        assert job_store.get_snapshot(job["job_id"]) is None
