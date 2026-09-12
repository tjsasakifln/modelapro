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
import hashlib
import json
import os
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
    return len(a) == 40 and a == b


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
        if names != {"core-1", "core-2", "extensions"} or len(runs) != 3:
            problems.append("p04 run.json: expected core-1, core-2 and extensions exactly once")

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


def check_junit(path: Path, min_tests: int = 1, label: str = "junit", forbid_skips: bool = True,
                separate_install_job: bool = False) -> list[str]:
    """A JUnit XML that is absent, unparseable, empty, skipped or red is not success.

    Skips are checked because a suite gated on an environment variable exits 0
    when the variable is absent: pytest collects the test, skips it, and the job
    stays green. Counting only failures would let a dropped env key silently
    restore the gap this artifact exists to close.
    """
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
    if forbid_skips:
        skipped = [c for c in cases if c.find("skipped") is not None and not (
            separate_install_job and "test_wheel_install_smoke" in c.attrib.get("classname", "")
            and "Set C15_INSTALL_SMOKE=1" in c.find("skipped").attrib.get("message", "")
        )]
        if skipped:
            ids = [f"{c.attrib.get('classname', '')}::{c.attrib.get('name', '')}" for c in skipped[:10]]
            problems.append(f"{label}: {len(skipped)} skipped testcases, e.g. {ids} (gate exited 0 without asserting)")
    return problems


