"""Shared helpers for C05 tests. Not production."""
import numpy as np
import pandas as pd


_UNSET = object()


def make_prepared(df: pd.DataFrame, target: str, groups=None, kinds=None):
    X = df.drop(columns=[target])
    columns = {}
    kinds = kinds or {}
    for c in X.columns:
        columns[c] = {
            "original_name": c,
            "role": "predictor",
            "kind": kinds.get(c, "quantitative"),
            "unit": None,
            "group_id": None,
            "categories": None,
            "reference_category": None,
        }
    groups = groups or {}
    for gid, gmeta in groups.items():
        for col in gmeta.get("columns") or []:
            if col in columns:
                columns[col]["kind"] = "indicator"
                columns[col]["group_id"] = gid
    return {
        "schema_version": "MP/1",
        "X": X,
        "y": df[target],
        "row_ids": [str(i) for i in df.index],
        "feature_schema": {
            "version": 1,
            "columns": columns,
            "groups": groups,
            "target": {"column": target, "unit": "BRL"},
        },
        "encoder_state": {},
        "sample_ledger": {},
        "issues": [],
        "dataset_sha256": "test-synthetic",
        "base_frame": X.copy(),
    }


def request_spec(
    target,
    candidate_cols=_UNSET,
    search_policy=None,
    evaluation_policy=None,
    roles=None,
):
    spec = {
        "schema_version": "MP/1",
        "target_col": target,
        "roles": roles or {},
        "units": {},
        "search_policy": {
            "mode": "exact",
            "budget": 10_000,
            "objective": "original_scale_error",
            "seed": 0,
            "use_cache": False,
            "n_jobs": 1,
            "max_alternatives": 5,
            **(search_policy or {}),
        },
        "evaluation_policy": {
            "sample_size_rule": "nbr_item2_grau1",
            "remove_outliers": False,
            "seed": 0,
            **(evaluation_policy or {}),
        },
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"action": "report_only"},
    }
    if candidate_cols is not _UNSET:
        spec["candidate_cols"] = candidate_cols
    return spec


def positive_frame(n=30, n_vars=2, seed=0):
    rng = np.random.RandomState(seed)
    data = {}
    for i in range(n_vars):
        data[f"x{i+1}"] = rng.uniform(1.0, 10.0, n)
    data["y"] = 100 + 3 * data["x1"] + rng.normal(0, 0.4, n)
    return pd.DataFrame(data)
