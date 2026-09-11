#!/usr/bin/env python3
"""Before/after measurement protocol for the same synthetic cases.

Fields are kept distinct. Robot clicks are never converted into evaluator hours.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


FORBIDDEN_CLAIM_TOKENS = (
    "economia de horas",
    "hours saved",
    "produtividade humana medida",
    "avaliador-hora",
    "human-hour savings",
)


def empty_metrics(*, phase: str, sha: str) -> dict:
    return {
        "phase": phase,
        "sha": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "human_pilot_executed": False,
        "human_active_time_s": None,
        "cases": [],
        "claims_policy": (
            "compute_time_s is machine wall time. "
            "automated_navigation_time_s and automated_actions count scripted steps. "
            "human_active_time_s is null until an authorized professional pilot runs. "
            "Do not present robot clicks as evaluator-hour savings."
        ),
    }


def record_case(metrics: dict, *, case_id: str, compute_time_s: float, actions: dict | None = None, nav_s=None) -> None:
    metrics["cases"].append(
        {
            "id": case_id,
            "compute_time_s": float(compute_time_s),
            "automated_navigation_time_s": nav_s,
            "automated_actions": actions
            or {"clicks": 0, "retyped_fields": 0, "editorial_corrections": 0},
            "human_active_time_s": None,
        }
    )


def assert_no_human_hour_claims(text: str) -> None:
    lowered = text.lower()
    for token in FORBIDDEN_CLAIM_TOKENS:
        if token in lowered:
            raise SystemExit(f"forbidden productivity claim: {token!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-json", type=Path, default=None, help="optional runner run.json to attach timings")
    args = parser.parse_args(argv)
    metrics = empty_metrics(phase=args.phase, sha=args.sha)
    if args.run_json and args.run_json.is_file():
        payload = json.loads(args.run_json.read_text(encoding="utf-8"))
        for run in payload.get("runs") or []:
            record_case(
                metrics,
                case_id=run.get("name") or "run",
                compute_time_s=0.0,
                actions={
                    "clicks": 0,
                    "retyped_fields": 0,
                    "editorial_corrections": 0,
                    "pytest_returncode": run.get("returncode"),
                },
            )
        metrics["runner_sha"] = payload.get("sha")
        metrics["runner_exit"] = payload.get("exit_code")
    blob = json.dumps(metrics, ensure_ascii=False)
    assert_no_human_hour_claims(blob)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
