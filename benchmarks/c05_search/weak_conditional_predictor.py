"""Benchmark: a marginally weak predictor that is conditionally material.

This is a synthetic, labeled case. It is not a speed claim for other machines.
Run via tests/c05_search/test_a04_heuristic_diversity.py or:

    python3 benchmarks/c05_search/weak_conditional_predictor.py
"""
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
from modules.search_space import parse_feature_name  # noqa: E402


def build_frame(seed=21, n=80):
    rng = np.random.RandomState(seed)
    s = rng.normal(0.0, 1.0, n)
    c = rng.normal(0.0, 1.0, n)
    y = 8 * s + 3.0 * s * c + rng.normal(0, 0.3, n)
    x_signal = s - s.min() + 1.0
    x_cond = c - c.min() + 1.0
    y_std = (y - y.mean()) / (y.std() + 1e-9)
    data = {"x_signal": x_signal, "x_cond": x_cond}
    for i in range(10):
        raw = 0.75 * y_std + 0.25 * rng.normal(0, 1.0, n)
        data[f"noise{i}"] = raw - raw.min() + 0.5
    data["y"] = y
    return pd.DataFrame(data)


def run(seed=21):
    df = build_frame(seed=seed)
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
        "sample_ledger": {},
        "issues": [],
        "dataset_sha256": "benchmark-synthetic-weak-conditional",
        "base_frame": X.copy(),
    }
    spec = {
        "schema_version": "MP/1",
        "target_col": "y",
        "candidate_cols": None,
        "roles": {c: "predictor" for c in X.columns},
        "search_policy": {
            "mode": "approximate",
            "budget": 80,
            "seed": seed,
            "max_variables": 12,
            "use_cache": False,
            "objective": "original_scale_error",
        },
        "evaluation_policy": {"sample_size_rule": None, "remove_outliers": False},
    }
    result = search_models(prepared, None, spec)
    bases = set()
    pair = False
    for entry in result["search_audit"]["history"]:
        b = {parse_feature_name(c)[1] for c in entry.get("variables") or []}
        bases |= b
        if b >= {"x_signal", "x_cond"}:
            pair = True
    out = {
        "labeled": "synthetic_benchmark",
        "possible": result["search_audit"]["possible"],
        "evaluated": result["search_audit"]["evaluated"],
        "exact_optimum_guaranteed": result["search_audit"]["coverage"]["exact_optimum_guaranteed"],
        "x_cond_covered": "x_cond" in bases,
        "conditional_pair_generated": pair,
        "winner_id": (result["winner"] or {}).get("candidate_id"),
        "profile": result["search_audit"]["profile"],
    }
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
