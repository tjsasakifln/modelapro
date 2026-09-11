#!/usr/bin/env python3
"""C16 acceptance harness.

C17 runs this against a composite SHA:

    python scripts/c16_acceptance/run_harness.py --output c16_summary.json

The process always prints a disjoint summary of aprovados, reprovados and
não executados. Exit code is 0 only when there are zero reprovados and
zero classification violations (skip/xfail). Baseline failures of
production code yield a non-zero exit — that is honest, not a harness bug.
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
CLASSIFICATION_PATH = ROOT / "tests" / "acceptance" / "classification.json"
PYTEST_TARGETS = [
    "tests/test_audit_fixes.py",
    "tests/test_full_flow.py",
    "tests/acceptance/",
]


def git_sha() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return (r.stdout or "").strip() or "UNKNOWN"


def load_rules() -> dict:
    with CLASSIFICATION_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def classify(nodeid: str, rules: dict) -> str:
    blob = nodeid.replace("\\", "/")
    for rule in rules.get("rules", []):
        prefix = rule["prefix"]
        stem = Path(prefix).stem
        dotted = prefix.replace("/", ".").replace(".py", "")
        if prefix in blob or dotted in blob or f".{stem}." in f".{blob}." or f"/{stem}.py" in blob:
            return rule["kind"]
    return rules.get("default_kind", "unit")


def parse_junit(path: Path) -> list[dict]:
    tree = ET.parse(path)
    cases = []
    for case in tree.iter("testcase"):
        nodeid = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        file_attr = case.attrib.get("file", "")
        if file_attr:
            nodeid = f"{file_attr}::{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        status = "passed"
        message = ""
        skipped = case.find("skipped")
        failed = case.find("failure")
        errored = case.find("error")
        if skipped is not None:
            status = "skipped"
            message = (skipped.attrib.get("message") or "") + (skipped.text or "")
            if "xfail" in (skipped.attrib.get("type") or "").lower() or "xfail" in message.lower():
                status = "xfail"
        elif failed is not None:
            status = "failed"
            message = (failed.attrib.get("message") or "") + "\n" + (failed.text or "")
        elif errored is not None:
            status = "error"
            message = (errored.attrib.get("message") or "") + "\n" + (errored.text or "")
        cases.append({
            "nodeid": nodeid,
            "name": case.attrib.get("name"),
            "classname": case.attrib.get("classname"),
            "file": file_attr,
            "time": case.attrib.get("time"),
            "status": status,
            "message": message.strip(),
        })
    return cases


def bucket(case: dict, kind: str) -> str:
    """Return aprovado | reprovado | nao_executado | violacao_a04."""
    status = case["status"]
    msg = case["message"]
    if status in {"skipped", "xfail"}:
        return "violacao_a04"
    if status == "passed":
        return "aprovado"
    combined = msg
    if "UNMET_DEPENDENCY:" in combined or combined.startswith("NOT_RUN") or "NOT_RUN:" in combined:
        return "nao_executado"
    if status in {"failed", "error"}:
        return "reprovado"
    return "reprovado"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C16 independent-oracle harness")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--junit", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument("pytest_args", nargs="*", help="extra args forwarded to pytest")
    args = parser.parse_args(argv)

    sha = args.sha or git_sha()
    if args.junit is not None:
        junit_path = args.junit
    elif os.environ.get("C16_JUNIT"):
        junit_path = Path(os.environ["C16_JUNIT"])
    elif args.output is not None:
        junit_path = args.output.with_suffix(".junit.xml")
    else:
        junit_path = Path.cwd() / "c16_harness_junit.xml"
    junit_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pytest",
        *PYTEST_TARGETS,
        "-q", "--tb=short",
        f"--junitxml={junit_path}",
        *args.pytest_args,
    ]
    proc = subprocess.run(cmd, cwd=ROOT)
    rules = load_rules()
    cases = parse_junit(junit_path) if junit_path.exists() else []

    summary = {
        "campaign_id": "C16",
        "contract_version": "MP/1",
        "sha": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pytest_command": cmd,
        "pytest_exit_code": proc.returncode,
        "aprovados": [],
        "reprovados": [],
        "nao_executados": [],
        "violacoes_a04": [],
        "counts": {},
        "kinds": {"unit": 0, "e2e": 0, "contract-sim": 0},
        "e2e_unlabeled_simulator_pass": [],
    }
    for case in cases:
        kind = classify(case["nodeid"] + " " + (case.get("file") or "") + " " + (case.get("classname") or ""), rules)
        case["kind"] = kind
        summary["kinds"][kind] = summary["kinds"].get(kind, 0) + 1
        dest = bucket(case, kind)
        record = {
            "id": case["name"] or case["nodeid"],
            "nodeid": case["nodeid"],
            "kind": kind,
            "status": case["status"],
            "message": case["message"][:800],
        }
        if dest == "aprovado":
            summary["aprovados"].append(record)
            if kind == "contract-sim":
                # labeled — allowed. unlabeled simulator would be a defect.
                pass
        elif dest == "nao_executado":
            summary["nao_executados"].append(record)
        elif dest == "violacao_a04":
            summary["violacoes_a04"].append(record)
        else:
            summary["reprovados"].append(record)

    summary["counts"] = {
        "aprovados": len(summary["aprovados"]),
        "reprovados": len(summary["reprovados"]),
        "nao_executados": len(summary["nao_executados"]),
        "violacoes_a04_skip_xfail": len(summary["violacoes_a04"]),
        "total": len(cases),
    }
    ids = (
        {r["id"] for r in summary["aprovados"]}
        | {r["id"] for r in summary["reprovados"]}
        | {r["id"] for r in summary["nao_executados"]}
        | {r["id"] for r in summary["violacoes_a04"]}
    )
    summary["counts"]["disjoint"] = len(ids) == len(cases)

    text = [
        f"C16 harness sha={sha}",
        f"aprovados={summary['counts']['aprovados']}",
        f"reprovados={summary['counts']['reprovados']}",
        f"nao_executados={summary['counts']['nao_executados']}",
        f"violacoes_a04_skip_xfail={summary['counts']['violacoes_a04_skip_xfail']}",
        f"total={summary['counts']['total']} disjoint={summary['counts']['disjoint']}",
        f"pytest_exit={proc.returncode}",
        "ids:",
    ]
    for label, bucket_name in (
        ("APROVADO", "aprovados"),
        ("REPROVADO", "reprovados"),
        ("NAO_EXECUTADO", "nao_executados"),
        ("A04_SKIP_XFAIL", "violacoes_a04"),
    ):
        for rec in summary[bucket_name]:
            text.append(f"  {label} [{rec['kind']}] {rec['id']}")
    report = "\n".join(text)
    print(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.output}")

    if summary["violacoes_a04"] or not summary["counts"]["disjoint"]:
        return 2
    if summary["reprovados"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
