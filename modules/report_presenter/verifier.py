"""Check a rendered minuta against the snapshot it claims to copy.

Detects mutated value, unit, grau, omitted annex line, and incoherent equation.
Not a second valuation engine: it only compares PDF/view text to snapshot fields.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional

from ..provenance import canonical_json
from .formula import compose_model_equation
from .qualification import assess_document_state


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
        if not line.startswith(("MP1_", "MPQUAL_", "MPSAMPLE_")):
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


def _finding(
    code: str, field: str, expected: Any, observed: Any, message: str
) -> Dict[str, Any]:
    return {
        "code": code,
        "field": field,
        "expected": expected,
        "observed": observed,
        "message": message,
    }


def _contains_pdf_text(text: str, expected: str) -> bool:
    if expected in text:
        return True
    return "".join(expected.split()) in "".join(text.split())


def _equation_coherent(text: str, model: Mapping[str, Any], target_col: str) -> bool:
    composed = compose_model_equation(model, target_col=target_col)
    if not composed["present"]:
        return True
    blob = text.replace(" ", "").replace("·", "*").replace("−", "-")
    pairs = composed.get("coefficient_pairs") or []
    if not pairs:
        formula = (composed.get("formula") or "").replace(" ", "")
        return (not formula) or formula in blob or composed["formula"] in text
    for name, value in pairs:
        if str(name) not in text and str(name).lower() not in text.lower():
            return False
        storage = format_storage_number(value)
        if storage not in text and format(value, ".15g") not in text:
            return False
    return True


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

    frozen_snapshot_checks = {
        "MP1_REFERENCE_DATE": str(snap.get("reference_date") or "PENDENTE"),
        "MP1_INSPECTION_DATE": str(
            snap.get("inspection_date")
            or _as_mapping(report_context).get("inspection_date")
            or "PENDENTE"
        ),
        "MP1_N_RECEIVED": format_storage_number(sample.get("received")),
        "MP1_N_OBSERVED": format_storage_number(sample.get("observed_target")),
        "MP1_N_PREPARED": format_storage_number(sample.get("prepared")),
        "MP1_N_USED": format_storage_number(
            sample.get("used")
            if sample.get("used") is not None
            else len(_as_list(sample.get("used_row_ids")))
        ),
        "MP1_N_EXCLUDED": format_storage_number(
            sample.get("excluded")
            if sample.get("excluded") is not None
            else len(_as_list(sample.get("excluded_row_ids")))
        ),
    }
    for key, expected in frozen_snapshot_checks.items():
        observed = frozen.get(key)
        if observed != expected:
            code = (
                "MUTATED_DATE"
                if key in {"MP1_REFERENCE_DATE", "MP1_INSPECTION_DATE"}
                else "MUTATED_SAMPLE_COUNT"
            )
            findings.append(
                _finding(
                    code,
                    key,
                    expected,
                    observed,
                    "Marcador MP/1 do PDF não coincide com o snapshot.",
                )
            )

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

    adopted = value.get("adopted_value", value.get("adopted"))
    if isinstance(adopted, Mapping):
        adopted = adopted.get("point", adopted.get("value"))
    expected_adopted = format_storage_number(adopted)
    if frozen.get("MP1_ADOPTED_VALUE") != expected_adopted:
        findings.append(
            _finding(
                "MUTATED_ADOPTED_VALUE",
                "value.adopted_value",
                expected_adopted,
                frozen.get("MP1_ADOPTED_VALUE"),
                "O valor adotado no PDF não coincide com o snapshot.",
            )
        )

    interval_fields = {
        "mean_ci80": ("MP1_MEAN_CI80_LOWER", "MP1_MEAN_CI80_UPPER"),
        "prediction_interval": ("MP1_PRED_LOWER", "MP1_PRED_UPPER"),
        "arbitration_interval": ("MP1_ARB_LOWER", "MP1_ARB_UPPER"),
        "admissible_interval": ("MP1_ADM_LOWER", "MP1_ADM_UPPER"),
    }
    for field, (lower_key, upper_key) in interval_fields.items():
        interval = _as_mapping(value.get(field))
        expected_lower = format_storage_number(interval.get("lower"))
        expected_upper = format_storage_number(interval.get("upper"))
        if (
            frozen.get(lower_key) != expected_lower
            or frozen.get(upper_key) != expected_upper
        ):
            findings.append(
                _finding(
                    "MUTATED_INTERVAL",
                    f"value.{field}",
                    {"lower": expected_lower, "upper": expected_upper},
                    {"lower": frozen.get(lower_key), "upper": frozen.get(upper_key)},
                    f"O intervalo {field} no PDF não coincide com o snapshot.",
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
        if (
            observed_grade not in {None, expected_grade, label, "PENDENTE"}
            and observed_grade != expected_grade
        ):
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
    from ..results_generator import build_report_view

    view = build_report_view(snap, ctx)
    compact_text = "".join(text.split())
    for rows_key in ("used_rows", "excluded_rows"):
        for row in view.get(rows_key) or []:
            ordered = [
                row.get("seq"),
                row.get("row_id"),
                row.get("source"),
                row.get("justification"),
            ]
            if rows_key == "used_rows":
                ordered.append(row.get("label"))
            ordered.extend(row.get("value_cells") or [])
            expected_row = "".join(
                "".join(str(value or "").split()) for value in ordered
            )
            if expected_row and expected_row not in compact_text:
                findings.append(
                    _finding(
                        "MUTATED_SAMPLE_ROW",
                        f"report_context.{rows_key}.{row.get('row_id')}",
                        expected_row,
                        None,
                        "A linha renderizada não preserva fonte, justificativa e valores efetivos.",
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

    state = assess_document_state(snap, report_context)
    profile = _as_mapping(state.get("profile"))
    qualification_checks = {
        "MPQUAL_PROFILE_ID": str(profile.get("id") or "PENDENTE"),
        "MPQUAL_PROFILE_VERSION": str(profile.get("version") or "PENDENTE"),
        "MPQUAL_VALUE_BASIS": str(profile.get("value_basis") or "PENDENTE"),
        "MPQUAL_RELEASE_STATUS": str(
            state.get("case_release_status") or "analysis_only"
        ),
        "MPQUAL_GRADE_REQUIREMENT": str(
            state.get("grade_requirement_status") or "pending"
        ),
        "MPQUAL_RESULT_FINGERPRINT": str(state.get("result_fingerprint") or "PENDENTE"),
        "MPQUAL_REPORT_CONTENT_FINGERPRINT": str(
            state.get("report_content_fingerprint") or "PENDENTE"
        ),
        "MPQUAL_REVIEW_EVENTS": str(len(state.get("review_events") or [])),
        "MPQUAL_RULES_SHA256": hashlib.sha256(
            canonical_json(state.get("rule_results") or []).encode("utf-8")
        ).hexdigest(),
        "MPQUAL_REVIEW_SHA256": hashlib.sha256(
            canonical_json(state.get("review_events") or []).encode("utf-8")
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
    for key, expected in qualification_checks.items():
        observed = frozen.get(key)
        if observed != expected:
            code = (
                "MUTATED_REVIEW"
                if key in {"MPQUAL_REVIEW_EVENTS", "MPQUAL_REVIEW_SHA256"}
                else "MUTATED_PROFILE"
            )
            if key == "MPQUAL_RULES_SHA256":
                code = "MUTATED_QUALIFICATION_RULES"
            if key == "MPSAMPLE_ROWS_SHA256":
                code = "MUTATED_SAMPLE_ROW"
            findings.append(
                _finding(
                    code,
                    key,
                    expected,
                    observed,
                    "Marcador MP-QUAL do PDF não coincide com o snapshot.",
                )
            )

    for rule in state.get("rule_results") or []:
        if not isinstance(rule, Mapping):
            continue
        for field in ("rule_id", "source_id", "edition_or_version", "clause", "status"):
            expected = str(rule.get(field) or "").strip()
            if expected and not _contains_pdf_text(text, expected):
                findings.append(
                    _finding(
                        "OMITTED_QUALIFICATION_RULE_FIELD",
                        f"rule_results.{rule.get('rule_id')}.{field}",
                        expected,
                        None,
                        "Campo de regra qualificada ausente do PDF.",
                    )
                )
                break

    for index, attachment in enumerate(
        ctx.get("documentary_files")
        or ctx.get("photos")
        or ctx.get("attachments")
        or []
    ):
        if not isinstance(attachment, Mapping):
            continue
        name = str(
            attachment.get("filename") or attachment.get("name") or f"anexo-{index + 1}"
        )
        content = attachment.get("bytes") or attachment.get("content")
        expected_digest = (
            hashlib.sha256(bytes(content)).hexdigest()
            if isinstance(content, (bytes, bytearray))
            else str(attachment.get("sha256") or "")
        )
        if name not in text or (expected_digest and expected_digest not in text):
            findings.append(
                _finding(
                    "OMITTED_DOCUMENTARY_ATTACHMENT",
                    f"report_context.documentary_files[{index}]",
                    {"name": name, "sha256": expected_digest},
                    None,
                    "Mapa de documento/fotografia autorizado ausente do PDF.",
                )
            )

    return {"ok": not findings, "findings": findings, "frozen": frozen}
