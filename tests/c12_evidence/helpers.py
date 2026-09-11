"""Labeled synthetic MP/1 fixtures for C12 tests.

These mappings stand in for unpublished C01/C02/C10 peers. They are not
production simulators and must not be treated as live pipeline evidence.
Every dataset here is synthetic.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple


SYNTHETIC_LABEL = "SYNTHETIC_FIXTURE_C12_NOT_PRODUCTION"

# Generating process used by the (simulated) evaluation — not a reimplementation
# of the C12 packager. C12 reconstructs from packaged coefficients.
CONST = 20000.0
COEF_AREA = 1000.0
COEF_QUARTOS = 5000.0
SUBJECT_AREA = 80.0
SUBJECT_QUARTOS = 2.0
STD_ERROR = 100.0
T_CRIT = 1.2815515655446004  # declared by the evaluation (80% two-sided, large df)
XTX_INV = [
    [0.01, 0.0, 0.0],
    [0.0, 0.0001, 0.0],
    [0.0, 0.0, 0.01],
]
FORMULA_CELL = "=CMD|'/c calc'!A0"


def evaluation_point() -> float:
    return CONST + COEF_AREA * SUBJECT_AREA + COEF_QUARTOS * SUBJECT_QUARTOS


def evaluation_intervals() -> Tuple[Dict[str, float], Dict[str, float]]:
    x0 = [1.0, SUBJECT_AREA, SUBJECT_QUARTOS]
    lev = (
        x0[0] * XTX_INV[0][0] * x0[0]
        + x0[1] * XTX_INV[1][1] * x0[1]
        + x0[2] * XTX_INV[2][2] * x0[2]
    )
    se_mean = STD_ERROR * math.sqrt(lev)
    se_pred = STD_ERROR * math.sqrt(1.0 + lev)
    point = evaluation_point()
    mean_ci80 = {"lower": point - T_CRIT * se_mean, "upper": point + T_CRIT * se_mean}
    pred = {"lower": point - T_CRIT * se_pred, "upper": point + T_CRIT * se_pred}
    return mean_ci80, pred


def make_complete_evaluation(n: int = 220, n_excluded: int = 10) -> Dict[str, Any]:
    if n <= 200:
        raise ValueError("C12-A01 fixture must have more than 200 records")
    if n_excluded < 0 or n_excluded >= n:
        raise ValueError("n_excluded out of range")
    n_used = n - n_excluded
    rows: List[Dict[str, Any]] = []
    used_ids: List[str] = []
    excluded_ids: List[str] = []
    sample_ledger: List[Dict[str, Any]] = []
    for i in range(n):
        row_id = f"R{i:04d}"
        area = 50.0 + i * 0.5
        quartos = 1 + (i % 4)
        preco = CONST + COEF_AREA * area + COEF_QUARTOS * quartos
        rec = {
            "row_id": row_id,
            "area": area,
            "quartos": quartos,
            "preco": preco,
            "endereco": f"Rua Sintetica {i}",
            "fonte": "fixture-synthetic",
            "observacao": FORMULA_CELL if i == 0 else "ok",
        }
        rows.append(rec)
        if i < n_used:
            used_ids.append(row_id)
            sample_ledger.append(
                {
                    "row_id": row_id,
                    "disposition": "used",
                    "observed_target": True,
                    "reasons": [],
                }
            )
        else:
            excluded_ids.append(row_id)
            sample_ledger.append(
                {
                    "row_id": row_id,
                    "disposition": "excluded",
                    "observed_target": True,
                    "reasons": ["reviewed_exclusion: outlier_policy"],
                }
            )

    mean_ci80, pred = evaluation_intervals()
    point = evaluation_point()
    request_spec = {
        "schema_version": "MP/1",
        "target_col": "preco",
        "candidate_cols": ["area", "quartos"],
        "roles": {
            "preco": "target",
            "area": "predictor",
            "quartos": "predictor",
            "endereco": "identifier",
            "fonte": "source",
            "observacao": "excluded",
            "row_id": "identifier",
        },
        "units": {"preco": "BRL", "area": "m2", "quartos": "count"},
        "import_options": {"locale": "pt-BR", "delimiter": ",", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": list(excluded_ids)},
        "search_policy": {"mode": "exhaustive", "budget": 1000, "objective": "grau_fundamentacao", "seed": 12},
        "evaluation_policy": {"method": "holdout", "partitions": 1, "seed": 12},
        "reference_date": "2024-01-15",
        "inspection_date": "2024-01-20",
        "target_unit": "BRL",
        "applicant": "synthetic-applicant",
        "purpose": "C12 contract fixture",
    }
    feature_schema = {
        "version": "MP/1",
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
            "quartos": {
                "original_name": "quartos",
                "role": "predictor",
                "kind": "numeric",
                "unit": "count",
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
        },
        "groups": {},
        "target": {"column": "preco", "unit": "BRL"},
    }
    encoder_state = {
        "kind": "declarative_v1",
        "imputations": {},
        "one_hot": {},
        "label": SYNTHETIC_LABEL,
    }
    snapshot = {
        "schema_version": "MP/1",
        "job_id": "job-c12-synthetic",
        "project_id": "proj-c12-synthetic",
        "input_sha256": "a" * 64,
        "code_sha": "b" * 40,
        "reference_date": "2024-01-15",
        "generated_at": "2024-01-21T12:00:00+00:00",
        "target": {"column": "preco", "unit": "BRL", "estimand": "mean_response"},
        "value": {
            "point": point,
            "mean_ci80": mean_ci80,
            "prediction_interval": pred,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": n,
            "observed_target": n,
            "prepared": n,
            "used": n_used,
            "excluded": n_excluded,
            "used_row_ids": list(used_ids),
            "excluded_row_ids": list(excluded_ids),
        },
        "validation": {
            "fundamentacao": {"grade": 2, "points": 8, "items": []},
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 10.0},
            "statistical": {},
            "documentary": {"sources": [{"id": "src-synthetic", "status": "declared"}]},
            "issuance": {"status": "draft", "reasons": ["synthetic fixture"]},
        },
        "issues": [],
        "model": {
            "candidate_id": "ols-linear-area-quartos",
            "coefficients": {"const": CONST, "area": COEF_AREA, "quartos": COEF_QUARTOS},
            "x_transformations": {"area": "linear", "quartos": "linear"},
            "y_transformation": {"name": "linear"},
            "intercept": True,
            "features": ["area", "quartos"],
        },
        "search": {"mode": "exhaustive", "evaluated": 1},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"fixture": SYNTHETIC_LABEL},
    }
    input_bundle = {
        "schema_version": "MP/1",
        "raw_frame": [dict(r) for r in rows],
        "parsed_frame": [dict(r) for r in rows],
        "column_map": {k: k for k in rows[0].keys()},
        "row_ledger": sample_ledger,
        "input_sha256": snapshot["input_sha256"],
        "issues": [],
        "request_spec": request_spec,
        "label": SYNTHETIC_LABEL,
    }
    prepared_dataset = {
        "X": [{"area": r["area"], "quartos": r["quartos"]} for r in rows[:n_used]],
        "y": [r["preco"] for r in rows[:n_used]],
        "row_ids": list(used_ids),
        "excluded_row_ids": list(excluded_ids),
        "feature_schema": feature_schema,
        "encoder_state": encoder_state,
        "sample_ledger": sample_ledger,
        "issues": [],
        "dataset_sha256": "c" * 64,
        "base_frame": [
            {"row_id": r["row_id"], "area": r["area"], "quartos": r["quartos"], "preco": r["preco"]}
            for r in rows[:n_used]
        ],
        "label": SYNTHETIC_LABEL,
    }
    artifacts = {
        "request_spec": request_spec,
        "coefficients": {"const": CONST, "area": COEF_AREA, "quartos": COEF_QUARTOS},
        "y_transformation": {"name": "linear"},
        "x_transformations": {"area": "linear", "quartos": "linear"},
        "subject_design": {
            "X": {"const": 1.0, "area": SUBJECT_AREA, "quartos": SUBJECT_QUARTOS},
            "raw_values": {"area": SUBJECT_AREA, "quartos": SUBJECT_QUARTOS},
            "supported": True,
        },
        "residual_context": {
            "interval_method": "ols_mean_and_prediction",
            "interval_scale": "original",
            "t_crit": T_CRIT,
            "std_error": STD_ERROR,
            "subject_x": [1.0, SUBJECT_AREA, SUBJECT_QUARTOS],
            "xtx_inv": XTX_INV,
        },
        "report_pdf": {
            "bytes": b"%PDF-1.4 synthetic C12 report (not a substitute for tables)\n",
            "filename": "report.pdf",
            "type": "application/pdf",
            "function": "c08_report_pdf",
        },
        "label": SYNTHETIC_LABEL,
    }
    return {
        "snapshot": snapshot,
        "input_bundle": input_bundle,
        "prepared_dataset": prepared_dataset,
        "artifacts": artifacts,
        "label": SYNTHETIC_LABEL,
        "n": n,
        "n_used": n_used,
        "n_excluded": n_excluded,
        "used_ids": used_ids,
        "excluded_ids": excluded_ids,
        "point": point,
        "mean_ci80": mean_ci80,
        "prediction_interval": pred,
        "formula_cell": FORMULA_CELL,
    }


def make_legacy_formula_only() -> Dict[str, Any]:
    """Legacy evaluation that only kept a 4-decimal display formula."""
    point = evaluation_point()
    snapshot = {
        "schema_version": "MP/1",
        "job_id": "job-legacy",
        "project_id": None,
        "input_sha256": None,
        "code_sha": None,
        "reference_date": None,
        "generated_at": "2020-01-01T00:00:00+00:00",
        "target": {"column": "preco", "unit": "BRL", "estimand": "mean_response"},
        "value": {
            "point": point,
            "mean_ci80": None,
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": 30,
            "observed_target": 30,
            "prepared": 30,
            "used": 30,
            "excluded": 0,
            "used_row_ids": [f"L{i:02d}" for i in range(30)],
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
            "statistical": {},
            "documentary": {},
            "issuance": {"status": "draft", "reasons": ["legacy"]},
        },
        "issues": [],
        "model": {"formula": "y = 20000.0000 + 1000.0000*area + 5000.0000*quartos"},
        "search": {},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"fixture": SYNTHETIC_LABEL, "legacy": True},
    }
    return {
        "snapshot": snapshot,
        "input_bundle": {"schema_version": "MP/1", "issues": [], "label": SYNTHETIC_LABEL},
        "prepared_dataset": {"issues": [], "label": SYNTHETIC_LABEL},
        "artifacts": {"formula": snapshot["model"]["formula"], "label": SYNTHETIC_LABEL},
        "label": SYNTHETIC_LABEL,
        "memorized_point": point,
    }


def make_incomplete_evaluation() -> Dict[str, Any]:
    snapshot = {
        "schema_version": "MP/1",
        "job_id": "job-incomplete",
        "project_id": None,
        "input_sha256": None,
        "code_sha": None,
        "reference_date": None,
        "generated_at": "2024-02-01T00:00:00+00:00",
        "target": {"column": "preco", "unit": None, "estimand": "mean_response"},
        "value": {
            "point": None,
            "mean_ci80": None,
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": 5,
            "observed_target": 5,
            "prepared": 0,
            "used": 0,
            "excluded": 0,
            "used_row_ids": [],
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
            "statistical": {},
            "documentary": {
                "photos_required": True,
                "missing_photos": ["fachada"],
                "sources": [{"id": "laudo-externo", "status": "cited_only"}],
            },
            "issuance": {"status": "draft", "reasons": ["incomplete"]},
        },
        "issues": [],
        "model": {},
        "search": {},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"fixture": SYNTHETIC_LABEL},
    }
    artifacts = {
        "photos": [{"filename": "fachada.jpg", "bytes": None, "note": "declared but no bytes"}],
        "documentary": snapshot["validation"]["documentary"],
        "label": SYNTHETIC_LABEL,
    }
    return {
        "snapshot": snapshot,
        "input_bundle": None,
        "prepared_dataset": None,
        "artifacts": artifacts,
        "label": SYNTHETIC_LABEL,
    }
