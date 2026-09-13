#!/usr/bin/env python3
"""P04 reproducible runner.

Modes isolate diagnosis of BASE_SHA from acceptance of a composed candidate
by output directory and environment, not by skip/xfail.

    python scripts/pro_workflow/run.py --mode diagnose-base --output DIR
    python scripts/pro_workflow/run.py --mode accept-candidate --output DIR

Always records SHA, command, exit code, JUnit, and findings. PYTHONPATH is
cleared. New tests may fail the base: that is a finding.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_TARGETS = [
    "tests/pro_workflow/p04/test_oracle_independence.py",
    "tests/pro_workflow/p04/test_corpus_s01_s08.py",
    "tests/pro_workflow/p04/test_mutations.py",
    "tests/pro_workflow/p04/test_metrics_and_pilot.py",
    "tests/pro_workflow/p04/test_runner_and_ci.py",
    "tests/pro_workflow/p04/test_browser_composed.py",
]
CANDIDATE_TARGETS = [
    "tests/pro_workflow/p04/test_candidate_extensions.py",
]


def git_sha(cwd: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return (r.stdout or "").strip() or "UNKNOWN"


def parse_junit(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    tree = ET.parse(path)
    cases = []
    for case in tree.iter("testcase"):
        status = "passed"
        message = ""
        skipped = case.find("skipped")
        failed = case.find("failure")
        errored = case.find("error")
        if skipped is not None:
            status = "skipped"
            message = (skipped.attrib.get("message") or "") + (skipped.text or "")
            if "xfail" in message.lower():
                status = "xfail"
        elif failed is not None:
            status = "failed"
            message = (failed.attrib.get("message") or "") + "\n" + (failed.text or "")
        elif errored is not None:
            status = "error"
            message = (errored.attrib.get("message") or "") + "\n" + (errored.text or "")
        nodeid = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        cases.append(
            {
                "nodeid": nodeid,
                "name": case.attrib.get("name"),
                "time": case.attrib.get("time"),
                "status": status,
                "message": message.strip()[:1200],
            }
        )
    return cases


def run_pytest(targets: list[str], junit: Path, log: Path, env: dict) -> tuple[int, list[str]]:
    cmd = [sys.executable, "-m", "pytest", *targets, "-q", "--tb=short", f"--junitxml={junit}"]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        handle.write(f"sha={env.get('P04_SHA')}\n")
        handle.write(f"$ {' '.join(cmd)}\n")
        handle.flush()
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return proc.returncode, cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P04 independent-reference runner")
    parser.add_argument(
        "--mode",
        choices=("diagnose-base", "accept-candidate"),
        required=True,
        help="diagnose-base records failures as findings; accept-candidate requires them to pass",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=2, help="how many times to run the core suite")
    args = parser.parse_args(argv)

    out = args.output if args.output.is_absolute() else (Path.cwd() / args.output)
    out.mkdir(parents=True, exist_ok=True)
    sha = git_sha(ROOT)
    findings_dir = out / "findings"
    findings_dir.mkdir(exist_ok=True)

    base_env = os.environ.copy()
    base_env.pop("PYTHONPATH", None)
    base_env["P04_SHA"] = sha
    base_env["P04_FINDINGS_DIR"] = str(findings_dir)
    base_env["MODELA_SKIP_DOTENV"] = "1"
    if args.mode == "accept-candidate":
        base_env["P04_REQUIRE_EXTENSIONS"] = "1"
    else:
        base_env.pop("P04_REQUIRE_EXTENSIONS", None)

    summary = {
        "campaign_id": "MP-PRO-20260911/P04",
        "mode": args.mode,
        "sha": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "cwd": str(ROOT),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "runs": [],
        "skip_xfail_count": 0,
        "findings": [],
    }

    rc_all = 0
    for idx in range(1, max(args.repeat, 1) + 1):
        junit = out / f"p04-core-{idx}.junit.xml"
        log = out / f"p04-core-{idx}.log"
        rc, cmd = run_pytest(CORE_TARGETS, junit, log, base_env)
        cases = parse_junit(junit)
        skip_xfail = [c for c in cases if c["status"] in {"skipped", "xfail"}]
        failed = [c for c in cases if c["status"] in {"failed", "error"}]
        summary["skip_xfail_count"] += len(skip_xfail)
        summary["runs"].append(
            {
                "name": f"core-{idx}",
                "command": cmd,
                "returncode": rc,
                "log": str(log),
                "junit": str(junit),
                "passed": sum(1 for c in cases if c["status"] == "passed"),
                "failed": len(failed),
                "skip_xfail": [c["nodeid"] for c in skip_xfail],
                "failures": [{"nodeid": c["nodeid"], "message": c["message"][:400]} for c in failed],
            }
        )
        if rc != 0:
            rc_all = rc if rc_all == 0 else rc_all
        for c in failed:
            summary["findings"].append(
                {"suite": "core", "run": idx, "nodeid": c["nodeid"], "message": c["message"][:400]}
            )

    junit = out / "p04-extensions.junit.xml"
    log = out / "p04-extensions.log"
    rc, cmd = run_pytest(CANDIDATE_TARGETS, junit, log, base_env)
    cases = parse_junit(junit)
    failed = [c for c in cases if c["status"] in {"failed", "error"}]
    skip_xfail = [c for c in cases if c["status"] in {"skipped", "xfail"}]
    summary["skip_xfail_count"] += len(skip_xfail)
    summary["runs"].append(
        {
            "name": "extensions",
            "command": cmd,
            "returncode": rc,
            "log": str(log),
            "junit": str(junit),
            "passed": sum(1 for c in cases if c["status"] == "passed"),
            "failed": len(failed),
            "skip_xfail": [c["nodeid"] for c in skip_xfail],
            "failures": [{"nodeid": c["nodeid"], "message": c["message"][:400]} for c in failed],
        }
    )
    if args.mode == "accept-candidate" and rc != 0:
        rc_all = rc if rc_all == 0 else rc_all
    for c in failed:
        summary["findings"].append({"suite": "extensions", "nodeid": c["nodeid"], "message": c["message"][:400]})
    for path in sorted(findings_dir.glob("finding_*.json")):
        try:
            summary["findings"].append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            summary["findings"].append({"file": str(path), "parse": "error"})

    if summary["skip_xfail_count"]:
        rc_all = 2 if rc_all == 0 else rc_all
        summary["a04_violation"] = "skip/xfail is not allowed on applicable P04 tests"

    summary["exit_code"] = rc_all
    (out / "run.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"sha": sha, "mode": args.mode, "exit": rc_all, "output": str(out)}, ensure_ascii=False))
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
