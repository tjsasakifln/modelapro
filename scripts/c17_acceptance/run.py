"""C17 acceptance runner. Records HEAD SHA before any pytest invocation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def run_pytest(args: list[str], log_path: Path) -> int:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    cmd = [sys.executable, "-m", "pytest", *args]
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(cmd)}\n")
        handle.flush()
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="C17 acceptance on the current SHA")
    parser.add_argument("--output", required=True, help="Directory for logs and SHA")
    parser.add_argument("--full", action="store_true", help="Also run campaign suites and C16 harness")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    sha = git_head()
    (out / "INTEGRATION_HEAD_SHA.txt").write_text(sha + "\n", encoding="utf-8")
    env_lines = [
        f"sha={sha}",
        f"python={sys.version.replace(chr(10), ' ')}",
        f"executable={sys.executable}",
        f"platform={sys.platform}",
        f"os_name={os.name}",
        f"cwd={ROOT}",
        f"pythonpath={os.environ.get('PYTHONPATH', '')}",
        f"started={datetime.now(timezone.utc).isoformat()}",
    ]
    (out / "env.txt").write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    results = {"sha": sha, "runs": []}
    rc_all = 0
    for idx in (1, 2):
        log = out / f"c17_pytest_{idx}.log"
        rc = run_pytest(["tests/c17_integration", "-q", "--tb=short"], log)
        results["runs"].append({"name": f"c17_pytest_{idx}", "returncode": rc, "log": str(log)})
        rc_all = rc_all or rc

    if args.full:
        suites = [
            "tests/c01_input",
            "tests/c02_schema",
            "tests/c03_normative",
            "tests/c04_fitting",
            "tests/c05_search",
            "tests/c06_transformations",
            "tests/c07_validation",
            "tests/c08_report",
            "tests/c09_frontend",
            "tests/c10_pipeline",
            "tests/c11_persistence",
            "tests/c12_evidence",
            "tests/c13_decisions",
            "tests/c14_batch",
            "tests/c15_packaging",
            "tests/test_data_loader.py",
            "tests/test_model_builder.py",
            "tests/test_nbr14653.py",
            "tests/test_optimal_combination.py",
            "tests/test_transformations.py",
            "tests/test_results_generator.py",
            "tests/test_api.py",
            "tests/test_forms_heuristics.py",
            "tests/test_audit_fixes.py",
            "tests/test_full_flow.py",
        ]
        log = out / "campaign_pytest.log"
        rc = run_pytest([*suites, "-q", "--tb=line"], log)
        results["runs"].append({"name": "campaign_pytest", "returncode": rc, "log": str(log)})
        rc_all = rc_all or rc
        harness = ROOT / "scripts" / "c16_acceptance" / "run_harness.py"
        if harness.is_file():
            summary = out / "c16_summary.json"
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            with (out / "c16_harness.log").open("w", encoding="utf-8") as handle:
                proc = subprocess.run(
                    [sys.executable, str(harness), "--output", str(summary)],
                    cwd=ROOT,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
            results["runs"].append({"name": "c16_harness", "returncode": proc.returncode, "log": str(out / "c16_harness.log")})
            rc_all = rc_all or proc.returncode

    results["returncode"] = rc_all
    (out / "c17_runner.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"sha": sha, "returncode": rc_all, "output": str(out)}, indent=2))
    return rc_all


if __name__ == "__main__":
    raise SystemExit(main())
