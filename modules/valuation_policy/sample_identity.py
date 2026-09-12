"""Stable sample identity, observation kind, ambiguity, duplicates and groups."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from modules.import_formats import make_issue
from modules.utils import is_missing_token

OBSERVATION_KIND_OFFER = "offer"
OBSERVATION_KIND_TRANSACTION = "transaction"
KIND_ALIASES = {
    "oferta": OBSERVATION_KIND_OFFER,
    "offer": OBSERVATION_KIND_OFFER,
    "listing": OBSERVATION_KIND_OFFER,
    "asking": OBSERVATION_KIND_OFFER,
    "transacao": OBSERVATION_KIND_TRANSACTION,
    "transação": OBSERVATION_KIND_TRANSACTION,
    "transaction": OBSERVATION_KIND_TRANSACTION,
    "sale": OBSERVATION_KIND_TRANSACTION,
    "sold": OBSERVATION_KIND_TRANSACTION,
    "closed": OBSERVATION_KIND_TRANSACTION,
}

AREA_PRIVATIVE_HINTS = ("area_privativa", "area_privativo", "m2_privativo", "privative_area")
AREA_TOTAL_HINTS = ("area_total", "m2_total", "total_area", "area_construida")
PRICE_TOTAL_HINTS = ("preco_total", "valor_total", "preco", "valor")
PRICE_UNIT_HINTS = ("preco_m2", "valor_m2", "unit_price", "preco_unitario")


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum() or ch in {"_"})


def _columns(frame: pd.DataFrame) -> List[str]:
    return [str(c) for c in frame.columns]


def detect_observation_kinds(
    parsed_frame: pd.DataFrame,
    roles: Mapping[str, str],
    issues: List[dict],
) -> List[Optional[str]]:
    columns = _columns(parsed_frame)
    kind_col = None
    for name, role in roles.items():
        if role in {"source", "identifier"} and _norm(name) in {"tipo", "natureza", "observation_kind", "kind"}:
            kind_col = name
            break
    if kind_col is None:
        for name in columns:
            if _norm(name) in {"tipo", "natureza", "observation_kind", "kind", "origem"}:
                kind_col = name
                break
    n = len(parsed_frame)
    kinds: List[Optional[str]] = [None] * n
    if kind_col is None or kind_col not in parsed_frame.columns:
        return kinds
    collapsed = False
    for i, raw in enumerate(parsed_frame[kind_col].tolist()):
        token = str(raw).strip().lower() if not is_missing_token(raw) else ""
        mapped = KIND_ALIASES.get(token)
        kinds[i] = mapped
        if token and mapped is None:
            issues.append(
                make_issue(
                    "unknown_observation_kind",
                    "warning",
                    f"Natureza da observação {raw!r} não mapeada para oferta/transação.",
                    evidence={"column": kind_col, "value": raw},
                )
            )
    offers = sum(1 for k in kinds if k == OBSERVATION_KIND_OFFER)
    trans = sum(1 for k in kinds if k == OBSERVATION_KIND_TRANSACTION)
    if offers and trans:
        issues.append(
            make_issue(
                "offer_and_transaction_present",
                "info",
                "Amostra contém oferta e transação; as naturezas não foram colapsadas.",
                evidence={"offers": offers, "transactions": trans, "column": kind_col},
            )
        )
    return kinds


def detect_ambiguous_area_or_price(
    parsed_frame: pd.DataFrame,
    spec: Mapping[str, Any],
    issues: List[dict],
) -> None:
    columns = {_norm(c): c for c in _columns(parsed_frame)}
    units = spec.get("units") or {}
    target_unit = str(spec.get("target_unit") or "")
    priv = [orig for hint, orig in ((h, columns.get(h)) for h in AREA_PRIVATIVE_HINTS) if orig]
    total = [orig for hint, orig in ((h, columns.get(h)) for h in AREA_TOTAL_HINTS) if orig]
    area_basis = None
    for col, unit in units.items():
        if str(unit).lower() in {"m2_privativo", "privative_m2"}:
            area_basis = "privative"
        if str(unit).lower() in {"m2_total", "total_m2"}:
            area_basis = "total"
    if priv and total and area_basis is None:
        issues.append(
            make_issue(
                "ambiguous_area_basis",
                "error",
                "Área privativa e área total presentes sem declaração de qual entra no modelo.",
                evidence={"privative_columns": priv, "total_columns": total, "resolution": "declare units or roles"},
            )
        )
    unit_price_cols = [orig for h, orig in ((h, columns.get(h)) for h in PRICE_UNIT_HINTS) if orig]
    total_price_cols = [c for c in _columns(parsed_frame) if _norm(c) in PRICE_TOTAL_HINTS]
    if unit_price_cols and total_price_cols and target_unit in {"", None}:
        issues.append(
            make_issue(
                "ambiguous_price_basis",
                "error",
                "Preço total e preço unitário presentes; target_unit vazio não autoriza conversão.",
                evidence={
                    "unit_price_columns": unit_price_cols,
                    "total_price_columns": total_price_cols,
                    "resolution": "set target_unit to BRL or BRL/m2",
                },
            )
        )


def detect_dependent_groups(
    parsed_frame: pd.DataFrame,
    roles: Mapping[str, str],
    row_ids: Sequence[str],
    issues: List[dict],
) -> List[Dict[str, Any]]:
    source_cols = [name for name, role in roles.items() if role == "source" and name in parsed_frame.columns]
    groups: List[Dict[str, Any]] = []
    for column in source_cols:
        seen: Dict[str, List[str]] = {}
        for i, value in enumerate(parsed_frame[column].tolist()):
            if is_missing_token(value):
                continue
            seen.setdefault(str(value), []).append(row_ids[i])
        clustered = {k: ids for k, ids in seen.items() if len(ids) > 1}
        if clustered:
            groups.append({"column": column, "groups": clustered})
            affected = [rid for ids in clustered.values() for rid in ids]
            issues.append(
                make_issue(
                    "dependent_source_group",
                    "warning",
                    f"Registros compartilham a fonte {column!r}; n não é automaticamente independente.",
                    affected_ids=affected,
                    evidence={"column": column, "groups": clustered},
                )
            )
    return groups


def annotate_ingest_identity(
    *,
    parsed_frame: pd.DataFrame,
    raw_frame: pd.DataFrame,
    row_ids: Sequence[str],
    roles: Mapping[str, str],
    spec: Mapping[str, Any],
    issues: List[dict],
) -> Dict[str, Any]:
    kinds = detect_observation_kinds(parsed_frame, roles, issues)
    detect_ambiguous_area_or_price(parsed_frame, spec, issues)
    groups = detect_dependent_groups(parsed_frame, roles, row_ids, issues)
    locality_cols = [
        name
        for name in parsed_frame.columns
        if _norm(str(name)) in {"bairro", "localidade", "municipio", "cidade", "setor"}
    ]
    records = []
    for i, row_id in enumerate(row_ids):
        locality = None
        if locality_cols:
            locality = parsed_frame.iloc[i][locality_cols[0]]
        records.append(
            {
                "row_id": row_id,
                "locality": None if is_missing_token(locality) else locality,
                "reference_date": spec.get("reference_date"),
                "observation_kind": kinds[i] if i < len(kinds) else None,
                "stage": "interpreted",
            }
        )
    return {
        "records": records,
        "dependent_groups": groups,
        "raw_row_count": int(len(raw_frame)),
        "interpreted_row_count": int(len(parsed_frame)),
    }
