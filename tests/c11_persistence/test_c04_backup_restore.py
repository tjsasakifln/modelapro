import json

import pytest

from modules.job_store import BackupIntegrityError, JobStore, SchemaVersionError
from modules.project_store import ProjectStore

from tests.c11_persistence.conftest import sample_snapshot


def test_backup_restore_preserves_snapshot_revision_and_artifact(tmp_path):
    source = JobStore(tmp_path / "source", recover_abandoned=False)
    projects = ProjectStore(source.root)
    revision_id = projects.save_revision(
        "project_1", {"schema_version": "MP/1", "encoder_state": {}, "model_state": {}}
    )
    job = source.create(project_id="project_1", revision_id=revision_id)
    source.save_snapshot(job["job_id"], sample_snapshot(job["job_id"], "project_1"))
    source.save_artifact(job["job_id"], "evidence.json", b'{"sealed": true}')

    backup = source.export_backup(tmp_path / "backup")
    manifest = json.loads((backup / "modelapro-store-manifest.json").read_text())
    assert {entry["path"] for entry in manifest["files"]} >= {
        "c11.sqlite", f"jobs/{job['job_id']}/snapshot.json", "projects/project_1/revisions/" + revision_id + ".json"
    }
    restored = JobStore.restore_backup(backup, tmp_path / "restored")
    assert restored.get_snapshot(job["job_id"])["job_id"] == job["job_id"]
    assert restored.get_artifact(job["job_id"], "evidence.json") == b'{"sealed": true}'
    assert ProjectStore(restored.root).load_revision("project_1", revision_id)["revision_id"] == revision_id


def test_restore_rejects_corruption_and_nonempty_destination(tmp_path):
    source = JobStore(tmp_path / "source", recover_abandoned=False)
    job = source.create()
    source.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
    backup = source.export_backup(tmp_path / "backup")
    (backup / "jobs" / job["job_id"] / "snapshot.json").write_text("{}")
    with pytest.raises(BackupIntegrityError):
        JobStore.restore_backup(backup, tmp_path / "restore")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("do not overwrite")
    with pytest.raises(BackupIntegrityError):
        JobStore.restore_backup(backup, occupied)
    assert (occupied / "keep").read_text() == "do not overwrite"


def test_restore_refuses_newer_schema(tmp_path):
    source = JobStore(tmp_path / "source", recover_abandoned=False)
    backup = source.export_backup(tmp_path / "backup")
    manifest_path = backup / "modelapro-store-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["storage_schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SchemaVersionError):
        JobStore.restore_backup(backup, tmp_path / "restore")