def check_collection(root: Path, expected_sha: str | None) -> list[str]:
    problems: list[str] = []
    payload = _load_json(root / "collection.json", problems, "wide collection")
    if payload is None:
        return problems
    if (payload.get("schema") != "MP-C06-COLLECTION/1" or payload.get("exit_code") != 0
            or payload.get("tested_commit_sha") != expected_sha
            or str(payload.get("run_id")) != os.environ.get("GITHUB_RUN_ID")):
        problems.append("wide collection: invalid schema, execution status or run/commit identity")
    nodes = payload.get("nodeids")
    calls = payload.get("calls")
    if not isinstance(nodes, list) or not nodes or not isinstance(calls, dict):
        return problems + ["wide collection: selected obligations or executed calls are absent"]
    if len(nodes) != len(set(nodes)) or set(nodes) != set(calls):
        problems.append("wide collection: duplicate, missing or unselected executed obligations")
    for node, call in calls.items():
        if (not isinstance(call, dict)
                or call.get("outcome") not in {"passed", "failed", "skipped"}
                or call.get("phase") not in {"setup", "call", "teardown"}):
            problems.append(f"wide collection: malformed execution record for {node}")
        elif call.get("outcome") != "passed" and not (
            "test_wheel_install_smoke.py::" in node and call.get("outcome") == "skipped"
        ):
            problems.append(f"wide collection: obligation did not pass: {node}")
    required_files = {
        "tests/comercial/test_c06_numeric_disclosure.py",
        "tests/comercial/test_c06_commercial_surfaces.py",
        "tests/comercial/test_c06_qualification_integration.py",
        "tests/comercial/test_c06_document_flow.py",
        "tests/comercial/test_c06_cost_flow.py",
        "tests/comercial/test_c06_cost_consumer.py",
        "tests/comercial/test_c06_browser_document_flow.py",
        "tests/comercial/test_c06_browser_cost_flow.py",
        "tests/comercial/test_c06_recipient_document.py",
        "tests/comercial/test_c06_security_routes.py",
        "tests/comercial/test_c06_runtime_bootstrap.py",
        "tests/comercial/c06/test_catalog_distribution.py",
        "tests/pro_workflow/p04/test_nist_strd.py",
        "tests/comercial/c02/test_playwright_path.py",
        "tests/pro_workflow/p04/test_mutations_commercial.py",
    }
    collected_files = {node.split("::", 1)[0] for node in nodes}
    if __package__:
        from .test_inventory import check_inventory
    else:  # CI invokes this stdlib-only aggregator directly, without installing the wheel.
        from test_inventory import check_inventory
    problems.extend(check_inventory(nodes))
    if required_files - collected_files:
        problems.append("wide collection: mandatory C06 files absent: "
                        + ", ".join(sorted(required_files - collected_files)))
    try:
        cases = list(ET.parse(root / "wide.junit.xml").iter("testcase"))
        actual = {f"{c.get('classname')}::{c.get('name')}" for c in cases}
        expected = set()
        for node in nodes:
            file, tail = node.split("::", 1)
            parts = tail.split("::")
            expected.add(".".join([file.removesuffix(".py").replace("/", "."), *parts[:-1]]) + "::" + parts[-1])
        if actual != expected or len(cases) != len(nodes):
            problems.append("wide collection: JUnit does not cover the exact selected obligations")
    except (OSError, ET.ParseError, ValueError, TypeError):
        problems.append("wide collection: JUnit cross-check could not be completed")
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
    if counts.get("nao_executados"):
        problems.append(f"c16.json: {counts.get('nao_executados')} required cases not executed")
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
    require_identity: bool = False,
) -> list[str]:
    """Open every mandatory evidence artifact and report what disagrees."""
    root = Path(artifacts_dir)
    problems: list[str] = []
    if not root.is_dir():
        return [f"artifacts: directory absent at {root} (no evidence was downloaded)"]
    namespaces = {
        "p04-harness": "p04-harness", "wide-suite-linux": "wide-suite-linux",
        "install-eval-linux": "install-smoke", "c16-harness": "c16-harness",
        "build-sdist-wheel": "dist", "c15-tests-linux": "c15-linux-evidence",
        "c15-tests-windows": "c15-windows-evidence",
    }

    def folder(job):
        return root / namespaces[job] if require_identity else root
    if require_identity:
        for job in namespaces:
            problems.extend(check_identity(folder(job), job, expected_sha))
    problems.extend(check_p04_run(folder("p04-harness") / "run.json", expected_sha=expected_sha, mode=p04_mode))
    problems.extend(
        check_junit(folder("wide-suite-linux") / "wide.junit.xml", min_tests=min_wide_tests,
                    label="wide.junit.xml", forbid_skips=require_identity, separate_install_job=True)
    )
    # The installed-artifact smoke is skipif-gated on C15_INSTALL_SMOKE. If that
    # env key is ever dropped from the job, pytest skips and exits 0 and the gap
    # comes back inside its own fix, so this artifact forbids skips.
    problems.extend(
        check_junit(folder("install-eval-linux") / "install-smoke.junit.xml", min_tests=1,
                    label="install-smoke.junit.xml", forbid_skips=True)
    )
    problems.extend(check_c16(folder("c16-harness") / "c16.json", expected_sha=expected_sha))
    if require_identity:
        problems.extend(check_collection(folder("wide-suite-linux"), expected_sha))
        for job, filename in [("c15-tests-linux", "c15-linux.junit.xml"),
                              ("c15-tests-windows", "c15-windows.junit.xml")]:
            problems.extend(check_junit(folder(job) / filename, label=filename, separate_install_job=True))
        problems.extend(check_junit(folder("c16-harness") / "c16.junit.xml", label="c16.junit.xml"))
        for name in ("p04-core-1.junit.xml", "p04-core-2.junit.xml", "p04-extensions.junit.xml"):
            problems.extend(check_junit(folder("p04-harness") / name, label=name))
        p04 = _load_json(folder("p04-harness") / "run.json", problems, "p04 cross-check")
        for record in (p04 or {}).get("runs", []):
            name = record.get("name")
            filename = {"core-1": "p04-core-1.junit.xml", "core-2": "p04-core-2.junit.xml",
                        "extensions": "p04-extensions.junit.xml"}.get(name)
            path = folder("p04-harness") / (filename or "missing")
            if not path.is_file():
                continue
            try:
                cases = list(ET.parse(path).iter("testcase"))
                passed = sum(c.find("failure") is None and c.find("error") is None
                             and c.find("skipped") is None for c in cases)
                if record.get("passed") != passed:
                    problems.append(f"p04 {name}: summary disagrees with JUnit collection")
            except ET.ParseError:
                pass  # Already rejected by check_junit.
        c16 = _load_json(folder("c16-harness") / "c16.json", problems, "c16 exit status")
        if (c16 or {}).get("pytest_exit_code") != 0:
            problems.append("c16: pytest exit code lost or nonzero")
        installed = _load_json(folder("install-eval-linux") / "installed-eval.json", problems, "installed evaluation")
        dist = _load_json(folder("build-sdist-wheel") / "identity.json", problems, "distribution identity")
        if installed is not None:
            if (installed.get("status") != "PASS" or installed.get("tested_commit_sha") != expected_sha
                    or installed.get("run_id") != os.environ.get("GITHUB_RUN_ID")):
                problems.append("installed evaluation status or candidate/run identity differs")
            wheel_hashes = {v for k, v in (dist or {}).get("package_hashes", {}).items() if k.endswith(".whl")}
            if len(wheel_hashes) != 1 or installed.get("wheel_sha256") not in wheel_hashes:
                problems.append("installed evaluation used another wheel")
    return problems


