"""PDF report renderer for MP/1 ResultSnapshot (campaign C08).

`render_report(snapshot, report_context)` is the only MP/1 PDF builder. It
copies value/unit/dates/sample/issues from the snapshot and never refits a
model or reconstructs the point estimate from interval bounds.

`generate_pdf_report` remains a legacy adapter for `ModelResult` (C16/worker).
Renderer failures on the MP/1 path raise `ReportRenderError` (never `None`).
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from .config_manager import config
from .logging_manager import logger
from .provenance import canonical_json
from .qualification_profile.assessment import normalize_institution_receipt
from .report_presenter.formula import compose_model_equation
from .report_presenter.qualification import assess_document_state
from .report_presenter.search_coverage import interpret_search
from .report_presenter.series import assess_chart_series
from .results import ModelResult

DISPLAY_ROUNDING_DECIMALS = 2

ISSUANCE_REASON_LABELS = {
    "no_automatic_report_approval": "Este documento não constitui aprovação automática de laudo.",
    "grau_is_not_issuance_readiness": "O grau calculado não equivale a prontidão de emissão.",
    "documentary_declared_is_not_verified_proof": "Documento apenas declarado não é comprovação.",
    "draft": "Minuta em rascunho, sujeita a revisão profissional.",
}

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

GRAU_LABELS = {1: "Grau I", 2: "Grau II", 3: "Grau III"}

ISSUANCE_LABELS = {
    "draft": "Minuta (rascunho) — saída técnica, não é laudo aprovado",
    "review_required": "Revisão profissional obrigatória — não constitui aprovação",
    "ready_for_professional_review": (
        "Pronta para revisão profissional — não constitui aprovação automática"
    ),
}

PRECISION_STATUS_LABELS = {
    "not_computed": "Precisão não calculada",
    "not_applicable_cost_quantification": "Não aplicável à quantificação de custo",
    "classified": "Precisão classificada",
    "unclassified": "Precisão calculada mas não classificável",
    "error": "Erro ao calcular a precisão",
}

ORIGIN_BUCKETS = {
    "normative": "normative",
    "normativo": "normative",
    "c03": "normative",
    "nbr": "normative",
    "statistical": "statistical",
    "estatistico": "statistical",
    "estatístico": "statistical",
    "c04": "statistical",
    "c07": "statistical",
    "documentary": "documentary",
    "documental": "documentary",
    "document": "documentary",
    "search": "search",
    "busca": "search",
    "c05": "search",
    "inference": "inference",
    "inferencia": "inference",
    "inferência": "inference",
    "c06": "inference",
}

ORIGIN_LABELS = {
    "normative": "Normativo",
    "statistical": "Estatístico",
    "documentary": "Documental",
    "search": "Busca",
    "inference": "Inferência",
    "other": "Outro",
}

CONFIRMED_BRL_UNITS = {
    "BRL",
    "R$",
    "BRL/M2",
    "BRL/M²",
    "R$/M2",
    "R$/M²",
    "BRL/M^2",
}

_PATH_RE = re.compile(
    r"(?:(?:/home/|/Users/|/var/|/tmp/|/opt/|[A-Za-z]:\\)[^\s,;<>\"']+)"
)
_SECRET_KEY_RE = re.compile(
    r"(password|secret|token|api[_-]?key|authorization|cookie|private[_-]?key)",
    re.IGNORECASE,
)

_CHART_FIGSIZE = (6.4, 3.7)
_CHART_DPI = 120


class ReportRenderError(Exception):
    """Identifiable PDF renderer failure for C10 `artifact_states`.

    Never used as a successful document. Callers must record the artifact as
    failed; a finished calculation does not imply a delivered report.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "C08_RENDER_FAILED",
        origin: str = "C08",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.origin = origin
        self.severity = "error"
        self.evidence = dict(evidence or {})

    def to_issue(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "origin": self.origin,
            "message": self.message,
            "affected_ids": list(self.evidence.get("affected_ids") or []),
            "evidence": {k: v for k, v in self.evidence.items() if k != "affected_ids"},
        }


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _as_finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def format_snapshot_number(value: Any) -> str:
    """Canonical, round-trip display of a snapshot number (not a recalculation)."""
    if value is None:
        return "null"
    number = _as_finite_number(value)
    if number is None:
        return "null"
    if abs(number) >= 1e15:
        return format(number, ".15g")
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _fmt(value: Optional[float], decimals: int = 2, prefix: str = "") -> str:
    if value is None:
        return "—"
    try:
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return "—"
        return f"{prefix}{value:.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pt_br(value: Any, decimals: int = 2) -> str:
    number = _as_finite_number(value)
    if number is None:
        return "—"
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _normalize_unit(unit: Any) -> Optional[str]:
    if unit is None:
        return None
    text = str(unit).strip()
    if not text or text.lower() in {"none", "null", "unknown", "desconhecida", "n/a", "na"}:
        return None
    return text


def _unit_is_brl(unit: Optional[str]) -> bool:
    if not unit:
        return False
    compact = unit.replace(" ", "").upper().replace("²", "2")
    compact = compact.replace("M^2", "M2")
    return compact in {u.replace(" ", "").upper().replace("²", "2") for u in CONFIRMED_BRL_UNITS} or compact in {
        "BRL",
        "R$",
        "BRL/M2",
        "R$/M2",
        "BRL/M^2",
    }


def _unit_is_brl_per_m2(unit: Optional[str]) -> bool:
    if not unit:
        return False
    compact = unit.replace(" ", "").upper().replace("²", "2").replace("M^2", "M2")
    return compact in {"BRL/M2", "R$/M2", "BRL/M^2"}


def format_value_with_unit(value: Any, unit: Optional[str], *, decimals: int = 2) -> str:
    number = _as_finite_number(value)
    if number is None:
        return "—"
    if _unit_is_brl_per_m2(unit):
        return f"R$ {_fmt_pt_br(number, decimals)}/m²"
    if _unit_is_brl(unit):
        return f"R$ {_fmt_pt_br(number, decimals)}"
    if unit:
        return f"{_fmt_pt_br(number, decimals)} {unit}"
    return _fmt_pt_br(number, decimals)


