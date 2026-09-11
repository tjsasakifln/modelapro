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


def evaluate(results: Mapping[str, str]) -> int:
    if not results:
        print("aggregator: no required jobs declared", file=sys.stderr)
        return 1
    bad = {name: status for name, status in results.items() if status != SUCCESS}
    if bad:
        print("aggregator: required jobs not success:", json.dumps(bad, sort_keys=True), file=sys.stderr)
        return 1
    print("aggregator: all required jobs succeeded:", json.dumps(dict(results), sort_keys=True))
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
    args = parser.parse_args(argv)
    if args.results_json:
        payload = json.loads(args.results_json)
    else:
        payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        print("aggregator: results must be a JSON object", file=sys.stderr)
        return 1
    return evaluate(normalize(payload))


if __name__ == "__main__":
    raise SystemExit(main())
