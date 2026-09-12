"""Require every mandatory GitHub Actions job result to be success AND require
the evidence artifacts those jobs claim to have produced to agree with them.

Used by the aggregator job (if: always()). Missing, skipped, cancelled,
failure, and empty results are not success. A fast/diagnostic suite cannot
green the PR through this script.

Gap R20-A: a job can exit zero while the artifact it produced records
``exit_code: 1`` (a lost pipe status, a diagnostic mode, a suite that never
ran). Job conclusions alone cannot see that, so this script also opens the
downloaded artifacts and fails when the recorded evidence disagrees with the
green job, is absent, is unparseable, or was produced from another SHA.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping


SUCCESS = "success"

# Explicit inventory of blocking jobs on the C18/P04 workflow. A job that
# never ran is not success: the aggregator must see every name.
DEFAULT_REQUIRED_JOBS = (
    "lint",
    "c15-tests-linux",
    "c15-tests-windows",
    "build-sdist-wheel",
    "install-eval-linux",
    "wide-suite-linux",
    "c16-harness",
    "p04-harness",
)

# The candidate is accepted with the strict mode, never with the diagnostic
# mode that only describes the old base.
CANDIDATE_MODE = "accept-candidate"


def evaluate(results: Mapping[str, str], required: list[str] | tuple[str, ...] | None = None) -> int:
    if not results and not required:
        print("aggregator: no required jobs declared", file=sys.stderr)
        return 1
    inventory = list(required) if required is not None else list(results.keys())
    missing = [name for name in inventory if name not in results]
    bad = {name: results.get(name, "missing") for name in inventory if results.get(name) != SUCCESS}
    for name in missing:
        bad[name] = "missing"
    if bad:
        print("aggregator: required jobs not success:", json.dumps(bad, sort_keys=True), file=sys.stderr)
        return 1
    print("aggregator: all required jobs succeeded:", json.dumps({k: results[k] for k in inventory}, sort_keys=True))
    return 0


def normalize(payload: Mapping) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in payload.items():
        if isinstance(value, Mapping) and "result" in value:
            out[str(name)] = str(value.get("result") or "")
        else:
            out[str(name)] = str(value or "")
    return out


def _load_json(path: Path, problems: list[str], label: str) -> dict | None:
    if not path.is_file():
        problems.append(f"{label}: artifact absent at {path}")
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unreadable file
        problems.append(f"{label}: unreadable ({exc})")
        return None
    if not raw.strip():
        problems.append(f"{label}: artifact is empty")
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        problems.append(f"{label}: not parseable JSON ({exc})")
        return None
    if not isinstance(payload, dict):
        problems.append(f"{label}: expected a JSON object, got {type(payload).__name__}")
        return None
    return payload


def _sha_matches(recorded: str, expected: str) -> bool:
    a, b = (recorded or "").strip().lower(), (expected or "").strip().lower()
    if not a or not b:
        return False
    shortest = min(len(a), len(b))
    if shortest < 7:
        return False
    return a[:shortest] == b[:shortest]


def _is_failure_finding(entry: object) -> bool:
    """A finding is a defect only when it carries a failure signal.

    Two shapes reach ``run.json``: entries the runner builds from the JUnit
    parser (always a failed/errored case, carrying nodeid + message) and
    entries the extension tests write themselves, which record the observed
    state whether or not it is good (``present: true`` is a success record).
    """
    if not isinstance(entry, Mapping):
        return True
    if entry.get("parse") == "error":
        return True
    if entry.get("nodeid") and entry.get("message"):
        return True
    if entry.get("present") is False:
        return True
    return False


def check_p04_run(path: Path, expected_sha: str | None = None, mode: str = CANDIDATE_MODE) -> list[str]:
    """The P04 runner artifact must show a real, strict, clean candidate run."""
    problems: list[str] = []
    payload = _load_json(path, problems, "p04 run.json")
    if payload is None:
        return problems

    recorded_mode = str(payload.get("mode") or "")
    if recorded_mode != mode:
        problems.append(f"p04 run.json: mode is {recorded_mode!r}, required {mode!r}")

    if "exit_code" not in payload:
        problems.append("p04 run.json: exit_code absent (runner status was lost)")
    elif payload.get("exit_code") != 0:
        problems.append(f"p04 run.json: exit_code is {payload.get('exit_code')!r}, required 0")

    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        problems.append("p04 run.json: no runs recorded (suite did not execute)")
    else:
        for entry in runs:
            if not isinstance(entry, Mapping):
                problems.append(f"p04 run.json: malformed run entry {entry!r}")
                continue
            name = entry.get("name", "?")
            if entry.get("returncode") != 0:
                problems.append(f"p04 run.json: run {name} returncode {entry.get('returncode')!r}, required 0")
            if entry.get("failed"):
                problems.append(f"p04 run.json: run {name} reports {entry.get('failed')} failed cases")
            if not entry.get("passed"):
                problems.append(f"p04 run.json: run {name} recorded zero passed cases")
        names = {str(e.get("name")) for e in runs if isinstance(e, Mapping)}
        if "extensions" not in names:
            problems.append("p04 run.json: the strict extensions suite is absent from runs")

    if payload.get("skip_xfail_count"):
        problems.append(f"p04 run.json: {payload.get('skip_xfail_count')} skip/xfail on applicable tests")

    # `findings` is an event log, not a defect list: run.py appends every
    # finding_*.json the extension tests write, including the ones that record
    # success (present: true). Failing on mere presence would keep even a fully
    # fixed candidate red. Fail on the entries that carry a failure signal.
    bad_findings = [f for f in (payload.get("findings") or []) if _is_failure_finding(f)]
    if bad_findings:
        ids = [str(f.get("nodeid") or f.get("id") or f) for f in bad_findings[:8]]
        problems.append(f"p04 run.json: {len(bad_findings)} failure findings recorded, e.g. {ids}")

    if expected_sha:
        if not _sha_matches(str(payload.get("sha") or ""), expected_sha):
            problems.append(
                f"p04 run.json: sha {payload.get('sha')!r} does not match candidate {expected_sha!r} (stale artifact)"
            )
    return problems


def check_junit(path: Path, min_tests: int = 1, label: str = "junit") -> list[str]:
    """A JUnit XML that is absent, unparseable, empty or red is not success."""
    problems: list[str] = []
    if not path.is_file():
        problems.append(f"{label}: artifact absent at {path}")
        return problems
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        problems.append(f"{label}: not parseable XML ({exc})")
        return problems
    cases = list(tree.iter("testcase"))
    if len(cases) < min_tests:
        problems.append(f"{label}: {len(cases)} testcases, floor is {min_tests} (suite truncated or not run)")
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    if failed:
        ids = [f"{c.attrib.get('classname', '')}::{c.attrib.get('name', '')}" for c in failed[:10]]
        problems.append(f"{label}: {len(failed)} failed/errored testcases, e.g. {ids}")
    return problems


def check_c16(path: Path, expected_sha: str | None = None) -> list[str]:
    """The independent harness summary must show zero reprovados / violations."""
    problems: list[str] = []
    payload = _load_json(path, problems, "c16.json")
    if payload is None:
        return problems
    counts = payload.get("counts")
    if not isinstance(counts, Mapping):
        problems.append("c16.json: counts block absent")
        return problems
    if counts.get("reprovados"):
        problems.append(f"c16.json: {counts.get('reprovados')} reprovados")
    if counts.get("violacoes_a04_skip_xfail"):
        problems.append(f"c16.json: {counts.get('violacoes_a04_skip_xfail')} skip/xfail classification violations")
    if not counts.get("aprovados"):
        problems.append("c16.json: zero aprovados (harness did not really run)")
    if counts.get("disjoint") is not True:
        problems.append("c16.json: buckets are not disjoint")
    if expected_sha and not _sha_matches(str(payload.get("sha") or ""), expected_sha):
        problems.append(
            f"c16.json: sha {payload.get('sha')!r} does not match candidate {expected_sha!r} (stale artifact)"
        )
    return problems


def verify_artifacts(
    artifacts_dir: Path,
    expected_sha: str | None = None,
    min_wide_tests: int = 1,
    p04_mode: str = CANDIDATE_MODE,
) -> list[str]:
    """Open every mandatory evidence artifact and report what disagrees."""
    root = Path(artifacts_dir)
    problems: list[str] = []
    if not root.is_dir():
        return [f"artifacts: directory absent at {root} (no evidence was downloaded)"]
    problems.extend(check_p04_run(root / "run.json", expected_sha=expected_sha, mode=p04_mode))
    problems.extend(check_junit(root / "wide.junit.xml", min_tests=min_wide_tests, label="wide.junit.xml"))
    problems.extend(check_c16(root / "c16.json", expected_sha=expected_sha))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-json", help="JSON object of job_name -> result or GitHub needs")
    parser.add_argument(
        "--required-jobs",
        default="",
        help="comma-separated inventory; missing/unrun names fail. empty = keys of results only",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="directory with the downloaded evidence (run.json, wide.junit.xml, c16.json)",
    )
    parser.add_argument("--expected-sha", default="", help="candidate SHA the artifacts must have been produced from")
    parser.add_argument("--min-wide-tests", type=int, default=1, help="floor committed before the run")
    parser.add_argument("--p04-mode", default=CANDIDATE_MODE, help="mode the P04 runner artifact must record")
    args = parser.parse_args(argv)
    if args.results_json:
        payload = json.loads(args.results_json)
    else:
        payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        print("aggregator: results must be a JSON object", file=sys.stderr)
        return 1
    required = [item.strip() for item in args.required_jobs.split(",") if item.strip()] or None
    rc = evaluate(normalize(payload), required=required)

    if args.artifacts_dir is not None:
        problems = verify_artifacts(
            args.artifacts_dir,
            expected_sha=args.expected_sha or None,
            min_wide_tests=args.min_wide_tests,
            p04_mode=args.p04_mode,
        )
        if problems:
            print("aggregator: evidence artifacts disagree with the job results:", file=sys.stderr)
            for item in problems:
                print(f"  - {item}", file=sys.stderr)
            rc = rc or 1
        else:
            print("aggregator: evidence artifacts agree with the job results")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
