#!/usr/bin/env python3
"""Fresh consumer of the shipped C04 API. Not a pytest reimplementation of the unit.

Exits 0 only if fit_candidate + evaluate_fitted return a fitted model with a
finite point estimate and non-empty used_row_ids.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.model_builder import evaluate_fitted, fit_candidate  # noqa: E402


def main() -> int:
    rng = np.random.default_rng(20260911)
    n = 30
    area = np.linspace(20.0, 80.0, n)
    y = 200.0 + 15.0 * area + rng.normal(0.0, 5.0, n)
    prepared = {
        "X": pd.DataFrame({"area": area}),
        "y": pd.Series(y, name="preco"),
        "row_ids": [f"r{i}" for i in range(n)],
        "feature_schema": {
            "version": 1,
            "columns": {
                "area": {
                    "original_name": "area",
                    "role": "predictor",
                    "kind": "numeric",
                    "unit": None,
                    "group_id": None,
                    "categories": None,
                    "reference_category": None,
                }
            },
            "groups": {},
            "target": {"column": "preco", "unit": None},
        },
        "encoder_state": {},
        "base_frame": pd.DataFrame({"area": area}),
        "issues": [],
        "dataset_sha256": "consumer",
    }
    spec = {
        "candidate_id": "consumer-area",
        "features": ["area"],
        "base_variables": ["area"],
        "feature_groups": {},
        "x_transformations": {},
        "y_transformation": "identity",
        "intercept": True,
    }
    request = {"schema_version": "MP/1", "outlier_policy": {"mode": "report_only", "scenario": "principal"}}
    fit = fit_candidate(prepared, spec, request)
    if fit.status != "fitted":
        print("FAIL status", fit.status, fit.issues)
        return 1
    if not fit.used_row_ids:
        print("FAIL empty used_row_ids")
        return 1
    assessment = evaluate_fitted(
        fit,
        {
            "subject_id": "consumer-subject",
            "raw_values": {"area": 40.0},
            "X": pd.DataFrame([{"area": 40.0}]),
            "supported": True,
        },
        request,
    )
    point = assessment.value["point"]
    if point is None or not np.isfinite(point):
        print("FAIL point", point, assessment.issues)
        return 1
    print("OK status", fit.status, "point", point, "n", len(fit.used_row_ids), "sha", fit.model_sha256[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
