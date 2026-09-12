"""Record local operational checks without pretending they ran on Windows."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


CHECKS = ("queue_cancel", "backup_restore", "disk_refusal", "pdf_probe", "technical_corpus")


def _max_rss_kib() -> int | None:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except ImportError:  # Windows has no resource module.
        return None


def _result(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        payload = fn()
        return {"status": "PASSED", "elapsed_seconds": round(time.monotonic() - started, 6), **payload}
    except Exception as exc:  # Evidence must preserve a failure, never turn it green.
        return {"status": "FAILED", "elapsed_seconds": round(time.monotonic() - started, 6), "error": repr(exc)}


def _queue_cancel(root: Path) -> dict[str, Any]:
    from modules.job_store import JobStore
    from modules.local_task_runner import LocalTaskRunner

    store = JobStore(root / "queue", recover_abandoned=False)
    first, second = store.create(), store.create()
    runner = LocalTaskRunner(store, max_workers=1, max_queue=1, min_free_disk_bytes=0, recover_abandoned=False)

    def complete_first() -> dict[str, str]:
        time.sleep(0.1)
        store.save_snapshot(
            first["job_id"],
            {"schema_version": "MP/1", "job_id": first["job_id"], "synthetic": True},
        )
        return {"outcome": "succeeded"}

    try:
        runner.submit(first["job_id"], complete_first)
        runner.submit(second["job_id"], lambda: {"outcome": "succeeded"})
        runner.cancel(second["job_id"])
    finally:
        runner.shutdown(wait=True)
    first_state = store.get(first["job_id"])["state"]
    second_state = store.get(second["job_id"])["state"]
    if first_state != "succeeded" or second_state != "cancelled":
        raise AssertionError(
            f"queue/cancel states were first={first_state!r}, second={second_state!r}"
        )
    return {"completed_job_state": first_state, "cancelled_job_state": second_state}


def _backup_restore(root: Path) -> dict[str, Any]:
    from modules.job_store import JobStore

    store = JobStore(root / "source", recover_abandoned=False)
    job = store.create()
    store.save_snapshot(
        job["job_id"],
        {"schema_version": "MP/1", "job_id": job["job_id"], "synthetic": True},
    )
    store.save_artifact(job["job_id"], "evidence.json", b'{"synthetic":true}')
    backup = store.export_backup(root / "backup")
    restored = JobStore.restore_backup(backup, root / "restored")
    if restored.get_snapshot(job["job_id"])["job_id"] != job["job_id"]:
        raise AssertionError("restored snapshot identity differs")
    if restored.get_artifact(job["job_id"], "evidence.json") != b'{"synthetic":true}':
        raise AssertionError("restored evidence differs")
    return {
        "backup": str(backup),
        "restored_job_id": job["job_id"],
        "evidence_parity": True,
    }


def _disk_refusal(root: Path) -> dict[str, Any]:
    from modules.job_store import JobStore
    from modules.local_task_runner import LocalTaskRunner

    store = JobStore(root / "disk", recover_abandoned=False)
    runner = LocalTaskRunner(store, min_free_disk_bytes=2**63 - 1, recover_abandoned=False)
    try:
        try:
            runner.submit(store.create()["job_id"], lambda: {"outcome": "succeeded"})
        except RuntimeError as exc:
            if "disk" not in str(exc).lower():
                raise
            return {"refusal": str(exc)}
        raise AssertionError("low-disk job was accepted")
    finally:
        runner.shutdown(wait=True)


def _pdf_probe() -> dict[str, Any]:
    from scripts.c15_local.pdf_env import probe_weasyprint

    probe = probe_weasyprint()
    if not probe.ok:
        raise RuntimeError(probe.message)
    return {"available": bool(probe.ok), "detail": probe.message}


def run_harness(budget_path: Path, *, exercise: bool = False, corpus: list[str] | None = None) -> dict[str, Any]:
    """Return JSON-ready evidence; absent exercise is explicitly NOT_RUN."""
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    if budget.get("schema_version") != "MP-COM-PERF/1":
        raise ValueError("unrecognised performance budget")
    disk = shutil.disk_usage(budget_path.parent)
    evidence: dict[str, Any] = {
        "schema_version": "MP-COM-OPERATIONS/1",
        "budget_path": str(budget_path),
        "budget_status": budget["status"],
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "pid": os.getpid(),
            "free_disk_bytes": disk.free,
        },
        "checks": {name: {"status": "NOT_RUN"} for name in CHECKS},
        "resource": {
            "elapsed_seconds": None,
            "max_rss_kib": _max_rss_kib(),
            "free_disk_bytes": disk.free,
            "exit_code": 0,
        },
    }
    if not exercise:
        return evidence
    with tempfile.TemporaryDirectory(prefix="modelapro-c04-operational-") as raw:
        root = Path(raw)
        evidence["checks"]["queue_cancel"] = _result(lambda: _queue_cancel(root))
        evidence["checks"]["backup_restore"] = _result(lambda: _backup_restore(root))
        evidence["checks"]["disk_refusal"] = _result(lambda: _disk_refusal(root))
        evidence["checks"]["pdf_probe"] = _result(_pdf_probe)
    if corpus:
        evidence["checks"]["technical_corpus"] = _result(
            lambda: {"exit_code": subprocess.run(corpus, check=False).returncode, "command": corpus}
        )
        if evidence["checks"]["technical_corpus"].get("exit_code") != 0:
            evidence["checks"]["technical_corpus"]["status"] = "FAILED"
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise", action="store_true", help="run local checks; does not certify Windows")
    parser.add_argument("--corpus", nargs=argparse.REMAINDER, help="optional existing technical corpus command")
    args = parser.parse_args(argv)
    started = time.monotonic()
    evidence = run_harness(args.budget, exercise=args.exercise, corpus=args.corpus)
    failed = any(check.get("status") == "FAILED" for check in evidence["checks"].values())
    exit_code = 1 if failed else 0
    evidence["resource"] = evidence.get("resource", {}) | {
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "max_rss_kib": _max_rss_kib(),
        "exit_code": exit_code,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
