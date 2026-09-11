"""Require every mandatory GitHub Actions job result to be success.

Used by the aggregator job (if: always()). Missing, skipped, cancelled,
failure, and empty results are not success. A fast/diagnostic suite cannot
green the PR through this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Mapping


SUCCESS = "success"

# Explicit inventory of blocking jobs on the C18/P04 workflow. A job that
# never ran is not success: the aggregator must see every name.
DEFAULT_REQUIRED_JOBS = (
    "lint",
    "c15-tests-linux",
    "build-sdist-wheel",
    "install-eval-linux",
    "wide-suite-linux",
    "c16-harness",
    "p04-harness",
)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-json", help="JSON object of job_name -> result or GitHub needs")
    parser.add_argument(
        "--required-jobs",
        default="",
        help="comma-separated inventory; missing/unrun names fail. empty = keys of results only",
    )
    args = parser.parse_args(argv)
    if args.results_json:
        payload = json.loads(args.results_json)
    else:
        payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        print("aggregator: results must be a JSON object", file=sys.stderr)
        return 1
    required = [item.strip() for item in args.required_jobs.split(",") if item.strip()] or None
    return evaluate(normalize(payload), required=required)


if __name__ == "__main__":
    raise SystemExit(main())
