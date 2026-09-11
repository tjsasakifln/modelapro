"""C07 cost/limits of evaluate_procedure on a small synthetic sample.

This is not a client dataset. It records elapsed time, partition count,
budget, and fast vs full mode so enablement of stability stays transparent.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "c07_validation"
for path in (ROOT, FIXTURES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from modules.model_evaluation import evaluate_procedure  # noqa: E402
from contract_fixtures import (  # noqa: E402
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
    synthetic_signal_rows,
)


def _run(mode: str) -> dict:
    bundle = make_input_bundle(synthetic_signal_rows(28, seed=1), input_sha256="synthetic-c07-bench")
    spec = make_request_spec(
        evaluation_policy={
            "method": "random",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": mode,
            "stability": True,
            "budget": {
                "pipeline_bootstrap_replicates": 3 if mode == "fast" else 8,
                "fixed_model_perturbations": 3 if mode == "fast" else 5,
            },
        }
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    t0 = time.perf_counter()
    result = evaluate_procedure(bundle, spec, fit, 5)
    elapsed = time.perf_counter() - t0
    provenance = result["procedure_provenance"]
    stability = result.get("stability") or {}
    return {
        "synthetic": True,
        "mode": mode,
        "elapsed_seconds": round(elapsed, 6),
        "n_folds": result["partition"]["n_splits"],
        "n_reserved": result["metrics"]["n_reserved"],
        "budget": provenance.get("budget"),
        "executed_steps": [item["step"] for item in provenance.get("executed") or []],
        "stability_executed_analyses": list(stability.get("executed_analyses") or []),
        "stability_skipped": list(stability.get("skipped_analyses") or []),
        "cost": provenance.get("cost"),
        "stability_cost": stability.get("cost"),
        "status": result.get("status"),
    }


def main() -> int:
    payload = {
        "schema_version": "MP/1",
        "kind": "c07_cost_benchmark",
        "note": "Synthetic identified sample. Not a client dataset.",
        "fast": _run("fast"),
        "full": _run("full"),
    }
    out_dir = Path(__file__).resolve().parent
    out_path = out_dir / "cost_limits.json"
    out_path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
