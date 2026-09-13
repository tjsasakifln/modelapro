"""Shared FrozenProject / subject fixtures for C14.

Labeled as campaign tests of the shipped `modules.valuation_batch.evaluate_batch`.
Peer C02/C03/C04/C06 callables are consumed when importable; otherwise the
frozen-application fallbacks inside valuation_batch.py run. Fixtures never
build a BatchResult themselves.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional

import pytest


SCHEMA = "MP/1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_request_spec(**overrides: Any) -> Dict[str, Any]:
    spec = {
        "schema_version": SCHEMA,
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {
            "preco": "target",
            "area": "predictor",
            "bairro": "predictor",
            "row_id": "identifier",
        },
        "units": {"preco": "BRL", "area": "m2"},
        "import_options": {"locale": "pt-BR", "delimiter": None, "encoding": None},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": ["r30"]},
        "search_policy": {"mode": "exhaustive", "budget": 1000, "objective": "grau_fundamentacao", "seed": 7},
        "evaluation_policy": {"method": "holdout", "partitions": 1, "seed": 7},
        "reference_date": "2024-06-01",
        "inspection_date": "2024-06-15",
        "target_unit": "BRL",
        "applicant": "synthetic-c14",
        "purpose": "batch-test",
    }
    spec.update(overrides)
    return spec


def make_encoder_state() -> Dict[str, Any]:
    return {
        "version": SCHEMA,
        "unknown_category_policy": "unsupported",
        "locale": "pt-BR",
        "missing_policy": {"predictors": "complete_case", "target": "never_impute"},
        "column_order": ["area", "bairro_Sul"],
        "base_variables": [
            {
                "original_name": "area",
                "internal_name": "area",
                "kind": "numeric",
                "locale": "pt-BR",
                "impute_value": None,
            },
            {
                "original_name": "bairro",
                "internal_name": "bairro",
                "kind": "categorical",
                "categories": ["Centro", "Sul"],
                "reference_category": "Centro",
                "indicator_columns": ["bairro_Sul"],
                "indicator_levels": ["Sul"],
                "grouping": {"policy": "none", "mapping": {}},
                "unknown_policy": "unsupported",
            },
        ],
    }


def make_feature_schema() -> Dict[str, Any]:
    return {
        "version": SCHEMA,
        "columns": {
            "area": {
                "original_name": "area",
                "role": "predictor",
                "kind": "numeric",
                "unit": "m2",
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
            "bairro_Sul": {
                "original_name": "bairro",
                "role": "predictor",
                "kind": "categorical",
                "unit": None,
                "group_id": "bairro",
                "categories": ["Centro", "Sul"],
                "reference_category": "Centro",
            },
        },
        "groups": {"bairro": {"columns": ["bairro_Sul"], "base_variable": "bairro"}},
        "target": {"column": "preco", "unit": "BRL"},
    }


def make_model_spec() -> Dict[str, Any]:
    return {
        "candidate_id": "ols_area_bairro",
        "features": ["area", "bairro_Sul"],
        "base_variables": ["area", "bairro"],
        "feature_groups": {"bairro": ["bairro_Sul"]},
        "x_transformations": {"area": "linear"},
        "y_transformation": {"name": "linear"},
        "intercept": True,
    }


def make_model_state() -> Dict[str, Any]:
    # y = 100000 + 2500*area + 20000*(bairro==Sul). Synthetic, identified.
    coefficients = {"const": 100000.0, "area": 2500.0, "bairro_Sul": 20000.0}
    feature_order = ["const", "area", "bairro_Sul"]
    # Diagonally dominant (X'X)^{-1} so mean CI is well-defined and finite.
    xtx_inv = [
        [0.08, -0.0004, -0.01],
        [-0.0004, 0.00002, 0.0],
        [-0.01, 0.0, 0.12],
    ]
    return {
        "coefficients": coefficients,
        "feature_order": feature_order,
        "residual_std": 8000.0,
        "n": 30,
        "k": 2,
        "xtx_inv": xtx_inv,
        "target_transform_state": {"name": "linear", "estimand": "original_unit"},
        "model_sha256": _sha(json.dumps(coefficients, sort_keys=True)),
        "used_row_ids": [f"r{i}" for i in range(1, 31) if i != 30],
        "excluded_row_ids": ["r30"],
        "diagnostics": {
            "item_scores": {1: 2, 2: 3, 3: 2, 5: 3, 6: 3},
            "sample_evidence_status": "declared",
            "pvalues": {"const": 0.001, "area": 0.01, "bairro_Sul": 0.02},
            "f_pvalue": 0.001,
        },
        "pvalues": {"const": 0.001, "area": 0.01, "bairro_Sul": 0.02},
        "f_pvalue": 0.001,
    }


def make_frozen_project(**overrides: Any) -> Dict[str, Any]:
    spec = make_request_spec()
    frozen = {
        "schema_version": SCHEMA,
        "project_id": "proj-c14-synthetic",
        "revision_id": "rev-1",
        "input_sha256": _sha("synthetic-input-c14"),
        "dataset_sha256": _sha("synthetic-dataset-c14"),
        "request_spec": spec,
        "feature_schema": make_feature_schema(),
        "encoder_state": make_encoder_state(),
        "model_spec": make_model_spec(),
        "model_state": make_model_state(),
        "model_scope": "population_model",
        "subject_constraints": {},
        "domain": {
            "kind": "declared",
            "variables": {
                "area": {"min": 50.0, "max": 200.0},
                "bairro": {"allowed_categories": ["Centro", "Sul"]},
            },
        },
        "sample_ledger": {
            "used_row_ids": [f"r{i}" for i in range(1, 30)],
            "excluded_row_ids": ["r30"],
            "exclusion_reasons": {"r30": "reviewed_outlier"},
            "reviewed_exclusions": ["r30"],
            "sample_ranges": {"area": {"min": 60.0, "max": 180.0}},
        },
        "normative_version": "NBR 14653-2:2011",
        "artifact_refs": {"model_state": "revisions/rev-1/model_state.json"},
        "provenance": {
            "code_sha": "c92949e4db8c559c6b02ef58b7df90d6cf01e7ed",
            "synthetic": True,
            "filename": "synthetic_market.csv",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, Mapping) and isinstance(frozen.get(key), dict):
            merged = copy.deepcopy(frozen[key])
            merged.update(value)
            frozen[key] = merged
        else:
            frozen[key] = value
    return frozen


def make_subject(
    subject_id: str,
    area: float,
    bairro: str,
    documentary_items: Optional[List[Dict[str, Any]]] = None,
    *,
    documentary: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    doc: Dict[str, Any]
    if documentary is not None:
        doc = dict(documentary)
        doc.setdefault("subject_id", subject_id)
        doc.setdefault("origin", "subject")
        if documentary_items is not None:
            doc["items"] = list(documentary_items)
        else:
            doc.setdefault("items", list(doc.get("items") or []))
    else:
        doc = {
            "subject_id": subject_id,
            "origin": "subject",
            "items": list(documentary_items or []),
        }
    return {
        "subject_id": subject_id,
        "raw": {"area": area, "bairro": bairro},
        "documentary": doc,
    }


def c03_documentary(subject_id: str, *, item1: int = 2, item3: int = 2) -> Dict[str, Any]:
    """Subject-owned C03 documentary with provenance. Not inherited across imóveis."""
    return {
        "subject_id": subject_id,
        "origin": "subject",
        "item1": {
            "grade": item1,
            "provenance": {"kind": "synthetic-test", "subject_id": subject_id, "rule": "tabela1_item1"},
        },
        "item3": {
            "grade": item3,
            "provenance": {"kind": "synthetic-test", "subject_id": subject_id, "rule": "tabela1_item3"},
        },
        "items": [],
    }


def expected_point(area: float, bairro: str) -> float:
    """Independent linear oracle of the frozen coefficients (not evaluate_batch)."""
    dummy = 1.0 if bairro == "Sul" else 0.0
    return 100000.0 + 2500.0 * float(area) + 20000.0 * dummy


@pytest.fixture
def frozen_population() -> Dict[str, Any]:
    return make_frozen_project()


@pytest.fixture
def request_spec() -> Dict[str, Any]:
    return make_request_spec()
