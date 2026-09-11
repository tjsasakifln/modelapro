"""Synthetic MP/1 InputBundle builders for C02 tests.

These fixtures are labeled contract fixtures. They are NOT C01 ingest_market
output and must not be treated as evidence of C01 integration.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

import pandas as pd


def mp1_request_spec(**overrides: Any) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "schema_version": "MP/1",
        "target_col": "valor",
        "candidate_cols": None,
        "roles": {
            "valor": "target",
            "bairro": "predictor",
            "area": "predictor",
            "id_imovel": "identifier",
            "data_anuncio": "date",
        },
        "kinds": {
            "bairro": "categorical",
            "area": "numeric",
            "valor": "numeric",
        },
        "units": {"area": "m2"},
        "import_options": {"locale": "pt-BR", "delimiter": None, "encoding": None},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {"mode": "exhaustive", "budget": None, "objective": "aic", "seed": 0},
        "evaluation_policy": {"method": "holdout", "seed": 0},
        "reference_date": None,
        "inspection_date": None,
        "target_unit": None,
        "applicant": "",
        "purpose": "",
    }
    for key, value in overrides.items():
        if (
            key in {"roles", "kinds", "units", "missing_policy", "import_options"}
            and isinstance(value, dict)
            and isinstance(spec.get(key), dict)
        ):
            merged = dict(spec[key])
            merged.update(value)
            spec[key] = merged
        else:
            spec[key] = value
    return spec


def mp1_bundle(
    rows: List[Dict[str, Any]],
    *,
    raw_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    parsed = pd.DataFrame(rows)
    raw = pd.DataFrame(raw_rows if raw_rows is not None else rows)
    ledger = []
    for row in rows:
        target = row.get("valor")
        observed = target is not None and not (isinstance(target, float) and pd.isna(target))
        ledger.append(
            {
                "row_id": str(row["row_id"]),
                "observed_target": bool(observed),
                "disposition": "kept" if observed else "missing_target",
                "missing_before": [k for k, v in row.items() if v is None or v == ""],
                "changes": [],
                "reasons": [],
            }
        )
    payload = json.dumps(
        {"schema_version": "MP/1", "row_ids": [r["row_id"] for r in rows]},
        sort_keys=True,
    )
    return {
        "schema_version": "MP/1",
        "raw_frame": raw,
        "parsed_frame": parsed,
        "column_map": {c: c for c in parsed.columns if c != "row_id"},
        "row_ledger": ledger,
        "input_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "issues": [],
        "_fixture_kind": "synthetic_mp1",
    }


def a01_rows() -> List[Dict[str, Any]]:
    """Centro is most frequent (reference). area uses pt-BR grouping/decimal."""
    return [
        {"row_id": "r1", "bairro": "Centro", "area": "80,00", "valor": 100000, "id_imovel": "A1", "data_anuncio": "2024-01-01"},
        {"row_id": "r2", "bairro": "Centro", "area": "90,50", "valor": 110000, "id_imovel": "A2", "data_anuncio": "2024-01-02"},
        {"row_id": "r3", "bairro": "Centro", "area": "1.234,56", "valor": 120000, "id_imovel": "A3", "data_anuncio": "2024-01-03"},
        {"row_id": "r4", "bairro": "Norte", "area": "100,00", "valor": 130000, "id_imovel": "A4", "data_anuncio": "2024-01-04"},
        {"row_id": "r5", "bairro": "Norte", "area": "110,00", "valor": 140000, "id_imovel": "A5", "data_anuncio": "2024-01-05"},
        {"row_id": "r6", "bairro": "Sul", "area": "120,00", "valor": 150000, "id_imovel": "A6", "data_anuncio": "2024-01-06"},
        {"row_id": "r7", "bairro": "Sul", "area": "130,00", "valor": 160000, "id_imovel": "A7", "data_anuncio": "2024-01-07"},
    ]
