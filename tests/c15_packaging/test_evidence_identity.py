"""The tested merge is valid; stale runs, altered bytes and wrong parents are not."""
import hashlib
import json
import subprocess

import pytest

from c15_local.aggregate_required import check_identity


def evidence(tmp_path, monkeypatch):
    base, head, tested = "1" * 40, "2" * 40, "3" * 40
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"sha": head}, "base": {"sha": base}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    root = tmp_path / "evidence" / "p04-harness"
    root.mkdir(parents=True)
    (root / "run.json").write_text('{"exit_code": 0}')
    data = {
        "schema": "MP-C06-EVIDENCE/1", "job": "p04-harness", "event": "pull_request",
        "run_id": "123", "run_attempt": "1", "pr_head_sha": head, "base_sha": base,
        "tested_commit_sha": tested, "parents": [base, head],
        "tree_sha": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
        "source_dirty": False, "tracked_source_dirty_after": False,
        "files": {"run.json": hashlib.sha256((root / "run.json").read_bytes()).hexdigest()},
    }
    return root, data, tested


def test_merge_sha_differs_from_pr_head_and_is_valid(tmp_path, monkeypatch):
    root, data, tested = evidence(tmp_path, monkeypatch)
    (root / "identity.json").write_text(json.dumps(data))
    assert data["pr_head_sha"] != tested
    assert check_identity(root, "p04-harness", tested) == []


@pytest.mark.parametrize("mutation", [
    "run", "attempt", "parents", "head", "base", "tree", "sha",
    "dirty", "dirty_after", "bytes", "extra", "missing", "empty",
])
def test_identity_and_artifact_mutations_fail(tmp_path, monkeypatch, mutation):
    root, data, tested = evidence(tmp_path, monkeypatch)
    field = {"run": "run_id", "attempt": "run_attempt", "head": "pr_head_sha", "base": "base_sha",
             "tree": "tree_sha", "sha": "tested_commit_sha"}.get(mutation)
    if field:
        data[field] = "9" * 40
    elif mutation == "parents":
        data["parents"] = list(reversed(data["parents"]))
    elif mutation in {"dirty", "dirty_after"}:
        data["source_dirty" if mutation == "dirty" else "tracked_source_dirty_after"] = True
    elif mutation == "bytes":
        (root / "run.json").write_text('{"exit_code": 1}')
    elif mutation == "extra":
        (root / "swapped.whl").write_bytes(b"swapped")
    elif mutation == "missing":
        (root / "run.json").unlink()
    elif mutation == "empty":
        data["files"] = {}
    (root / "identity.json").write_text(json.dumps(data))
    assert check_identity(root, "p04-harness", tested)
