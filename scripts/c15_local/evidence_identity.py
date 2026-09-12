"""Bind a job's evidence and package bytes to the exact GitHub checkout/run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def identity() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
    pr = event.get("pull_request") or {}
    return {
        "schema": "MP-C06-EVIDENCE/1",
        "pr_head_sha": (pr.get("head") or {}).get("sha"),
        "base_sha": (pr.get("base") or {}).get("sha") or event.get("before"),
        "tested_commit_sha": git("rev-parse", "HEAD"),
        "tree_sha": git("rev-parse", "HEAD^{tree}"),
        "parents": git("show", "-s", "--format=%P", "HEAD").split(),
        "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "job": os.environ.get("GITHUB_JOB", "local"),
        "source_dirty": bool(git("status", "--porcelain")),
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["start", "seal"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output / "identity.json"
    if args.phase == "start":
        data = identity()  # Inspect cleanliness before creating any output.
        args.output.mkdir(parents=True, exist_ok=True)
    else:
        data = json.loads(target.read_text(encoding="utf-8"))
        data["tracked_source_changes"] = git("diff", "HEAD", "--name-only").splitlines()
        data["tracked_source_dirty_after"] = bool(data["tracked_source_changes"])
        output_relative = args.output.resolve().relative_to(Path.cwd().resolve()).as_posix()
        untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
        data["unexpected_untracked_source"] = [
            name for name in untracked if not name.startswith(output_relative + "/")
        ]
        data["files"] = {
            str(p.relative_to(args.output)).replace("\\", "/"): digest(p)
            for p in sorted(args.output.rglob("*")) if p.is_file() and p != target
        }
        data["package_hashes"] = {
            name: sha for name, sha in data["files"].items()
            if name.endswith((".whl", ".tar.gz", ".exe"))
        }
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
