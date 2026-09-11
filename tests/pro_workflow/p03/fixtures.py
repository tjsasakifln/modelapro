"""Synthetic presentation fixtures for P03. Identified as synthetic — not P01 integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from tests.c08_report.fixtures import (
    KNOWN_POINT,
    KNOWN_UNIT,
    known_context,
    known_snapshot,
    long_table_context,
    long_table_snapshot,
)

SYNTHETIC_LABEL = "synthetic P03 presentation fixture — not P01 integration and not client data"

KNOWN_POINT_STORAGE = "350000"


def _mark_synthetic(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = deepcopy(payload)
    payload["synthetic"] = True
    payload["fixture_synthetic"] = True
    payload["synthetic_label"] = SYNTHETIC_LABEL
    return payload


def snapshot_with_audit(*, approximate: bool = False, **overrides: Any) -> Dict[str, Any]:
    """C10-shaped search: audit only, no top-level mode/exhaustive."""
    snap = known_snapshot()
    if approximate:
        snap["search"] = {
            "audit": {
                "possible": 80,
                "generated": 80,
                "evaluated": 12,
                "rejected": 4,
                "coverage": {
                    "enumeration": "partial",
                    "ranking_objective": "partial",
                    "exact_optimum_guaranteed": False,
                },
                "budget": {"max_evaluations": 12, "used": 12},
                "mode": "heuristic",
                "objective": {"name": "aic"},
            },
            "winner_candidate_id": "area:identity|y:identity|int:1",
        }
    else:
        snap["search"] = {
            "audit": {
                "possible": 12,
                "generated": 12,
                "evaluated": 12,
                "rejected": 0,
                "coverage": {
                    "enumeration": "exhaustive",
                    "ranking_objective": "full",
                    "exact_optimum_guaranteed": True,
                },
                "budget": {"max_evaluations": 16, "used": 12},
                "mode": "exact",
                "objective": {"name": "aic"},
            },
            "winner_candidate_id": "area:identity|y:identity|int:1",
        }
    snap.update(overrides)
    snap["synthetic_label"] = SYNTHETIC_LABEL
    return snap


def snapshot_without_formula() -> Dict[str, Any]:
    snap = known_snapshot()
    snap["model"] = dict(snap["model"])
    snap["model"]["formula"] = ""
    snap["model"]["y_transformation"] = "identity"
    snap["synthetic_label"] = SYNTHETIC_LABEL
    return snap


def snapshot_log_scale() -> Dict[str, Any]:
    snap = known_snapshot()
    snap["model"] = dict(snap["model"])
    snap["model"]["formula"] = ""
    snap["model"]["y_transformation"] = "log"
    snap["model"]["coefficients"] = {"const": 10.5, "area": 0.008}
    snap["target"] = dict(snap["target"])
    snap["target"]["estimand"] = "média condicional na unidade original (retransformação pelo produtor)"
    snap["synthetic_label"] = SYNTHETIC_LABEL
    return snap


def aligned_series_context(*, n: int = 30, scale: str = "original", unit: str = "BRL") -> Dict[str, Any]:
    ctx = _mark_synthetic(known_context(n_used=n, n_excluded=6 if n >= 6 else 0))
    ids = [f"used-{i:04d}" for i in range(1, n + 1)]
    ctx["fitted_values"] = [float(200000 + 1000 * i) for i in range(n)]
    ctx["residuals"] = [float((i % 5) - 2) * 500 for i in range(n)]
    ctx["observed_values"] = [a + b for a, b in zip(ctx["fitted_values"], ctx["residuals"])]
    ctx["series_row_ids"] = ids
    ctx["series_scale"] = scale
    ctx["series_unit"] = unit
    ctx["used_rows"] = known_context(n_used=n, n_excluded=0)["used_rows"]
    return ctx


def shifted_series_context(n: int = 30) -> Dict[str, Any]:
    ctx = aligned_series_context(n=n)
    ids = list(ctx["series_row_ids"])
    ctx["series_row_ids"] = ids[1:] + [f"used-{n + 1:04d}"]
    return ctx


def length_mismatch_series_context(n: int = 30) -> Dict[str, Any]:
    ctx = aligned_series_context(n=n)
    ctx["fitted_values"] = ctx["fitted_values"][:-1]
    return ctx


def missing_series_context() -> Dict[str, Any]:
    ctx = _mark_synthetic(known_context())
    ctx.pop("fitted_values", None)
    ctx.pop("residuals", None)
    return ctx


def workflow_context_snapshot(*, with_unit: bool = True, docs_pending: bool = True) -> Dict[str, Any]:
    snap = known_snapshot()
    snap["target"] = dict(snap["target"])
    if not with_unit:
        snap["target"]["unit"] = ""
    snap["validation"] = dict(snap["validation"])
    snap["validation"]["fundamentacao"] = dict(snap["validation"]["fundamentacao"])
    snap["validation"]["fundamentacao"]["items"] = [
        {
            "item": 1,
            "id": "tabela1.item1",
            "description": "Caracterização do imóvel avaliando",
            "grade": None,
            "evidence_status": "pending",
            "detail": "Item 1 documental não informado",
        }
    ]
    if docs_pending:
        snap["validation"]["documentary"] = {
            "item1": {"evidence_status": "pending", "detail": "não comprovado"},
            "item3": {"evidence_status": "pending", "detail": "não comprovado"},
        }
    snap["provenance"] = {
        "workflow_context": {
            "schema_version": "MP-PRO/1",
            "subject_raw": {"area": 120.0, "quartos": 3},
            "requested_minimum_grade": 2,
            "grade_requirement_status": "not_met",
            "selection_scope": "subject_specific",
            "selection_conditioned_on_subject": True,
            "limitation_codes": [],
            "evaluation_policy": {"method": "none", "partitions": None, "groups": None, "seed": 17},
        }
    }
    snap["synthetic_label"] = SYNTHETIC_LABEL
    return snap


def old_mp1_snapshot() -> Dict[str, Any]:
    """BASE_SHA-era MP/1 snapshot without MP-PRO/1 extension keys."""
    snap = known_snapshot()
    snap.pop("workflow_context", None)
    snap["provenance"] = {
        "model_id": snap["model"]["model_id"],
        "code_sha": snap["code_sha"],
    }
    snap["synthetic_label"] = SYNTHETIC_LABEL
    return snap


def feature_schema_area_quartos() -> Dict[str, Any]:
    return {
        "version": 1,
        "columns": {
            "area": {
                "original_name": "area",
                "role": "predictor",
                "kind": "numeric",
                "unit": "m2",
            },
            "quartos": {
                "original_name": "quartos",
                "role": "predictor",
                "kind": "numeric",
                "unit": None,
            },
        },
        "groups": {},
        "target": {"column": "preco", "unit": "BRL"},
    }


def long_rows_with_values() -> tuple[Dict[str, Any], Dict[str, Any]]:
    snap = long_table_snapshot()
    ctx = long_table_context()
    ctx["synthetic"] = True
    ctx["fixture_synthetic"] = True
    ctx["synthetic_label"] = SYNTHETIC_LABEL
    return snap, ctx
