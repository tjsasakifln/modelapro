"""Check a rendered minuta against the snapshot it claims to copy.

Detects mutated value, unit, grau, omitted annex line, and incoherent equation.
Not a second valuation engine: it only compares PDF/view text to snapshot fields.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional

from .formula import compose_model_equation


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def format_storage_number(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return "null"
    if abs(number) >= 1e15:
        return format(number, ".15g")
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def parse_frozen_lines(text: str) -> Dict[str, str]:
    frozen: Dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip().replace("\x00", "")
        if not line.startswith("MP1_"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            frozen[key.strip()] = value.strip()
    return frozen


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text.replace("\x00", "")


_GRAU_LABELS = {1: "Grau I", 2: "Grau II", 3: "Grau III"}


def _finding(code: str, field: str, expected: Any, observed: Any, message: str) -> Dict[str, Any]:
    return {
        "code": code,
        "field": field,
        "expected": expected,
        "observed": observed,
        "message": message,
    }


def _equation_coherent(text: str, model: Mapping[str, Any], target_col: str) -> bool:
    composed = compose_model_equation(model, target_col=target_col)
    if not composed["present"]:
        return True
    blob = text.replace(" ", "").replace("·", "*").replace("−", "-")
    pairs = composed.get("coefficient_pairs") or []
    if not pairs:
        formula = (composed.get("formula") or "").replace(" ", "")
        return (not formula) or formula in blob or composed["formula"] in text
    names_ok = True
    values_ok = False
    for name, value in pairs:
        if str(name) not in text and str(name).lower() not in text.lower():
            names_ok = False
        storage = format_storage_number(value)
        display = f"{value:.6f}" if not float(value).is_integer() else str(int(value))
        if storage in text or display in text or format(value, ".15g") in text:
            values_ok = True
    return bool(names_ok and values_ok)


def verify_report_consistency(
    pdf_bytes: bytes,
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
    *,
    extracted_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare rendered PDF text to snapshot fields.

    Returns ``{"ok": bool, "findings": list}``. A clean render of the matching
    snapshot has no findings. Mutations of value, unit, grau, annex line or
    equation are reported individually.
    """
    if extracted_text is None:
        extracted_text = extract_pdf_text(pdf_bytes)
    text = extracted_text.replace("\x00", "")
    snap = _as_mapping(snapshot)
    value = _as_mapping(snap.get("value"))
    target = _as_mapping(snap.get("target"))
    sample = _as_mapping(snap.get("sample"))
    validation = _as_mapping(snap.get("validation"))
    fund = _as_mapping(validation.get("fundamentacao"))
    model = _as_mapping(snap.get("model"))
    frozen = parse_frozen_lines(text)
    findings: List[Dict[str, Any]] = []

    expected_point = format_storage_number(value.get("point"))
    observed_point = frozen.get("MP1_POINT")
    if observed_point != expected_point:
        findings.append(
            _finding(
                "MUTATED_VALUE",
                "value.point",
                expected_point,
                observed_point,
                "O ponto congelado no PDF não coincide com snapshot.value.point.",
            )
        )

    expected_unit = str(target.get("unit") or "").strip() or "PENDENTE"
    observed_unit = frozen.get("MP1_TARGET_UNIT")
    if observed_unit != expected_unit and not (
        expected_unit in {"", "PENDENTE"} and observed_unit == "PENDENTE"
    ):
        findings.append(
            _finding(
                "MUTATED_UNIT",
                "target.unit",
                expected_unit,
                observed_unit,
                "A unidade congelada no PDF não coincide com snapshot.target.unit.",
            )
        )

    grade = fund.get("grade")
    observed_grade = frozen.get("MP1_FUNDAMENTACAO_GRADE")
    if grade in (1, 2, 3):
        expected_grade = str(int(grade))
        label = _GRAU_LABELS[int(grade)]
        if observed_grade not in {None, expected_grade, label, "PENDENTE"} and observed_grade != expected_grade:
            findings.append(
                _finding(
                    "MUTATED_GRAU",
                    "validation.fundamentacao.grade",
                    expected_grade,
                    observed_grade,
                    "O grau de fundamentação do snapshot não coincide com o PDF.",
                )
            )
        elif observed_grade in {None, "PENDENTE"} and label not in text:
            findings.append(
                _finding(
                    "MUTATED_GRAU",
                    "validation.fundamentacao.grade",
                    expected_grade,
                    observed_grade,
                    "O grau de fundamentação do snapshot não coincide com o PDF.",
                )
            )
    else:
        if observed_grade in {"1", "2", "3"}:
            findings.append(
                _finding(
                    "MUTATED_GRAU",
                    "validation.fundamentacao.grade",
                    "PENDENTE",
                    observed_grade,
                    "O PDF afirma um grau de fundamentação que o snapshot não classificou.",
                )
            )

    used_ids = [str(i) for i in _as_list(sample.get("used_row_ids"))]
    excluded_ids = [str(i) for i in _as_list(sample.get("excluded_row_ids"))]
    omitted = [rid for rid in used_ids + excluded_ids if rid and rid not in text]
    if omitted:
        findings.append(
            _finding(
                "OMITTED_ANNEX_LINE",
                "sample.used_row_ids/excluded_row_ids",
                omitted[:8],
                None,
                "Identificadores da amostra utilizada/excluída ausentes do PDF.",
            )
        )

    ctx = _as_mapping(report_context)
    for row in list(ctx.get("used_rows") or []) + list(ctx.get("excluded_rows") or []):
        if not isinstance(row, Mapping):
            continue
        rid = str(row.get("row_id") or row.get("id") or "")
        if rid and rid not in text:
            findings.append(
                _finding(
                    "OMITTED_ANNEX_LINE",
                    "report_context.rows",
                    rid,
                    None,
                    f"Linha {rid} do contexto não aparece no PDF.",
                )
            )
            break

    target_col = str(target.get("column") or "")
    if not _equation_coherent(text, model, target_col):
        findings.append(
            _finding(
                "INCOHERENT_EQUATION",
                "model.formula/coefficients",
                compose_model_equation(model, target_col=target_col).get("formula"),
                None,
                "A equação apresentada não reconcilia com os coeficientes canônicos do snapshot.",
            )
        )

    return {"ok": not findings, "findings": findings, "frozen": frozen}
