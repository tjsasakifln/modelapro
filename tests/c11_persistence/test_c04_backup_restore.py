import json
import threading
import time

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


def test_restore_rejects_unlisted_member_and_symlink_destination(tmp_path):
    source = JobStore(tmp_path / "source", recover_abandoned=False)
    backup = source.export_backup(tmp_path / "backup")
    (backup / "unlisted-private-data.txt").write_text("must not be ignored")
    with pytest.raises(BackupIntegrityError, match="member set"):
        JobStore.restore_backup(backup, tmp_path / "restore-extra")

    (backup / "unlisted-private-data.txt").unlink()
    real_destination = tmp_path / "real-destination"
    real_destination.mkdir()
    linked_destination = tmp_path / "linked-destination"
    try:
        linked_destination.symlink_to(real_destination, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available on this platform")
    with pytest.raises(BackupIntegrityError, match="symlink"):
        JobStore.restore_backup(backup, linked_destination)


def test_restore_refuses_newer_schema(tmp_path):
    source = JobStore(tmp_path / "source", recover_abandoned=False)
    backup = source.export_backup(tmp_path / "backup")
    manifest_path = backup / "modelapro-store-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["storage_schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SchemaVersionError):
        JobStore.restore_backup(backup, tmp_path / "restore")


@pytest.mark.parametrize("kind", ["snapshot", "artifact"])
def test_backup_waits_for_file_and_database_metadata_commit(tmp_path, monkeypatch, kind):
    import modules.job_store as job_store_module

    store = JobStore(tmp_path / "source", recover_abandoned=False)
    job = store.create()
    entered = threading.Event()
    release = threading.Event()
    original = (
        job_store_module.atomic_write_json
        if kind == "snapshot"
        else job_store_module.atomic_write_bytes
    )

    def paused_write(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(
        job_store_module,
        "atomic_write_json" if kind == "snapshot" else "atomic_write_bytes",
        paused_write,
    )

    def save():
        if kind == "snapshot":
            store.save_snapshot(job["job_id"], sample_snapshot(job["job_id"]))
        else:
            store.save_artifact(job["job_id"], "proof.bin", b"sealed")

    save_thread = threading.Thread(target=save)
    save_thread.start()
    assert entered.wait(timeout=5)
    backup_thread = threading.Thread(
        target=lambda: store.export_backup(tmp_path / "backup")
    )
    backup_thread.start()
    time.sleep(0.05)
    assert backup_thread.is_alive(), (
        "backup crossed the sidecar/metadata commit window"
    )
    release.set()
    save_thread.join(timeout=5)
    backup_thread.join(timeout=5)
    assert not save_thread.is_alive() and not backup_thread.is_alive()

    restored = JobStore.restore_backup(tmp_path / "backup", tmp_path / "restored")
    if kind == "snapshot":
        assert restored.get(job["job_id"])["result_available"] is True
        assert restored.get_snapshot(job["job_id"])["job_id"] == job["job_id"]
    else:
        assert restored.get(job["job_id"])["artifact_states"]["proof.bin"]["state"] == "ready"
        assert restored.get_artifact(job["job_id"], "proof.bin") == b"sealed"