def check_identity(root: Path, job: str, expected_sha: str | None) -> list[str]:
    problems: list[str] = []
    data = _load_json(root / "identity.json", problems, f"{job} identity")
    if data is None:
        return problems
    expected = {
        "schema": "MP-C06-EVIDENCE/1", "job": job,
        "tested_commit_sha": expected_sha,
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    for field, value in expected.items():
        if value is None or data.get(field) != value:
            problems.append(f"{job}: identity mismatch {field}")
    if data.get("source_dirty") is not False or data.get("tracked_source_dirty_after") is not False:
        problems.append(f"{job}: dirty or unrecorded source checkout")
    if data.get("unexpected_untracked_source"):
        problems.append(f"{job}: unexpected untracked source files")
    if len(str(data.get("tree_sha", ""))) != 40:
        problems.append(f"{job}: missing tree SHA")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text(encoding="utf-8")) if event_path else {}
    pr = event.get("pull_request") or {}
    if data.get("event") == "pull_request":
        head, base = (pr.get("head") or {}).get("sha"), (pr.get("base") or {}).get("sha")
        if data.get("pr_head_sha") != head or data.get("base_sha") != base:
            problems.append(f"{job}: wrong PR head/base")
        if data.get("parents") != [base, head]:
            problems.append(f"{job}: tested merge does not have expected base/head parents")
    # Check against this job's independent checkout too, not only self-reported metadata.
    import subprocess
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    if data.get("tree_sha") != tree:
        problems.append(f"{job}: tree differs from aggregator checkout")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        return problems + [f"{job}: no sealed artifact contents"]
    actual = {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*")
              if p.is_file() and p != root / "identity.json"}
    if set(files) != actual:
        problems.append(f"{job}: artifact inventory differs")
    for name, sha in files.items():
        path = root / name
        if root.resolve() not in path.resolve().parents or not path.is_file():
            problems.append(f"{job}: unsafe or absent artifact {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            problems.append(f"{job}: altered artifact {name}")
    if job == "build-sdist-wheel":
        packages = data.get("package_hashes") or {}
        if not any(n.endswith(".whl") for n in packages) or not any(n.endswith(".tar.gz") for n in packages):
            problems.append(f"{job}: wheel/sdist hashes absent")
        if any(files.get(n) != sha for n, sha in packages.items()):
            problems.append(f"{job}: package hashes disagree")
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
    parser.add_argument("--require-identity", action="store_true", help="require isolated, sealed job/run identities")
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
            require_identity=args.require_identity,
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
