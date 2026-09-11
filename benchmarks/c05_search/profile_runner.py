"""Local before/after profile of search_models. Not a speed claim for other hardware."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.optimal_combination import search_models  # noqa: E402


def run(n_vars=3, n=24, seed=0, mode="exact"):
    rng = np.random.RandomState(seed)
    data = {f"x{i}": rng.uniform(1.0, 9.0, n) for i in range(n_vars)}
    data["y"] = 4 * data["x0"] + 10 + rng.normal(0, 0.4, n)
    df = pd.DataFrame(data)
    X = df.drop(columns=["y"])
    columns = {
        c: {
            "original_name": c,
            "role": "predictor",
            "kind": "quantitative",
            "unit": None,
            "group_id": None,
            "categories": None,
            "reference_category": None,
        }
        for c in X.columns
    }
    prepared = {
        "schema_version": "MP/1",
        "X": X,
        "y": df["y"],
        "row_ids": [str(i) for i in df.index],
        "feature_schema": {
            "version": 1,
            "columns": columns,
            "groups": {},
            "target": {"column": "y", "unit": None},
        },
        "encoder_state": {},
        "issues": [],
        "dataset_sha256": "benchmark-profile",
        "base_frame": X.copy(),
    }
    spec = {
        "schema_version": "MP/1",
        "target_col": "y",
        "candidate_cols": None,
        "search_policy": {
            "mode": mode,
            "budget": 500,
            "seed": seed,
            "use_cache": False,
            "n_jobs": 1,
        },
        "evaluation_policy": {"sample_size_rule": "nbr_item2_grau1", "remove_outliers": False},
    }
    result = search_models(prepared, None, spec)
    return {
        "labeled": "local_profile",
        "mode": result["search_audit"]["mode"],
        "possible": result["search_audit"]["possible"],
        "evaluated": result["search_audit"]["evaluated"],
        "profile": result["search_audit"]["profile"],
        "winner_id": (result["winner"] or {}).get("candidate_id"),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
