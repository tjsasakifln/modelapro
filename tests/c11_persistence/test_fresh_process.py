"""Fresh-interpreter consumer of the public C11 classes."""

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = r"""
import json
import sys
import time

sys.path.insert(0, sys.argv[1])
from modules.job_store import JobStore
from modules.project_store import ProjectStore
from modules.local_task_runner import LocalTaskRunner

root = sys.argv[2]
store = JobStore(root, recover_abandoned=True)
projects = ProjectStore(root)
revision_id = projects.save_revision(
    "proj_fresh",
    {
        "schema_version": "MP/1",
        "encoder_state": {"imputer": None},
        "model_state": {"spec": "ols"},
    },
)
job = store.create(
    project_id="proj_fresh",
    revision_id=revision_id,
    request_spec={"schema_version": "MP/1", "target_col": "y"},
    input_sha256="i" * 64,
    dataset_sha256="d" * 64,
    code_sha="c" * 40,
)
snapshot = {"schema_version": "MP/1", "job_id": job["job_id"], "value": {"point": 3.5}}
store.save_snapshot(job["job_id"], snapshot)
got = store.get_snapshot(job["job_id"])
assert got["value"]["point"] == 3.5
loaded = projects.load_revision("proj_fresh", revision_id)
assert loaded["revision_id"] == revision_id
assert store.get_snapshot("job_does_not_exist") is None

started = []

def work(cancel_requested=None):
    started.append(True)
    return {"outcome": "failed"}

runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
job2 = store.create()
runner.cancel(job2["job_id"])
runner.submit(job2["job_id"], work)
for _ in range(100):
    if store.get(job2["job_id"])["state"] != "queued":
        break
    time.sleep(0.02)
runner.shutdown(wait=True)
print(json.dumps({
    "job_id": job["job_id"],
    "revision_id": revision_id,
    "snap_point": got["value"]["point"],
    "job2_state": store.get(job2["job_id"])["state"],
    "started": started,
}))
"""


def test_fresh_process_public_api(tmp_path):
    repo_root = str(Path(__file__).resolve().parents[2])
    root = tmp_path / "fresh-store"
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, repo_root, str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["job_id"].startswith("job_")
    assert payload["revision_id"].startswith("rev_")
    assert payload["snap_point"] == 3.5
    assert payload["job2_state"] == "cancelled"
    assert payload["started"] == []
