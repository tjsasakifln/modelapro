"""Contract fixtures for C04. Labeled stand-ins for C02 PreparedDataset.

These are NOT evidence of real C02/C03/C06 integration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.model_builder import CandidateSpec

SEED = 20260911


def make_prepared_dataset(X, y, row_ids=None, **extra):
    """CONTRACT FIXTURE (labeled): C02 PreparedDataset stand-in."""
    X = pd.DataFrame(X).copy()
    y = pd.Series(y).copy()
    if row_ids is None:
        row_ids = [f"r{i}" for i in range(len(X))]
    row_ids = list(row_ids)
    schema = extra.get("feature_schema") or {
        "version": 1,
        "columns": {
            str(col): {
                "original_name": str(col),
                "role": "predictor",
                "kind": "numeric",
                "unit": None,
                "group_id": None,
                "categories": None,
                "reference_category": None,
            }
            for col in X.columns
        },
        "groups": extra.get("groups") or {},
        "target": {"column": str(y.name or "y"), "unit": extra.get("target_unit")},
    }
    return {
        "schema_version": "MP/1",
        "X": X.reset_index(drop=True),
        "y": pd.Series(np.asarray(y), name=y.name or "y"),
        "row_ids": row_ids,
        "feature_schema": schema,
        "encoder_state": extra.get("encoder_state") or {"contract_fixture": True, "fitted_on": list(row_ids)},
        "sample_ledger": extra.get("sample_ledger") or {},
        "issues": [],
        "dataset_sha256": extra.get("dataset_sha256") or "contract-fixture",
        "base_frame": extra.get("base_frame", X.reset_index(drop=True).copy()),
        "contract_fixture": True,
        "contract_fixture_for": "C02",
    }


def make_spec(candidate_id, features, intercept=True, **kwargs):
    return CandidateSpec(
        candidate_id=candidate_id,
        features=list(features),
        base_variables=list(kwargs.get("base_variables") or features),
        feature_groups=dict(kwargs.get("feature_groups") or {}),
        x_transformations=dict(kwargs.get("x_transformations") or {}),
        y_transformation=kwargs.get("y_transformation"),
        intercept=intercept,
    )


def make_request(**kwargs):
    spec = {
        "schema_version": "MP/1",
        "target_col": kwargs.get("target_col", "y"),
        "candidate_cols": kwargs.get("candidate_cols"),
        "roles": kwargs.get("roles") or {},
        "units": kwargs.get("units") or {},
        "import_options": {"locale": "auto", "delimiter": None, "encoding": None},
        "missing_policy": kwargs.get("missing_policy") or {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": kwargs.get("outlier_policy") or {"mode": "report_only", "scenario": "principal"},
        "search_policy": kwargs.get("search_policy") or {},
        "evaluation_policy": kwargs.get("evaluation_policy") or {},
        "reference_date": None,
        "inspection_date": None,
        "target_unit": kwargs.get("target_unit"),
        "applicant": "contract-fixture",
        "purpose": "C04-test",
    }
    spec.update({k: v for k, v in kwargs.items() if k not in spec})
    spec["outlier_policy"] = kwargs.get("outlier_policy") or spec["outlier_policy"]
    return spec


def linear_market(n=40, seed=SEED, extra_influence=False):
    rng = np.random.default_rng(seed)
    x1 = np.linspace(10.0, 50.0, n)
    x2 = np.linspace(1.0, 5.0, n) + rng.normal(0.0, 0.05, n)
    y = 1000.0 + 80.0 * x1 + 15.0 * x2 + rng.normal(0.0, 8.0, n)
    if extra_influence:
        x1 = np.append(x1, 400.0)
        x2 = np.append(x2, 2.0)
        y = np.append(y, 50.0)
    X = pd.DataFrame({"area": x1, "quartos": x2})
    y = pd.Series(y, name="preco")
    row_ids = [f"r{i}" for i in range(len(X))]
    return X, y, row_ids


@pytest.fixture
def principal_request():
    return make_request()