def _interval_bounds(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        lower = value.get("lower", value.get("inf", value.get("inferior")))
        upper = value.get("upper", value.get("sup", value.get("superior")))
        if lower is None and upper is None:
            return None
        out = {
            "lower": _as_finite_number(lower),
            "upper": _as_finite_number(upper),
        }
        if value.get("level") is not None:
            out["level"] = value.get("level")
        if value.get("kind") is not None:
            out["kind"] = value.get("kind")
        return out
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return {
            "lower": _as_finite_number(value[0]),
            "upper": _as_finite_number(value[1]),
        }
    return None


def _interval_display(bounds: Optional[Mapping[str, Any]], unit: Optional[str]) -> str:
    if not bounds:
        return "—"
    lower = bounds.get("lower")
    upper = bounds.get("upper")
    if lower is None and upper is None:
        return "—"
    return (
        f"{format_value_with_unit(lower, unit)} a "
        f"{format_value_with_unit(upper, unit)}"
    )


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = _PATH_RE.sub("[caminho local omitido]", text)
    return text


def _redact_mapping(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[omitido]"
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            key_s = str(key)
            if _SECRET_KEY_RE.search(key_s) or key_s.lower() in {
                "path",
                "file_path",
                "source_path",
                "local_path",
                "abspath",
                "filename_path",
            }:
                out[key_s] = "[omitido]"
            else:
                out[key_s] = _redact_mapping(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_mapping(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return _safe_text(value)
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return _safe_text(value)


def _issuance_reason_text(reason: Any) -> str:
    text = _safe_text(reason)
    if not text:
        return ""
    return ISSUANCE_REASON_LABELS.get(text, ISSUANCE_REASON_LABELS.get(text.lower(), text))


def _group_issues(issues: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: List[Dict[str, Any]] = []
    index: Dict[Tuple[str, str, str], int] = {}
    for issue in issues:
        key = (
            str(issue.get("origin_bucket") or ""),
            str(issue.get("code") or ""),
            str(issue.get("message") or ""),
        )
        if key not in index:
            index[key] = len(grouped)
            grouped.append(dict(issue))
            continue
        current = grouped[index[key]]
        seen = set(current.get("affected_ids") or [])
        for rid in issue.get("affected_ids") or []:
            if rid not in seen:
                current.setdefault("affected_ids", []).append(rid)
                seen.add(rid)
    return grouped


def _metrics_block(model: Mapping[str, Any], statistical: Mapping[str, Any]) -> Dict[str, Any]:
    metrics_src = model.get("metrics") if isinstance(model.get("metrics"), Mapping) else {}
    if not metrics_src:
        metrics_src = {
            k: statistical.get(k)
            for k in ("r2", "r2_adjusted", "f_statistic", "f_pvalue", "durbin_watson")
            if statistical.get(k) is not None
        }
        if statistical.get("f_pvalue") is not None and "f_pvalue" not in metrics_src:
            metrics_src["f_pvalue"] = statistical.get("f_pvalue")
    present = bool(metrics_src)
    return {
        "present": present,
        "source": "model.metrics" if isinstance(model.get("metrics"), Mapping) and model.get("metrics") else (
            "validation.statistical" if present else ""
        ),
        "external": False,
        "r2": _fmt(_as_finite_number(metrics_src.get("r2")), 4) if present else "—",
        "r2_adjusted": _fmt(_as_finite_number(metrics_src.get("r2_adjusted")), 4) if present else "—",
        "f_statistic": _fmt(_as_finite_number(metrics_src.get("f_statistic")), 3) if present else "—",
        "f_pvalue": _fmt(_as_finite_number(metrics_src.get("f_pvalue")), 4) if present else "—",
        "durbin_watson": _fmt(
            _as_finite_number(
                metrics_src.get("durbin_watson") or metrics_src.get("autocorrelation_durbin_watson")
            ),
            3,
        )
        if present
        else "—",
        "note": (
            "Indicadores de ajustamento da amostra utilizada (não são desempenho de validação externa)."
            if present
            else "Indicadores de ajustamento não foram fornecidos neste snapshot."
        ),
    }


def _context_sources(ctx: Mapping[str, Any], provenance: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split human sources from technical hashes. Do not invent market URLs."""
    human: List[Dict[str, Any]] = []
    technical: List[Dict[str, Any]] = []
    raw = ctx.get("sources")
    if isinstance(raw, Mapping) and not any(k in raw for k in ("id", "label", "citation", "name")):
        for key, value in raw.items():
            technical.append({"id": str(key), "label": str(key), "citation": _safe_text(value)})
        return human, technical
    for src in _as_list(raw):
        if isinstance(src, Mapping):
            entry = {
                "id": _safe_text(src.get("id") or ""),
                "label": _safe_text(src.get("label") or src.get("name") or ""),
                "citation": _safe_text(src.get("citation") or src.get("description") or ""),
            }
            if str(entry["id"]).lower() in {"input_sha256", "dataset_sha256", "code_sha"}:
                technical.append(entry)
            else:
                human.append(entry)
        else:
            human.append({"id": "", "label": _safe_text(src), "citation": ""})
    return human, technical


def _origin_bucket(origin: Any) -> str:
    text = str(origin or "other").strip().lower()
    if text in ORIGIN_BUCKETS:
        return ORIGIN_BUCKETS[text]
    for prefix, bucket in ORIGIN_BUCKETS.items():
        if text.startswith(prefix):
            return bucket
    return "other"


def _issue_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, Mapping):
        origin = raw.get("origin") or "other"
        return {
            "code": str(raw.get("code") or "ISSUE"),
            "severity": str(raw.get("severity") or "warning"),
            "origin": str(origin),
            "origin_bucket": _origin_bucket(origin),
            "origin_label": ORIGIN_LABELS.get(_origin_bucket(origin), "Outro"),
            "message": _safe_text(raw.get("message") or ""),
            "affected_ids": [str(i) for i in _as_list(raw.get("affected_ids"))],
            "evidence": _redact_mapping(raw.get("evidence") or {}),
        }
    return {
        "code": "ISSUE",
        "severity": "warning",
        "origin": "other",
        "origin_bucket": "other",
        "origin_label": "Outro",
        "message": _safe_text(raw),
        "affected_ids": [],
        "evidence": {},
    }


def _row_id(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("row_id", "id", "identificador"):
            if value.get(key) is not None:
                return str(value.get(key))
    return str(value)


def _document_items(raw: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not raw:
        return items
    if isinstance(raw, Mapping):
        if any(k in raw for k in ("declared", "present", "verified", "pending", "items")):
            for status in ("declared", "present", "verified", "pending"):
                for item in _as_list(raw.get(status)):
                    if isinstance(item, Mapping):
                        items.append(
                            {
                                "name": _safe_text(item.get("name") or item.get("id") or item),
                                "status": status,
                                "status_label": {
                                    "declared": "Declarado",
                                    "present": "Presente",
                                    "verified": "Verificado",
                                    "pending": "Pendente",
                                }[status],
                                "provenance": _safe_text(item.get("provenance") or item.get("source") or ""),
                            }
                        )
                    else:
                        items.append(
                            {
                                "name": _safe_text(item),
                                "status": status,
                                "status_label": {
                                    "declared": "Declarado",
                                    "present": "Presente",
                                    "verified": "Verificado",
                                    "pending": "Pendente",
                                }[status],
                                "provenance": "",
                            }
                        )
            for item in _as_list(raw.get("items")):
                items.extend(_document_items([item]))
            for key, nested in raw.items():
                if key in {
                    "declared",
                    "present",
                    "verified",
                    "pending",
                    "items",
                    "status",
                    "note",
                    "provenance",
                }:
                    continue
                if isinstance(nested, Mapping) and (
                    nested.get("evidence_status") or nested.get("status") or nested.get("grade") is not None
                ):
                    extra = dict(nested)
                    extra.setdefault("name", key)
                    extra.setdefault("id", key)
                    items.extend(_document_items(extra))
            return items
        nested_docs = [
            (key, nested)
            for key, nested in raw.items()
            if isinstance(nested, Mapping)
            and key
            not in {"status", "note", "provenance", "evidence", "calculation", "source"}
            and (nested.get("evidence_status") or nested.get("status") or "grade" in nested)
        ]
        if nested_docs and not raw.get("name") and not raw.get("id"):
            for key, nested in nested_docs:
                extra = dict(nested)
                extra.setdefault("name", key)
                extra.setdefault("id", key)
                items.extend(_document_items(extra))
            return items
        status = str(raw.get("status") or raw.get("evidence_status") or "declared")
        status_norm = {
            "declared": "declared",
            "declarado": "declared",
            "present": "present",
            "presente": "present",
            "verified": "verified",
            "verificado": "verified",
            "pending": "pending",
            "pendente": "pending",
        }.get(status.lower(), "declared")
        items.append(
            {
                "name": _safe_text(raw.get("name") or raw.get("id") or ""),
                "status": status_norm,
                "status_label": {
                    "declared": "Declarado",
                    "present": "Presente",
                    "verified": "Verificado",
                    "pending": "Pendente",
                }.get(status_norm, status_norm),
                "provenance": _safe_text(raw.get("provenance") or raw.get("source") or ""),
            }
        )
        return items
    if isinstance(raw, list):
        for item in raw:
            items.extend(_document_items(item))
    return items


def _documentary_attachments(raw: Any) -> List[Dict[str, Any]]:
    """Prepare only explicitly authorized attachment bytes for the report."""
    attachments = []
    for index, item in enumerate(_as_list(raw)):
        if not isinstance(item, Mapping):
            continue
        content = item.get("bytes") or item.get("content")
        media_type = _safe_text(item.get("type") or item.get("media_type") or "application/octet-stream")
        authorized = item.get("authorized_for_report") is True
        row = {
            "name": _safe_text(item.get("filename") or item.get("name") or f"anexo-{index + 1}"),
            "media_type": media_type,
            "authorized": authorized,
            "sha256": hashlib.sha256(bytes(content)).hexdigest()
            if isinstance(content, (bytes, bytearray))
            else _safe_text(item.get("sha256") or ""),
            "image_data_uri": None,
            "status": "mapped",
        }
        if authorized and isinstance(content, (bytes, bytearray)) and media_type in {
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            row["image_data_uri"] = f"data:{media_type};base64," + base64.b64encode(bytes(content)).decode("ascii")
            row["status"] = "embedded"
        elif not authorized:
            row["status"] = "not_authorized_for_report"
        elif not isinstance(content, (bytes, bytearray)):
            row["status"] = "bytes_missing"
        attachments.append(row)
    return attachments


def _next_action_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, Mapping):
        limitations_raw = raw.get("limitations")
        if isinstance(limitations_raw, list):
            limitations_items = [_safe_text(x) for x in limitations_raw if str(x).strip()]
        elif limitations_raw:
            limitations_items = [_safe_text(limitations_raw)]
        else:
            limitations_items = []
        return {
            "code": _safe_text(raw.get("code") or ""),
            "priority": _safe_text(raw.get("priority") or ""),
            "reason": _safe_text(raw.get("reason") or ""),
            "next_step": _safe_text(raw.get("next_step") or ""),
            "evidence_refs": [str(x) for x in _as_list(raw.get("evidence_refs"))],
            "limitations": "; ".join(limitations_items),
            "limitations_items": limitations_items,
        }
    return {
        "code": "",
        "priority": "",
        "reason": _safe_text(raw),
        "next_step": "",
        "evidence_refs": [],
        "limitations": "",
        "limitations_items": [],
    }


def _coef_rows(model: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    coefficients = model.get("coefficients")
    pvalues = model.get("pvalues") if isinstance(model.get("pvalues"), Mapping) else {}
    vif = model.get("vif") if isinstance(model.get("vif"), Mapping) else {}
    if isinstance(coefficients, Mapping):
        for name, coef in coefficients.items():
            number = _as_finite_number(coef)
            rows.append(
                {
                    "variable": str(name),
                    "coefficient_full": format_snapshot_number(number),
                    "coefficient": _fmt(number, 6) if number is not None else "—",
                    "pvalue": _fmt(_as_finite_number(pvalues.get(name)), 4) if name in pvalues else "—",
                    "vif": _fmt(_as_finite_number(vif.get(name)), 3)
                    if name in vif and str(name) != "const"
                    else "—",
                }
            )
        return rows
    for item in _as_list(coefficients):
        if not isinstance(item, Mapping):
            continue
        name = item.get("name") or item.get("variable") or ""
        number = _as_finite_number(item.get("value") if "value" in item else item.get("coefficient"))
        rows.append(
            {
                "variable": str(name),
                "coefficient_full": format_snapshot_number(number),
                "coefficient": _fmt(number, 6) if number is not None else "—",
                "pvalue": _fmt(_as_finite_number(item.get("pvalue")), 4),
                "vif": _fmt(_as_finite_number(item.get("vif")), 3)
                if str(name) != "const"
                else "—",
            }
        )
    return rows


def _index_rows(rows: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        if isinstance(raw, Mapping):
            rid = _row_id(raw)
            values = raw.get("values") if isinstance(raw.get("values"), Mapping) else {}
            extra = {
                k: v
                for k, v in raw.items()
                if k not in {"row_id", "id", "identificador", "source", "justification", "values", "label", "name"}
            }
            merged_values = dict(values)
            merged_values.update(extra)
            indexed[rid] = {
                "row_id": rid,
                "source": _safe_text(raw.get("source") or raw.get("fonte") or ""),
                "justification": _safe_text(raw.get("justification") or raw.get("justificativa") or ""),
                "label": _safe_text(raw.get("label") or raw.get("name") or ""),
                "values": {str(k): v for k, v in merged_values.items()},
            }
        else:
            rid = str(raw)
            indexed[rid] = {
                "row_id": rid,
                "source": "",
                "justification": "",
                "label": "",
                "values": {},
            }
    return indexed


def _ledger_rows(
    ids: Sequence[Any],
    details: Mapping[str, Dict[str, Any]],
    *,
    default_justification: str,
) -> List[Dict[str, Any]]:
    rows = []
    for raw_id in ids:
        rid = str(raw_id)
        info = details.get(rid) or {}
        source = info.get("source") or ""
        justification = info.get("justification") or ""
        label = info.get("label") or ""
        values = info.get("values") or {}
        storage_values = {
            str(k): format_snapshot_number(v) if _as_finite_number(v) is not None else _safe_text(v)
            for k, v in values.items()
        }
        rows.append(
            {
                "row_id": rid,
                "source": source if source else "Fonte não informada no contexto do relatório",
                "justification": justification if justification else default_justification,
                "label": label,
                "values": values,
                "storage_values": storage_values,
                "value_cells": [storage_values.get(k, values.get(k, "")) for k in sorted(values.keys())],
            }
        )
    return rows


def _value_columns(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    keys = []
    seen = set()
    for row in rows:
        for key in (row.get("values") or {}):
            if key not in seen:
                seen.add(key)
                keys.append(str(key))
    return keys


def _pending(label: str) -> str:
    return f"Pendência: {label}"


def build_report_view(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure snapshot → view-model mapping. No I/O, no model fitting."""
    if not isinstance(snapshot, Mapping):
        raise ReportRenderError(
            "snapshot MP/1 inválido ou ausente",
            code="C08_INVALID_SNAPSHOT",
            evidence={"snapshot_type": type(snapshot).__name__},
        )
    ctx = _as_mapping(report_context)

    target = _as_mapping(snapshot.get("target"))
    value = _as_mapping(snapshot.get("value"))
    sample = _as_mapping(snapshot.get("sample"))
    validation = _as_mapping(snapshot.get("validation"))
    model = _as_mapping(snapshot.get("model"))
    search = _as_mapping(snapshot.get("search"))
    provenance = _as_mapping(snapshot.get("provenance"))
    cost_result = _as_mapping(provenance.get("cost_result"))
    cost_memory = _as_mapping(cost_result.get("memory")) or _as_mapping(ctx.get("cost_memory"))
    cost_labels = (
        ("direct_subtotal", "Custo direto"),
        ("bdi_rate", "Taxa de BDI"),
        ("bdi_amount", "BDI"),
        ("reproduction_building", "Custo de reprodução da benfeitoria"),
        ("depreciation_rate", "Taxa de depreciação física"),
        ("depreciation_amount", "Depreciação física"),
        ("depreciated_building", "Benfeitoria depreciada"),
        ("land_subtotal", "Terreno explicitamente incluído"),
        ("total", "Total"),
    )
    issuance = _as_mapping(validation.get("issuance"))
    precisao = _as_mapping(validation.get("precisao"))
    fundamentacao = _as_mapping(validation.get("fundamentacao"))
    statistical = _as_mapping(validation.get("statistical"))
    documentary = validation.get("documentary")
    document_state = assess_document_state(snapshot, ctx)
    qualification_profile = _as_mapping(document_state.get("profile"))
    qualification_rules = [
        _redact_mapping(rule) for rule in _as_list(document_state.get("rule_results")) if isinstance(rule, Mapping)
    ]

    unit = _normalize_unit(target.get("unit") if target.get("unit") is not None else ctx.get("target_unit"))
    unit_pending = unit is None
    reference_date = snapshot.get("reference_date")
    if reference_date is not None:
        reference_date = str(reference_date).strip() or None
    inspection_date = snapshot.get("inspection_date")
    if inspection_date is None:
        inspection_date = ctx.get("inspection_date")
    if inspection_date is not None:
        inspection_date = str(inspection_date).strip() or None

    point = _as_finite_number(value.get("point"))
    mean_ci80 = _interval_bounds(value.get("mean_ci80"))
    prediction_interval = _interval_bounds(value.get("prediction_interval"))
    arbitration_interval = _interval_bounds(value.get("arbitration_interval"))
    admissible_interval = _interval_bounds(value.get("admissible_interval"))
    adopted_raw = value.get("adopted_value", value.get("adopted"))
    if isinstance(adopted_raw, Mapping):
        adopted_point = _as_finite_number(adopted_raw.get("point") or adopted_raw.get("value"))
        adopted_reason = _safe_text(adopted_raw.get("reason") or adopted_raw.get("policy_ref") or "")
    else:
        adopted_point = _as_finite_number(adopted_raw)
        adopted_reason = _safe_text(value.get("adoption_policy_ref") or "")

    used_ids = [str(i) for i in _as_list(sample.get("used_row_ids"))]
    excluded_ids = [str(i) for i in _as_list(sample.get("excluded_row_ids"))]
    n_received = sample.get("received")
    n_observed = sample.get("observed_target")
    n_prepared = sample.get("prepared")
    n_used = sample.get("used")
    n_excluded = sample.get("excluded")
    if n_used is None:
        n_used = len(used_ids)
    if n_excluded is None:
        n_excluded = len(excluded_ids)

    used_details = _index_rows(_as_list(ctx.get("used_rows")))
    excluded_details = _index_rows(_as_list(ctx.get("excluded_rows")))
    used_rows = _ledger_rows(
        used_ids,
        used_details,
        default_justification="Incluído na amostra efetiva do snapshot (justificativa não informada no contexto)",
    )
    excluded_rows = _ledger_rows(
        excluded_ids,
        excluded_details,
        default_justification="Pendência: justificativa de exclusão não informada",
    )
    used_value_columns = _value_columns(used_rows)
    excluded_value_columns = _value_columns(excluded_rows)
    for n, row in enumerate(used_rows, start=1):
        row["seq"] = n
        storage = row.get("storage_values") or {}
        row["value_cells"] = [storage.get(k, row["values"].get(k, "")) for k in used_value_columns]
    for n, row in enumerate(excluded_rows, start=1):
        row["seq"] = n
        storage = row.get("storage_values") or {}
        row["value_cells"] = [storage.get(k, row["values"].get(k, "")) for k in excluded_value_columns]

    issues = _group_issues([_issue_dict(i) for i in _as_list(snapshot.get("issues"))])
    issues_by_origin: Dict[str, List[Dict[str, Any]]] = {
        key: [] for key in ("normative", "statistical", "documentary", "search", "inference", "other")
    }
    for issue in issues:
        issues_by_origin.setdefault(issue["origin_bucket"], []).append(issue)
    priority_limitations = [
        issue for issue in issues if str(issue.get("severity") or "").lower() in {"error", "warning"}
    ]

    precisao_status = str(precisao.get("status") or "not_computed")
    precision_not_applicable_to_cost = (
        precisao_status == "not_applicable_cost_quantification"
        or precisao.get("reason") == "not_applicable_to_cost_quantification"
        or (
            statistical.get("route") == "cost_quantification"
            and statistical.get("precision_grade_applicable") is False
        )
    )
    if precision_not_applicable_to_cost:
        precisao_status = "not_applicable_cost_quantification"
    precisao_grade = precisao.get("grade")
    amplitude_pct = _as_finite_number(precisao.get("amplitude_pct"))

    documents = _document_items(documentary)
    documents.extend(_document_items(ctx.get("documents")))
    documentary_attachments = _documentary_attachments(
        ctx.get("documentary_files") or ctx.get("photos") or ctx.get("attachments")
    )
    # de-duplicate by (name, status)
    seen_docs = set()
    unique_docs = []
    for doc in documents:
        key = (doc.get("name"), doc.get("status"))
        if key in seen_docs:
            continue
        seen_docs.add(key)
        unique_docs.append(doc)

    sources, technical_sources = _context_sources(ctx, provenance)
    search_info = interpret_search(search)
    search_exhaustive = search_info["exhaustive"]
    search_mode = search_info["mode"]
    approximate = search_info["approximate"]
    search_limitations = list(search_info["limitations"])
    for item in _as_list(ctx.get("search_limitations")):
        text_item = _safe_text(item)
        if text_item and text_item not in search_limitations:
            search_limitations.append(text_item)
    inference_limitations = [
        _safe_text(item) for item in _as_list(ctx.get("inference_limitations") or model.get("inference_limitations"))
    ]
    if statistical.get("limitations"):
        inference_limitations.extend(_safe_text(x) for x in _as_list(statistical.get("limitations")))
    if search_info["summary"] and search_info["approximate"]:
        inference_limitations.append(search_info["summary"])

    next_actions = [_next_action_dict(a) for a in _as_list(snapshot.get("next_actions"))]

    issuance_status = str(issuance.get("status") or "draft")
    if issuance_status not in ISSUANCE_LABELS:
        issuance_status = "draft"
    issuance_reasons = [
        _issuance_reason_text(r) for r in _as_list(issuance.get("reasons")) if _issuance_reason_text(r)
    ]

    metrics = _metrics_block(model, statistical)
    equation = compose_model_equation(model, target_col=str(target.get("column") or ""))
    chart_series = assess_chart_series(ctx, used_row_ids=used_ids)
    external_validation = None
    procedure = validation.get("procedure") or validation.get("evaluation") or snapshot.get("evaluation")
    if isinstance(procedure, Mapping) and procedure:
        method = str(procedure.get("method") or procedure.get("kind") or "").strip().lower()
        if method and method not in {"none", "not_requested", "skipped"}:
            external_validation = {
                "present": True,
                "method": _safe_text(procedure.get("method") or procedure.get("kind") or ""),
                "summary": _safe_text(procedure.get("summary") or procedure.get("detail") or ""),
                "metrics": procedure.get("metrics") if isinstance(procedure.get("metrics"), Mapping) else {},
            }
        elif method in {"none", "not_requested", "skipped"}:
            external_validation = {
                "present": False,
                "method": method,
                "summary": "Validação externa não foi solicitada neste pedido. Isso não é defeito da minuta exploratória.",
                "metrics": {},
            }

    market = ctx.get("market_descriptive") or ctx.get("market_summary")
    market_rows = []
    market_n = None
    if isinstance(market, Mapping) and market.get("variables"):
        market_n = market.get("n")
        for var in market["variables"]:
            market_rows.append(
                {
                    "name": var.get("name"),
                    "unit": var.get("unit") or "",
                    "min": _fmt(var.get("min"), 2),
                    "mean": _fmt(var.get("mean"), 2),
                    "median": _fmt(var.get("median"), 2) if var.get("median") is not None else "—",
                    "max": _fmt(var.get("max"), 2),
                }
            )

    annexes = []
    for annex in _as_list(ctx.get("annexes")):
        if not isinstance(annex, Mapping):
            continue
        annexes.append(
            {
                "title": _safe_text(annex.get("title") or annex.get("name") or "Anexo"),
                "kind": annex.get("kind") or "table",
                "columns": [str(c) for c in _as_list(annex.get("columns"))],
                "rows": _as_list(annex.get("rows")),
                "note": _safe_text(annex.get("note") or ""),
            }
        )

    subject = ctx.get("subject") if isinstance(ctx.get("subject"), Mapping) else {}
    subject_items = [(str(k), subject[k]) for k in subject]

    model_id = (
        model.get("model_id")
        or model.get("id")
        or model.get("number")
        or model.get("candidate_id")
        or provenance.get("model_id")
    )
    model_revision = model.get("revision") or provenance.get("model_revision") or provenance.get("revision")
    model_sha = model.get("model_sha256") or provenance.get("model_sha256")
    code_sha = snapshot.get("code_sha") or provenance.get("code_sha")
    input_sha = snapshot.get("input_sha256") or provenance.get("input_sha256")
    generated_at = snapshot.get("generated_at")
    job_id = snapshot.get("job_id")
    project_id = snapshot.get("project_id")

    frozen = {
        "MP1_POINT": format_snapshot_number(point),
        "MP1_ADOPTED_VALUE": format_snapshot_number(adopted_point),
        "MP1_MEAN_CI80_LOWER": format_snapshot_number(mean_ci80["lower"] if mean_ci80 else None),
        "MP1_MEAN_CI80_UPPER": format_snapshot_number(mean_ci80["upper"] if mean_ci80 else None),
        "MP1_PRED_LOWER": format_snapshot_number(
            prediction_interval["lower"] if prediction_interval else None
        ),
        "MP1_PRED_UPPER": format_snapshot_number(
            prediction_interval["upper"] if prediction_interval else None
        ),
        "MP1_ARB_LOWER": format_snapshot_number(
            arbitration_interval["lower"] if arbitration_interval else None
        ),
        "MP1_ARB_UPPER": format_snapshot_number(
            arbitration_interval["upper"] if arbitration_interval else None
        ),
        "MP1_ADM_LOWER": format_snapshot_number(
            admissible_interval["lower"] if admissible_interval else None
        ),
        "MP1_ADM_UPPER": format_snapshot_number(
            admissible_interval["upper"] if admissible_interval else None
        ),
        "MP1_REFERENCE_DATE": reference_date or "PENDENTE",
        "MP1_INSPECTION_DATE": inspection_date or "PENDENTE",
        "MP1_TARGET_UNIT": unit or "PENDENTE",
        "MP1_N_RECEIVED": format_snapshot_number(n_received),
        "MP1_N_OBSERVED": format_snapshot_number(n_observed),
        "MP1_N_PREPARED": format_snapshot_number(n_prepared),
        "MP1_N_USED": format_snapshot_number(n_used),
        "MP1_N_EXCLUDED": format_snapshot_number(n_excluded),
        "MP1_ISSUANCE": issuance_status,
        "MP1_PRECISAO_STATUS": precisao_status,
        "MP1_FUNDAMENTACAO_GRADE": (
            str(int(fundamentacao["grade"]))
            if isinstance(fundamentacao.get("grade"), int)
            else "PENDENTE"
        ),
        "MP1_PRECISAO_GRADE": (
            str(int(precisao_grade)) if isinstance(precisao_grade, int) else "PENDENTE"
        ),
        "MPQUAL_PROFILE_ID": qualification_profile.get("id") or "PENDENTE",
        "MPQUAL_PROFILE_VERSION": qualification_profile.get("version") or "PENDENTE",
        "MPQUAL_VALUE_BASIS": qualification_profile.get("value_basis") or "PENDENTE",
        "MPQUAL_RELEASE_STATUS": document_state.get("case_release_status") or "analysis_only",
        "MPQUAL_GRADE_REQUIREMENT": document_state.get("grade_requirement_status") or "pending",
        "MPQUAL_RESULT_FINGERPRINT": document_state.get("result_fingerprint") or "PENDENTE",
        "MPQUAL_REPORT_CONTENT_FINGERPRINT": document_state.get("report_content_fingerprint")
        or "PENDENTE",
        "MPQUAL_REVIEW_EVENTS": str(len(document_state.get("review_events") or [])),
        "MPQUAL_RULES_SHA256": hashlib.sha256(
            canonical_json(qualification_rules).encode("utf-8")
        ).hexdigest(),
        "MPQUAL_REVIEW_SHA256": hashlib.sha256(
            canonical_json(document_state.get("review_events") or []).encode("utf-8")
        ).hexdigest(),
        "MPSAMPLE_ROWS_SHA256": hashlib.sha256(
            canonical_json(
                {
                    "used_rows": _as_list(ctx.get("used_rows")),
                    "excluded_rows": _as_list(ctx.get("excluded_rows")),
                }
            ).encode("utf-8")
        ).hexdigest(),
    }
    frozen_lines = [f"{key}={value}" for key, value in frozen.items()]

    provenance_for_report = _redact_mapping(provenance)
    for verbose_key in ("qualification_context", "workflow_context"):
        verbose_value = provenance_for_report.pop(verbose_key, None)
        if verbose_value:
            provenance_for_report[f"{verbose_key}_sha256"] = hashlib.sha256(
                canonical_json(verbose_value).encode("utf-8")
            ).hexdigest()

    grau_fundamentacao_label = GRAU_LABELS.get(fundamentacao.get("grade"), "Não classificado")
    if precisao_status == "not_applicable_cost_quantification":
        grau_precisao_label = "Não aplicável à quantificação de custo"
    elif precisao_status == "unclassified":
        grau_precisao_label = "Calculada, não classificável"
    elif precisao_status == "not_computed":
        grau_precisao_label = "Não calculado"
    elif precisao_status == "error":
        grau_precisao_label = "Erro no cálculo"
    else:
        grau_precisao_label = GRAU_LABELS.get(precisao_grade, "Não classificado")

    precisao_note = None
    if precisao_status == "unclassified":
        if amplitude_pct is not None:
            precisao_note = (
                f"Amplitude do IC da média = {_fmt(amplitude_pct, 1)}% — precisão calculada "
                "mas não classificável quanto ao grau da Tabela 5. Isso não autoriza emissão "
                "como se o grau existisse."
            )
        else:
            precisao_note = "Precisão calculada mas não classificável (amplitude não informada no snapshot)."
    elif precisao_status == "not_computed":
        precisao_note = "Grau de precisão não calculado no snapshot."
    elif precisao_status == "error":
        precisao_note = "Erro ao calcular a precisão — campo permanece pendente."

    item_scores = []
    for item in _as_list(fundamentacao.get("items")):
        if not isinstance(item, Mapping):
            continue
        item_scores.append(
            {
                "item": item.get("id") or item.get("item") or "",
                "description": _safe_text(item.get("description") or item.get("name") or ""),
                "grau_label": GRAU_LABELS.get(item.get("grade") or item.get("grau"), "Não atingido")
                if isinstance(item.get("grade") or item.get("grau"), int)
                else _safe_text(item.get("grade") or item.get("status") or "Pendente"),
                "detail": _safe_text(item.get("detail") or item.get("evidence_status") or ""),
                "evidence_status": _safe_text(item.get("evidence_status") or item.get("status") or ""),
            }
        )

    alternatives = []
    for alt in _as_list(snapshot.get("alternatives")):
        if isinstance(alt, Mapping):
            alternatives.append(
                {
                    "id": _safe_text(alt.get("candidate_id") or alt.get("id") or ""),
                    "summary": _safe_text(alt.get("summary") or alt.get("reason") or alt.get("status") or ""),
                }
            )
        else:
            alternatives.append({"id": "", "summary": _safe_text(alt)})

    applicant = (
        ctx.get("applicant")
        or snapshot.get("applicant")
        or provenance.get("applicant")
        or qualification_profile.get("applicant")
        or ""
    )
    purpose = (
        qualification_profile.get("purpose")
        or ctx.get("purpose")
        or snapshot.get("purpose")
        or provenance.get("purpose")
        or ""
    )
    rights = ctx.get("rights") or ctx.get("property_rights") or ""
    asset_identification = ctx.get("asset_identification") or ctx.get("asset") or subject
    if isinstance(asset_identification, Mapping):
        asset_identification_display = "; ".join(
            f"{_safe_text(key)}: {_safe_text(val)}" for key, val in asset_identification.items()
        )
    else:
        asset_identification_display = _safe_text(asset_identification)
    if rights:
        asset_identification_display = (
            f"{asset_identification_display}; direitos: {_safe_text(rights)}"
            if asset_identification_display
            else f"Direitos: {_safe_text(rights)}"
        )
    methodology = (
        ctx.get("methodology_justification")
        or qualification_profile.get("method")
        or validation.get("method")
        or ""
    )
    approved_reviews = document_state.get("approved_review_events") or []
    professional_identity = _as_mapping(ctx.get("professional_identity"))
    professional_identity_display = " — ".join(
        part
        for part in (
            _safe_text(professional_identity.get("name") or ""),
            _safe_text(professional_identity.get("council") or ""),
            _safe_text(professional_identity.get("registration") or ""),
            (
                "ART/RRT "
                + _safe_text(
                    professional_identity.get("art_rrt")
                    or professional_identity.get("responsibility_document")
                )
                if professional_identity.get("art_rrt")
                or professional_identity.get("responsibility_document")
                else ""
            ),
            _safe_text(professional_identity.get("documentary_reference") or ""),
        )
        if part
    )
    if approved_reviews:
        review = approved_reviews[-1]
        professional = _as_mapping(review.get("professional") or review.get("reviewer"))
        professional_review_display = " — ".join(
            part
            for part in (
                _safe_text(professional.get("name") or review.get("professional_name") or "Profissional identificado"),
                _safe_text(professional.get("registration") or review.get("professional_id") or ""),
                _safe_text(review.get("reason") or review.get("motive") or review.get("motivation") or ""),
                _safe_text(review.get("revision_id") or review.get("version") or ""),
            )
            if part
        )
    else:
        professional_review_display = "PENDENTE — evento aprovador identificável ausente"
    acceptance = normalize_institution_receipt(
        document_state.get("institution_acceptance"), qualification_profile
    )
    receipt = _as_mapping(acceptance.get("record"))
    if acceptance.get("recorded"):
        institution_acceptance_display = " — ".join(
            part
            for part in (
                "Comprovante registrado — NÃO VERIFICADO",
                _safe_text(
                    receipt.get("recipient_id")
                    or qualification_profile.get("recipient_id")
                    or ""
                ),
                _safe_text(receipt.get("protocol") or ""),
                "SHA-256 " + _safe_text(receipt.get("proof_sha256") or ""),
                "associação à versão efetivamente enviada NÃO VERIFICADA",
            )
            if part
        )
    else:
        institution_acceptance_display = "Não registrada; emissão do laudo não implica aceitação do destinatário."

    view = {
        "app_name": config.APP_NAME,
        "document_kind": document_state["document_kind"],
        "document_is_final": document_state["is_final"],
        "not_approved_label": (
            "Laudo final emitido após os critérios e a revisão vinculados a esta versão"
            if document_state["is_final"]
            else "Este documento não é laudo aprovado automaticamente e permanece análise/minuta"
        ),
        "issuance_status": issuance_status,
        "issuance_label": document_state["document_kind"],
        "issuance_reasons": issuance_reasons,
        "document_state": document_state,
        "document_state_blockers": document_state["blockers"],
        "case_release_status": document_state["case_release_status"],
        "applicant": _safe_text(applicant) or "Não informado",
        "purpose": _safe_text(purpose) or "Não informado",
        "target_col": _safe_text(target.get("column") or ""),
        "target_estimand": _safe_text(target.get("estimand") or ""),
        "unit": unit,
        "unit_pending": unit_pending,
        "unit_display": unit if unit else _pending("unidade do valor-alvo não informada"),
        "reference_date": reference_date,
        "reference_date_display": reference_date or _pending("data-base não informada"),
        "inspection_date": inspection_date,
        "inspection_date_display": inspection_date or _pending("data de vistoria não informada"),
        "generated_at": generated_at or _pending("data de emissão da minuta não informada"),
        "generated_at_raw": generated_at,
        "sources": sources,
        "technical_sources": technical_sources,
        "job_id": _safe_text(job_id),
        "project_id": _safe_text(project_id),
        "priority_limitations": priority_limitations,
        "point": point,
        "point_display": format_value_with_unit(point, unit) if not unit_pending else (
            format_snapshot_number(point) if point is not None else "—"
        ),
        "point_raw": format_snapshot_number(point),
        "cost_route": bool(cost_result),
        "cost_memory": cost_memory,
        "cost_memory_rows": [
            {
                "key": key,
                "label": label,
                "raw": format_snapshot_number(cost_memory.get(key)),
                "display": (
                    f"{_fmt_pt_br(cost_memory.get(key) * 100, 4)}%"
                    if key.endswith("_rate") and _as_finite_number(cost_memory.get(key)) is not None
                    else format_value_with_unit(cost_memory.get(key), unit)
                ),
            }
            for key, label in cost_labels
            if cost_memory.get(key) is not None
        ],
        "cost_items": [_redact_mapping(item) for item in _as_list(cost_result.get("items")) if isinstance(item, Mapping)],
        "cost_fundamentacao": _redact_mapping(cost_result.get("fundamentacao")),
        "adopted_value": adopted_point,
        "adopted_value_display": (
            format_value_with_unit(adopted_point, unit) if adopted_point is not None and not unit_pending else (
                format_snapshot_number(adopted_point) if adopted_point is not None else "Não adotado"
            )
        ),
        "adopted_value_reason": adopted_reason or "Política de adoção não declarada",
        "mean_ci80": mean_ci80,
        "mean_ci80_display": _interval_display(mean_ci80, unit if not unit_pending else None),
        "prediction_interval": prediction_interval,
        "prediction_interval_display": _interval_display(
            prediction_interval, unit if not unit_pending else None
        ),
        "arbitration_interval": arbitration_interval,
        "arbitration_interval_display": _interval_display(
            arbitration_interval, unit if not unit_pending else None
        ),
        "admissible_interval": admissible_interval,
        "admissible_interval_display": _interval_display(
            admissible_interval, unit if not unit_pending else None
        ),
        "n_received": n_received if n_received is not None else "—",
        "n_observed": n_observed if n_observed is not None else "—",
        "n_prepared": n_prepared if n_prepared is not None else "—",
        "n_used": n_used if n_used is not None else "—",
        "n_excluded": n_excluded if n_excluded is not None else "—",
        "used_ids": used_ids,
        "excluded_ids": excluded_ids,
        "used_ids_joined": " ".join(used_ids),
        "excluded_ids_joined": " ".join(excluded_ids),
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "used_value_columns": used_value_columns,
        "excluded_value_columns": excluded_value_columns,
        "used_count_mismatch": (
            n_used is not None and used_ids and int(n_used) != len(used_ids)
        ),
        "excluded_count_mismatch": (
            n_excluded is not None and excluded_ids and int(n_excluded) != len(excluded_ids)
        ),
        "issues": issues,
        "issues_by_origin": issues_by_origin,
        "has_issues": bool(issues),
        "precisao_status": precisao_status,
        "precisao_status_label": PRECISION_STATUS_LABELS.get(precisao_status, precisao_status),
        "precisao_grade": precisao_grade,
        "precisao_amplitude_pct": amplitude_pct,
        "precisao_note": precisao_note,
        "grau_fundamentacao_label": grau_fundamentacao_label,
        "grau_fundamentacao_points": fundamentacao.get("points"),
        "grau_precisao_label": grau_precisao_label,
        "item_scores": item_scores,
        "documents": unique_docs,
        "documentary_attachments": documentary_attachments,
        "next_actions": next_actions,
        "search_exhaustive": search_exhaustive,
        "search_mode": _safe_text(search_mode) if search_mode else "",
        "search_approximate": approximate,
        "search_coverage_known": search_info["coverage_known"],
        "search_budget": (
            _safe_text(search_info["budget"]) if search_info["budget"] is not None else (
                _safe_text(search.get("budget")) if search.get("budget") is not None else ""
            )
        ),
        "search_coverage": (
            _safe_text(search_info["enumeration"])
            if search_info["enumeration"]
            else (_safe_text(search.get("coverage")) if search.get("coverage") is not None else "")
        ),
        "search_objective": _safe_text(search_info["objective"] or search.get("objective") or ""),
        "combinations_tested": search_info["evaluated"] or search.get("combinations_tested") or search.get("evaluated"),
        "search_possible": search_info["possible"],
        "search_summary": search_info["summary"],
        "search_message": _safe_text(search_info["message"] or search.get("message") or ""),
        "search_limitations": search_limitations,
        "inference_limitations": inference_limitations,
        "formula": _safe_text(equation["formula"]),
        "formula_display": _safe_text(equation["formula_display"]),
        "formula_storage": _safe_text(equation["formula_storage"]),
        "formula_source": equation["source"],
        "formula_present": equation["present"],
        "fitting_scale": equation["fitting_scale"],
        "formula_log_scale": equation["log_scale"],
        "formula_notes": equation["notes"],
        "transform_rows": equation["transform_rows"],
        "variable_meanings": equation["variable_meanings"],
        "coef_rows": _coef_rows(model),
        "metrics": metrics,
        "metrics_present": metrics["present"],
        "chart_series": chart_series,
        "chart_available": chart_series["plot"],
        "chart_absence_reason": chart_series["reason"],
        "chart_warning": chart_series.get("warning"),
        "external_validation": external_validation,
        "market_summary_rows": market_rows,
        "market_summary_n": market_n,
        "annexes": annexes,
        "subject_items": subject_items,
        "has_subject": bool(subject_items),
        "asset_identification_display": asset_identification_display or _pending("identificação do bem não informada"),
        "rights_display": _safe_text(rights) or _pending("direitos avaliados não informados"),
        "region_characterization": _safe_text(ctx.get("region_characterization") or ""),
        "property_characterization": _safe_text(ctx.get("property_characterization") or ""),
        "methodology_display": _safe_text(methodology) or _pending("justificativa metodológica não informada"),
        "assumptions": [_safe_text(x) for x in _as_list(ctx.get("assumptions"))],
        "professional_review_display": professional_review_display,
        "professional_identity": _redact_mapping(professional_identity),
        "professional_identity_display": professional_identity_display
        or "PENDENTE — qualificação legal do responsável não informada",
        "qualification_profile": qualification_profile,
        "qualification_profile_display": (
            " / ".join(
                part
                for part in (
                    _safe_text(qualification_profile.get("id")),
                    _safe_text(qualification_profile.get("version")),
                    _safe_text(qualification_profile.get("recipient_id")),
                )
                if part
            )
            or "PENDENTE"
        ),
        "value_basis_display": _safe_text(qualification_profile.get("value_basis")) or "PENDENTE",
        "qualification_rules": qualification_rules,
        "result_fingerprint": document_state.get("result_fingerprint"),
        "institution_acceptance_display": institution_acceptance_display,
        "digital_signature": document_state.get("signature") or {},
        "alternatives": alternatives,
        "model_id": _safe_text(model_id) if model_id else "",
        "model_revision": _safe_text(model_revision) if model_revision else "",
        "display_rounding_decimals": DISPLAY_ROUNDING_DECIMALS,
        "model_sha": _safe_text(model_sha) if model_sha else "",
        "code_sha": _safe_text(code_sha) if code_sha else "",
        "input_sha256": _safe_text(input_sha) if input_sha else "",
        "provenance_safe": provenance_for_report,
        "frozen": frozen,
        "frozen_lines": frozen_lines,
        "charts": {},
        "chart_b64": None,
        "unit_is_brl": (not unit_pending) and _unit_is_brl(unit),
        "unit_is_brl_m2": (not unit_pending) and _unit_is_brl_per_m2(unit),
        "legacy_exhaustive": search_exhaustive,
        "legacy_combinations_tested": search.get("combinations_tested"),
        "legacy_search_message": search.get("message") or "",
    }
    return view


def _figure_to_base64() -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    plt.close()
    return encoded


def _charts_from_series(
    fitted: Any,
    residuals: Any,
    observed: Any = None,
    *,
    axis_fitted: str = "Valores ajustados",
    axis_resid: str = "Resíduos",
    axis_observed: str = "Valores observados",
) -> Dict[str, str]:
    charts: Dict[str, str] = {}
    fitted_arr = np.asarray(fitted, dtype=float) if fitted is not None else np.array([])
    resid_arr = np.asarray(residuals, dtype=float) if residuals is not None else np.array([])
    if fitted_arr.size == 0 or resid_arr.size == 0:
        return charts
    if observed is None:
        observed_arr = fitted_arr + resid_arr
    else:
        observed_arr = np.asarray(observed, dtype=float)

    plt.figure(figsize=_CHART_FIGSIZE)
    sns.scatterplot(x=fitted_arr, y=resid_arr)
    plt.axhline(y=0, color="r", linestyle="--")
    plt.xlabel(axis_fitted)
    plt.ylabel(axis_resid)
    plt.title("Resíduos versus valores ajustados")
    plt.tight_layout()
    charts["residuals_vs_fitted"] = _figure_to_base64()

    plt.figure(figsize=_CHART_FIGSIZE)
    sns.histplot(resid_arr, kde=True)
    plt.xlabel(axis_resid)
    plt.ylabel("Frequência")
    plt.title("Histograma dos resíduos")
    plt.tight_layout()
    charts["residuals_hist"] = _figure_to_base64()

    plt.figure(figsize=_CHART_FIGSIZE)
    sns.scatterplot(x=observed_arr, y=fitted_arr)
    min_val = float(min(observed_arr.min(), fitted_arr.min()))
    max_val = float(max(observed_arr.max(), fitted_arr.max()))
    plt.plot([min_val, max_val], [min_val, max_val], color="r", linestyle="--", label="Bissetriz (y = x)")
    plt.xlabel(axis_observed)
    plt.ylabel(axis_fitted)
    plt.title("Observado versus estimado")
    plt.legend()
    plt.tight_layout()
    charts["observed_vs_estimated"] = _figure_to_base64()
    return charts


def _attach_charts(
    view: Dict[str, Any],
    report_context: Optional[Mapping[str, Any]],
    model_result: Optional[ModelResult] = None,
    provided_charts: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    charts: Dict[str, str] = {}
    if provided_charts:
        charts.update({k: v for k, v in provided_charts.items() if v})
    ctx = _as_mapping(report_context)
    if ctx.get("charts") and isinstance(ctx.get("charts"), Mapping):
        charts.update({k: v for k, v in ctx["charts"].items() if v})
    series = view.get("chart_series") or assess_chart_series(
        ctx, used_row_ids=view.get("used_ids") or []
    )
    view["chart_series"] = series
    view["chart_available"] = bool(series.get("plot"))
    view["chart_absence_reason"] = series.get("reason") or ""
    view["chart_warning"] = series.get("warning")
    if series.get("warning"):
        warning_issue = _issue_dict(
            {
                "code": series["warning"].get("code") or "REPORT_CHARTS_MISALIGNED",
                "severity": "warning",
                "origin": "report",
                "message": (
                    f"{series['warning'].get('message')}. Os gráficos não foram plotados. "
                    "O cálculo do snapshot permanece inalterado."
                ),
                "affected_ids": [],
                "evidence": {"chart": True},
            }
        )
        existing_codes = {i.get("code") for i in view.get("issues") or []}
        if warning_issue["code"] not in existing_codes:
            view.setdefault("issues", []).append(warning_issue)
            bucket = warning_issue["origin_bucket"]
            view.setdefault("issues_by_origin", {}).setdefault(bucket, []).append(warning_issue)
            view["has_issues"] = True
    if series.get("plot") and (
        not charts.get("observed_vs_estimated") or not charts.get("residuals_vs_fitted")
    ):
        try:
            generated = _charts_from_series(
                series.get("fitted"),
                series.get("residuals"),
                series.get("observed"),
                axis_fitted=series.get("axis_fitted") or "Valores ajustados",
                axis_resid=series.get("axis_resid") or "Resíduos",
                axis_observed=series.get("axis_observed") or "Valores observados",
            )
            for key, val in generated.items():
                charts.setdefault(key, val)
        except Exception as exc:  # charts must not abort a valid snapshot PDF
            logger.error("Error generating report charts: %s", exc)
            view.setdefault("issues", []).append(
                _issue_dict(
                    {
                        "code": "C08_CHARTS_FAILED",
                        "severity": "warning",
                        "origin": "C08",
                        "message": f"Gráficos não gerados: {type(exc).__name__}: {exc}",
                        "affected_ids": [],
                        "evidence": {},
                    }
                )
            )
    elif (not series.get("plot")) and model_result is not None and not charts:
        try:
            generated = ResultsGenerator.generate_charts(model_result)
            for key, val in generated.items():
                charts.setdefault(key, val)
        except Exception as exc:
            logger.error("Error generating report charts: %s", exc)
    view["charts"] = charts
    view["chart_b64"] = charts.get("observed_vs_estimated")
    return view


def compose_report_html(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
    *,
    view: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render the HTML string that `render_report` feeds to WeasyPrint."""
    import jinja2

    resolved = dict(view) if view is not None else build_report_view(snapshot, report_context)
    try:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )
        template = env.get_template("report.html")
        return template.render(**resolved)
    except Exception as exc:
        raise ReportRenderError(
            f"Falha ao compor HTML do relatório: {type(exc).__name__}: {exc}",
            code="C08_HTML_COMPOSE_FAILED",
            evidence={"exception_type": type(exc).__name__},
        ) from exc


def _write_pdf(html_content: str) -> bytes:
    try:
        import weasyprint
    except Exception as exc:
        raise ReportRenderError(
            f"Motor de PDF indisponível: {type(exc).__name__}: {exc}",
            code="C08_PDF_ENGINE_UNAVAILABLE",
            evidence={"exception_type": type(exc).__name__},
        ) from exc
    try:
        pdf_bytes = weasyprint.HTML(string=html_content, encoding="utf-8").write_pdf()
    except Exception as exc:
        raise ReportRenderError(
            f"Falha ao renderizar PDF: {type(exc).__name__}: {exc}",
            code="C08_PDF_ENGINE_FAILED",
            evidence={"exception_type": type(exc).__name__, "exception_message": str(exc)},
        ) from exc
    if pdf_bytes is None:
        raise ReportRenderError(
            "Motor de PDF devolveu None — documento não entregue",
            code="C08_PDF_EMPTY",
        )
    pdf_bytes = bytes(pdf_bytes)
    if not pdf_bytes:
        raise ReportRenderError(
            "Motor de PDF devolveu documento vazio — documento não entregue",
            code="C08_PDF_EMPTY",
        )
    if not pdf_bytes.startswith(b"%PDF"):
        raise ReportRenderError(
            "Motor de PDF devolveu bytes que não são PDF — documento não entregue",
            code="C08_PDF_INVALID",
            evidence={"prefix": pdf_bytes[:8].decode("latin-1", errors="replace")},
        )
    return pdf_bytes


def render_report(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> bytes:
    """Build the review-ready PDF from an MP/1 ResultSnapshot.

    Returns PDF bytes. Never returns None. Raises ReportRenderError on failure.
    Does not fit or recalculate a regression.
    """
    view = build_report_view(snapshot, report_context)
    if (
        view.get("case_release_status") == "signed_integrity_verified"
        and view.get("document_is_final")
    ):
        raise ReportRenderError(
            "A revisão assinada não pode ser renderizada novamente; entregue os bytes assinados já vinculados.",
            code="C03_SIGNED_REVISION_IMMUTABLE",
            origin="C03",
            evidence={"result_fingerprint": view.get("result_fingerprint")},
        )
    view = _attach_charts(view, report_context)
    html_content = compose_report_html(snapshot, report_context, view=view)
    return _write_pdf(html_content)


def _legacy_model_result_to_snapshot(
    model_result: ModelResult,
    *,
    target_col: str = "",
    avaliando_raw: Optional[Dict[str, float]] = None,
    solicitante: str = "",
    finalidade: str = "",
    exhaustive: Optional[bool] = None,
    combinations_tested: Optional[int] = None,
    search_message: str = "",
    market_summary: Optional[dict] = None,
    market_data: Optional[pd.DataFrame] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Adapt a legacy ModelResult into an MP/1-shaped snapshot + context.

    Copies stored fields only. Does not invert campo-de-arbítrio bounds to
    recover a point estimate, and does not stamp datetime.now() as data-base.
    """
    validation_result = getattr(model_result, "validation_result", None)
    details = dict(getattr(validation_result, "details", None) or {}) if validation_result else {}

    # Point must already be stored; never reconstruct from interval strings.
    point = details.get("central_estimate")
    if point is None:
        point = details.get("point")
    if point is None:
        point = details.get("predicted_mean")
    point = _as_finite_number(point)

    ic_lo = _as_finite_number(details.get("ic80_inferior"))
    ic_hi = _as_finite_number(details.get("ic80_superior"))
    arb_lo = _as_finite_number(details.get("campo_arbitrio_inferior"))
    arb_hi = _as_finite_number(details.get("campo_arbitrio_superior"))
    adm_lo = _as_finite_number(
        getattr(validation_result, "valores_admissiveis_inferior", None) if validation_result else None
    )
    adm_hi = _as_finite_number(
        getattr(validation_result, "valores_admissiveis_superior", None) if validation_result else None
    )

    issues: List[Dict[str, Any]] = []
    if validation_result:
        for warning in getattr(validation_result, "warnings", None) or []:
            issues.append(
                {
                    "code": "LEGACY_VALIDATION_WARNING",
                    "severity": "warning",
                    "origin": "normative",
                    "message": str(warning),
                    "affected_ids": [],
                    "evidence": {},
                }
            )
        for message in getattr(validation_result, "messages", None) or []:
            issues.append(
                {
                    "code": "LEGACY_VALIDATION_MESSAGE",
                    "severity": "info",
                    "origin": "normative",
                    "message": str(message),
                    "affected_ids": [],
                    "evidence": {},
                }
            )

    grau_precisao = getattr(validation_result, "grau_precisao", None) if validation_result else None
    amplitude_pct = (
        getattr(validation_result, "precisao_amplitude_pct", None) if validation_result else None
    )
    if grau_precisao is not None:
        precisao_status = "classified"
    elif amplitude_pct is not None:
        precisao_status = "unclassified"
    else:
        precisao_status = "not_computed"

    item_scores = []
    if validation_result and getattr(validation_result, "item_scores", None):
        for item in sorted(validation_result.item_scores, key=lambda i: i.item):
            item_scores.append(
                {
                    "item": item.item,
                    "description": item.description,
                    "grade": item.grau_achieved,
                    "detail": item.detail,
                    "evidence_status": "declared",
                }
            )

    mm = getattr(model_result, "model_metrics", None)
    metrics = {}
    if mm:
        metrics = {
            "r2": mm.r2,
            "r2_adjusted": mm.r2_adjusted,
            "f_statistic": mm.f_statistic,
            "f_pvalue": mm.f_pvalue,
            "durbin_watson": mm.autocorrelation_durbin_watson,
        }

    used_rows = []
    used_ids = []
    if market_data is not None and not getattr(market_data, "empty", True):
        display_df = market_data
        columns = [str(c) for c in display_df.columns]
        for idx, row in enumerate(display_df.itertuples(index=True)):
            raw_index = row[0]
            values = {}
            for col, val in zip(columns, row[1:]):
                values[col] = "" if pd.isna(val) else val
            rid = None
            for key in ("row_id", "id"):
                if key in values and values[key] not in (None, ""):
                    rid = str(values[key])
                    break
            if rid is None:
                rid = str(raw_index)
            used_ids.append(rid)
            used_rows.append(
                {
                    "row_id": rid,
                    "source": "planilha de mercado (adaptador legado)",
                    "justification": "Registro fornecido em market_data",
                    "values": values,
                    "label": str(values.get("nome") or values.get("endereco") or ""),
                }
            )

    generated_at = None
    timestamp = getattr(model_result, "timestamp", None)
    if isinstance(timestamp, datetime):
        generated_at = timestamp.isoformat()
    elif timestamp:
        generated_at = str(timestamp)

    snapshot = {
        "schema_version": "MP/1",
        "job_id": "legacy-adapter",
        "project_id": None,
        "input_sha256": "",
        "code_sha": "",
        "reference_date": None,
        "inspection_date": None,
        "generated_at": generated_at,
        "target": {
            "column": target_col or "",
            "unit": "",
            "estimand": "estimativa pontual da média condicional (legado, unidade não confirmada)",
        },
        "value": {
            "point": point,
            "mean_ci80": {"lower": ic_lo, "upper": ic_hi} if ic_lo is not None or ic_hi is not None else None,
            "prediction_interval": None,
            "arbitration_interval": {"lower": arb_lo, "upper": arb_hi}
            if arb_lo is not None or arb_hi is not None
            else None,
            "admissible_interval": {"lower": adm_lo, "upper": adm_hi}
            if adm_lo is not None or adm_hi is not None
            else None,
        },
        "sample": {
            "received": len(used_ids) if used_ids else None,
            "observed_target": len(used_ids) if used_ids else None,
            "prepared": len(used_ids) if used_ids else None,
            "used": len(used_ids) if used_ids else None,
            "excluded": 0,
            "used_row_ids": used_ids,
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {
                "grade": getattr(validation_result, "grau_fundamentacao", None) if validation_result else None,
                "points": getattr(validation_result, "grau_fundamentacao_pontos", None)
                if validation_result
                else None,
                "items": item_scores,
            },
            "precisao": {
                "status": precisao_status,
                "grade": grau_precisao,
                "amplitude_pct": amplitude_pct,
            },
            "statistical": {},
            "documentary": {"declared": [], "present": [], "verified": []},
            "issuance": {
                "status": "review_required",
                "reasons": [
                    "Adaptador legado: ModelResult não é um ResultSnapshot MP/1 completo",
                    "Data-base e unidade do alvo não persistidas no resultado legado",
                ],
            },
        },
        "issues": issues,
        "model": {
            "model_id": "legacy-ModelResult",
            "revision": None,
            "formula": getattr(model_result, "formula", "") or "",
            "coefficients": dict(getattr(model_result, "coefficients", None) or {}),
            "pvalues": dict(getattr(model_result, "pvalues", None) or {}),
            "vif": dict(getattr(model_result, "vif", None) or {}),
            "metrics": metrics,
        },
        "search": {
            "exhaustive": exhaustive,
            "mode": None if exhaustive is None else ("exhaustive" if exhaustive else "approximate"),
            "combinations_tested": combinations_tested,
            "message": search_message or "",
            "limitations": []
            if exhaustive is not False
            else [
                "Busca aproximada: o espaço excedeu o limite combinatório e recorreu ao fallback documentado."
            ],
        },
        "alternatives": [],
        "next_actions": [
            {
                "code": "PROVIDE_MP1_SNAPSHOT",
                "priority": "high",
                "reason": "Este PDF veio do adaptador legado generate_pdf_report",
                "next_step": "C10 deve chamar render_report com ResultSnapshot e report_context integrais",
                "evidence_refs": [],
                "limitations": "O adaptador não reconstrói o ponto a partir do campo de arbítrio",
            }
        ],
        "provenance": {
            "adapter": "generate_pdf_report",
            "source": "ModelResult",
        },
        "applicant": solicitante,
        "purpose": finalidade,
    }

    descriptive = None
    if market_summary and market_summary.get("variables"):
        descriptive = {
            "n": market_summary.get("n"),
            "variables": list(market_summary["variables"]),
        }

    context = {
        "applicant": solicitante,
        "purpose": finalidade,
        "used_rows": used_rows,
        "excluded_rows": [],
        "market_descriptive": descriptive,
        "subject": dict(avaliando_raw) if avaliando_raw else {},
        "documents": [],
        "sources": [],
        "inference_limitations": [
            "Adaptador legado: estimativa pontual só aparece se já estiver persistida no ModelResult; "
            "não é recuperada por inversão de intervalos."
        ],
    }
    return snapshot, context


class ResultsGenerator:
    @staticmethod
    def generate_charts(model_result: ModelResult) -> Dict[str, str]:
        """Generate print-sized residual charts with Portuguese legends."""
        charts: Dict[str, str] = {}
        if not model_result or not getattr(model_result, "success", False) or not model_result.model_metrics:
            return charts
        try:
            return _charts_from_series(
                model_result.fitted_values,
                model_result.residuals,
            )
        except Exception as exc:
            logger.error("Error generating charts: %s", exc)
            return charts

    @staticmethod
    def build_market_summary(
        df: pd.DataFrame, variable_cols: Optional[List[str]] = None
    ) -> Optional[dict]:
        """Optional descriptive min/mean/median/max helper for the adapter.

        This is a sample descriptive, not a complete market diagnosis.
        """
        if df is None or df.empty:
            return None
        cols = variable_cols if variable_cols else list(df.select_dtypes(include=[np.number]).columns)
        variables = []
        for col in cols:
            if col not in df.columns:
                continue
            series = pd.to_numeric(df[col], errors="coerce")
            if series.notna().sum() == 0:
                continue
            variables.append(
                {
                    "name": col,
                    "min": float(series.min()),
                    "mean": float(series.mean()),
                    "median": float(series.median()),
                    "max": float(series.max()),
                }
            )
        if not variables:
            return None
        return {"n": len(df), "variables": variables}

    @staticmethod
    def generate_pdf_report(
        model_result: ModelResult,
        target_col: str = "",
        avaliando_raw: Optional[Dict[str, float]] = None,
        solicitante: str = "",
        finalidade: str = "",
        exhaustive: Optional[bool] = None,
        combinations_tested: Optional[int] = None,
        search_message: str = "",
        market_summary: Optional[dict] = None,
        charts: Optional[Dict[str, str]] = None,
        market_data: Optional[pd.DataFrame] = None,
    ) -> Optional[bytes]:
        """Legacy adapter: ModelResult → render_report.

        Invalid/incomplete ModelResult still returns None so C16 and the
        current worker path keep their documented behaviour. MP/1 callers
        must use `render_report`, which never returns None.
        """
        try:
            if model_result is None or not hasattr(model_result, "validation_result"):
                logger.error("Error generating PDF report: invalid ModelResult")
                return None
            snapshot, context = _legacy_model_result_to_snapshot(
                model_result,
                target_col=target_col,
                avaliando_raw=avaliando_raw,
                solicitante=solicitante,
                finalidade=finalidade,
                exhaustive=exhaustive,
                combinations_tested=combinations_tested,
                search_message=search_message,
                market_summary=market_summary,
                market_data=market_data,
            )
            view = build_report_view(snapshot, context)
            view = _attach_charts(
                view,
                context,
                model_result=model_result,
                provided_charts=charts,
            )
            html_content = compose_report_html(snapshot, context, view=view)
            return _write_pdf(html_content)
        except ReportRenderError as exc:
            logger.error("Error generating PDF report: %s", exc)
            return None
        except Exception as exc:
            logger.error("Error generating PDF report: %s", exc)
            return None

    @staticmethod
    def render_report(
        snapshot: Mapping[str, Any],
        report_context: Optional[Mapping[str, Any]] = None,
    ) -> bytes:
        return render_report(snapshot, report_context)
