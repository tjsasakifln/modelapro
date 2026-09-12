"""Qualification-aware document state for MP-COM/2 reports.

This module consumes the additive ``provenance.qualification_context`` owned
by the qualification producers.  It does not recalculate a grade or turn a
human review into a technical rule result.  Its only decision is which label
the document may carry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..provenance import canonical_json

RULE_STATUSES = {
    "passed",
    "failed",
    "pending_manual",
    "not_applicable",
    "unsupported",
    "unverified",
    "error",
}
BLOCKING_RULE_STATUSES = {
    "failed",
    "pending_manual",
    "unsupported",
    "unverified",
    "error",
}
FINAL_RELEASE_STATES = {
    "ready_for_professional_signoff",
    "signed_integrity_verified",
}
CALCULATION_OK = {
    "valid",
    "calculated",
    "completed",
    "passed",
    "ok",
    "verified",
}
GRADE_OK = {"met", "not_requested"}
REVIEW_APPROVAL_EVENTS = {
    "approved",
    "review_approved",
    "professional_review_approved",
    "ready_for_signoff",
}
REVIEW_APPROVAL_DECISIONS = {"approved", "accepted", "ready_for_signoff"}
PROFILE_FIELDS = (
    "id",
    "version",
    "source_set_sha256",
    "purpose",
    "value_basis",
    "method",
    "asset_scope",
)
RULE_FIELDS = (
    "rule_id",
    "source_id",
    "edition_or_version",
    "clause",
    "applicability",
    "status",
    "observed",
    "criterion_ref",
    "evidence_refs",
    "explanation",
)


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (Mapping, list, tuple, set)):
        return len(value) == 0
    return False


def qualification_context(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = _mapping(snapshot.get("provenance"))
    return _mapping(provenance.get("qualification_context"))


def _fingerprint_value(value: Any) -> Any:
    """Return a JSON-safe representation without copying attachment bytes."""
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if isinstance(value, Mapping):
        return {
            str(key): _fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_fingerprint_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted((_fingerprint_value(item) for item in value), key=str)
    if hasattr(value, "tolist"):
        return _fingerprint_value(value.tolist())
    if hasattr(value, "item"):
        return _fingerprint_value(value.item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"type": type(value).__name__, "text": str(value)}


_EXTERNAL_SIGNATURE_RULE_ID = "bb.guiar.assinatura_icp"
_EXTERNAL_SIGNATURE_EVIDENCE = (
    "MP-OUTPUT-MANIFEST/1:representations.signed_report.pdf"
    "#assinatura-cadeia-validada"
)
_EXTERNAL_SIGNATURE_REQUIREMENT = (
    "Via de assinatura digital do PDF por certificado ICP-Brasil"
)
_EXTERNAL_SIGNATURE_PENDING_EXPLANATION = (
    _EXTERNAL_SIGNATURE_REQUIREMENT
    + " — a via de importação e verificação existe, mas os bytes assinados e a "
    "cadeia de confiança ainda não foram fornecidos nesta etapa. A pendência "
    "permite preparar os bytes para assinatura, mas impede o pacote final assinado."
)


def _normalize_external_signature_state(qctx: Dict[str, Any]) -> None:
    """Remove only lifecycle changes caused by receiving the signed bytes.

    The unsigned report must be fingerprinted before an external signature can
    exist.  Moving this one requirement from ``pending_manual`` to ``passed``
    therefore cannot change the material the signature binds.  Every other
    rule, declaration and output requirement remains byte-for-byte material.
    """

    def signature_phase(raw: Any) -> Optional[str]:
        if not isinstance(raw, Mapping) or raw.get("rule_id") != _EXTERNAL_SIGNATURE_RULE_ID:
            return None
        status = raw.get("status")
        observed = raw.get("observed")
        evidence = raw.get("evidence_refs")
        explanation = raw.get("explanation")
        if (
            status == "pending_manual"
            and observed is None
            and evidence == []
            and explanation == _EXTERNAL_SIGNATURE_PENDING_EXPLANATION
        ):
            return "pending"
        if (
            status == "passed"
            and observed == _EXTERNAL_SIGNATURE_EVIDENCE
            and isinstance(evidence, list)
            and evidence == [_EXTERNAL_SIGNATURE_EVIDENCE]
            and explanation == _EXTERNAL_SIGNATURE_REQUIREMENT
        ):
            return "verified"
        return None

    def normalize_rule(raw: Any) -> Any:
        rule = dict(raw)
        rule.update(
            {
                "status": "external_signature_stage",
                "observed": None,
                "evidence_refs": [],
                "explanation": "external signature state excluded from signable material",
            }
        )
        return rule

    if "rule_results" not in qctx:
        return
    top_rules = _list(qctx.get("rule_results"))
    output = _mapping(qctx.get("output_conformance"))
    if not output:
        return
    raw_output_rules = _list(output.get("rule_results"))
    top_matches = [rule for rule in top_rules if isinstance(rule, Mapping)
                   and rule.get("rule_id") == _EXTERNAL_SIGNATURE_RULE_ID]
    output_matches = [rule for rule in raw_output_rules if isinstance(rule, Mapping)
                      and rule.get("rule_id") == _EXTERNAL_SIGNATURE_RULE_ID]
    if len(top_matches) != 1 or len(output_matches) != 1:
        return
    phase = signature_phase(top_matches[0])
    if phase is None or signature_phase(output_matches[0]) != phase:
        return
    blockers = _list(output.get("blocking"))
    signature_blockers = [
        row for row in blockers
        if isinstance(row, Mapping)
        and row.get("requirement_id") == _EXTERNAL_SIGNATURE_RULE_ID
    ]
    awaiting = _list(output.get("awaiting_signature"))
    if phase == "pending":
        expected_blocker = {
            "code": "output_requirement_pending_signature",
            "requirement_id": _EXTERNAL_SIGNATURE_RULE_ID,
            "clause": top_matches[0].get("clause"),
            "detail": _EXTERNAL_SIGNATURE_PENDING_EXPLANATION,
            "owner": "profissional responsável / cadeia de confiança configurada",
            "stage": "post_review_external_signature",
        }
        if signature_blockers != [expected_blocker] or awaiting.count(
            _EXTERNAL_SIGNATURE_RULE_ID
        ) != 1:
            return
    elif signature_blockers or _EXTERNAL_SIGNATURE_RULE_ID in awaiting:
        return

    qctx["rule_results"] = [
        normalize_rule(rule) if rule is top_matches[0] else rule for rule in top_rules
    ]
    output_rules = [
        normalize_rule(rule) if rule is output_matches[0] else rule
        for rule in raw_output_rules
    ]
    output["rule_results"] = output_rules
    output["blocking"] = [
        row
        for row in blockers if row not in signature_blockers
    ]
    output["awaiting_signature"] = [
        item
        for item in awaiting
        if item != _EXTERNAL_SIGNATURE_RULE_ID
    ] + [_EXTERNAL_SIGNATURE_RULE_ID]
    output["conforming"] = sum(
        1
        for rule in output_rules
        if isinstance(rule, Mapping)
        and rule.get("rule_id") != _EXTERNAL_SIGNATURE_RULE_ID
        and rule.get("status") == "passed"
    )
    output["would_be_accepted_without_reservations"] = bool(
        not output["blocking"] and int(output.get("applicable_requirements") or 0) > 0
    )
    qctx["output_conformance"] = output


def report_content_fingerprint(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Identify the exact calculation and client-facing report inputs.

    Review, signature and release fields are excluded to avoid a circular
    fingerprint.  Attachment bytes are represented by their size and digest.
    """
    snap = _fingerprint_value(snapshot)
    provenance = _mapping(snap.get("provenance"))
    qctx = _mapping(provenance.get("qualification_context"))
    for field in (
        "review_events",
        "stale_review_events",
        "digital_signature",
        "report_content_fingerprint",
        "signed_bytes_sha256",
        "institution_acceptance",
        "case_release_status",
        "release_blockers",
        "pending_manual_rules",
        "claims",
    ):
        qctx.pop(field, None)
    _normalize_external_signature_state(qctx)
    if qctx:
        provenance["qualification_context"] = qctx
    snap["provenance"] = provenance
    validation = _mapping(snap.get("validation"))
    issuance = _mapping(validation.get("issuance"))
    # These are derived lifecycle labels. Including them would make the act of
    # recording a review change the content identity that the review binds.
    issuance.pop("status", None)
    issuance.pop("case_release_status", None)
    if issuance:
        validation["issuance"] = issuance
    else:
        validation.pop("issuance", None)
    snap["validation"] = validation
    ctx = _mapping(_fingerprint_value(report_context or {}))
    for field in (
        "digital_signature",
        "signed_pdf_bytes",
        "unsigned_pdf_bytes",
        "signature_validation_context",
    ):
        ctx.pop(field, None)
    material = {
        "schema_version": "MP-REPORT-CONTENT/1",
        "snapshot": snap,
        "report_context": ctx,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def signable_snapshot_sha256(snapshot: Mapping[str, Any]) -> str:
    """Hash calculation/review state while excluding post-signing state fields."""
    snap = _fingerprint_value(snapshot)
    provenance = _mapping(snap.get("provenance"))
    qctx = _mapping(provenance.get("qualification_context"))
    for field in (
        "digital_signature",
        "institution_acceptance",
        "case_release_status",
        "signed_bytes_sha256",
        "claims",
    ):
        qctx.pop(field, None)
    _normalize_external_signature_state(qctx)
    if qctx:
        provenance["qualification_context"] = qctx
    snap["provenance"] = provenance
    validation = _mapping(snap.get("validation"))
    issuance = _mapping(validation.get("issuance"))
    issuance.pop("status", None)
    issuance.pop("case_release_status", None)
    if issuance:
        validation["issuance"] = issuance
    else:
        validation.pop("issuance", None)
    snap["validation"] = validation
    return hashlib.sha256(canonical_json(snap).encode("utf-8")).hexdigest()


def _profile(context: Mapping[str, Any]) -> Dict[str, Any]:
    # Producers may expose a resolved profile directly or under ``profile``.
    return _mapping(context.get("resolved_profile") or context.get("profile"))


def _review_event_valid(
    event: Any,
    expected_fingerprint: str,
    expected_report_fingerprint: str,
) -> bool:
    row = _mapping(event)
    if not row:
        return False
    event_type = _text(
        row.get("event_type") or row.get("type") or row.get("status")
    ).lower()
    decision = _text(
        row.get("decision") or row.get("outcome") or row.get("status")
    ).lower()
    approved = (
        event_type in REVIEW_APPROVAL_EVENTS or decision in REVIEW_APPROVAL_DECISIONS
    )
    professional = _mapping(row.get("professional") or row.get("reviewer"))
    professional_id = _text(
        professional.get("id")
        or professional.get("registration")
        or row.get("professional_id")
        or row.get("reviewer_id")
    )
    reason = _text(
        row.get("reason")
        or row.get("motive")
        or row.get("motivation")
        or row.get("notes")
    )
    event_fingerprint = _text(row.get("result_fingerprint") or row.get("fingerprint"))
    event_report_fingerprint = _text(
        row.get("report_content_fingerprint")
        or row.get("document_fingerprint")
        or row.get("presentation_fingerprint")
    )
    version = _text(
        row.get("document_sha256")
        or row.get("snapshot_sha256")
        or row.get("revision_id")
        or row.get("version")
    )
    fingerprint_matches = bool(
        expected_fingerprint
        and event_fingerprint == expected_fingerprint
        and event_report_fingerprint == expected_report_fingerprint
    )
    return bool(
        approved
        and professional_id
        and reason
        and version
        and fingerprint_matches
        and row.get("stale") is not True
    )


def _row_evidence_blockers(
    sample: Mapping[str, Any], report_context: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    for kind, ids_field, rows_field in (
        ("used", "used_row_ids", "used_rows"),
        ("excluded", "excluded_row_ids", "excluded_rows"),
    ):
        expected_ids = [str(item) for item in _list(sample.get(ids_field))]
        rows = [_mapping(item) for item in _list(report_context.get(rows_field))]
        actual_ids = [str(row.get("row_id") or row.get("id") or "") for row in rows]
        if expected_ids != actual_ids or len(set(actual_ids)) != len(actual_ids):
            blockers.append(
                {
                    "code": "SAMPLE_ROW_MAP_INCOMPLETE",
                    "path": f"report_context.{rows_field}",
                    "message": f"Linhas {kind} não correspondem, em ordem, aos IDs congelados.",
                    "expected_count": len(expected_ids),
                    "observed_count": len(rows),
                }
            )
            continue
        incomplete = []
        for index, row in enumerate(rows):
            values = row.get("values")
            if (
                not _text(row.get("source"))
                or not isinstance(values, Mapping)
                or not values
                or (kind == "excluded" and not _text(row.get("justification")))
            ):
                incomplete.append(actual_ids[index] or str(index))
        if incomplete:
            blockers.append(
                {
                    "code": "SAMPLE_ROW_EVIDENCE_INCOMPLETE",
                    "path": f"report_context.{rows_field}",
                    "message": f"Linhas {kind} sem fonte ou valores efetivos.",
                    "row_ids": incomplete[:20],
                }
            )
    return blockers


def _signature_record_valid(
    signature: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any],
    report_context: Mapping[str, Any],
    expected_result_fingerprint: str,
    expected_report_fingerprint: str,
) -> bool:
    local = _mapping(signature.get("local_verification"))
    signed_pdf = report_context.get("signed_pdf_bytes")
    unsigned_pdf = report_context.get("unsigned_pdf_bytes")
    byte_binding = bool(
        isinstance(signed_pdf, (bytes, bytearray))
        and isinstance(unsigned_pdf, (bytes, bytearray))
        and bytes(signed_pdf).startswith(bytes(unsigned_pdf))
        and hashlib.sha256(bytes(signed_pdf)).hexdigest()
        == signature.get("signed_pdf_sha256")
        and hashlib.sha256(bytes(unsigned_pdf)).hexdigest()
        == signature.get("unsigned_pdf_sha256")
    )
    if not byte_binding:
        return False
    try:
        from ..digital_signatures.pdf import verify_pdf_signature

        live_verification = verify_pdf_signature(
            bytes(signed_pdf),
            validation_context=report_context.get("signature_validation_context"),
            policy=signature.get("policy")
            if isinstance(signature.get("policy"), Mapping)
            else None,
        )
    except Exception:
        return False
    return bool(
        signature.get("schema_version") == "MP-SIGN/1"
        and signature.get("status") == "valid"
        and signature.get("backend") == "pyHanko"
        and local.get("status") == "valid"
        and int(local.get("signature_count") or 0) > 0
        and signature.get("incremental_base_verified") is True
        and _text(signature.get("signed_pdf_sha256"))
        and _text(signature.get("snapshot_sha256"))
        and signature.get("snapshot_sha256") == signable_snapshot_sha256(snapshot)
        and _text(signature.get("revision_id"))
        and signature.get("result_fingerprint") == expected_result_fingerprint
        and signature.get("report_content_fingerprint") == expected_report_fingerprint
        and live_verification.get("status") == "valid"
        and live_verification.get("signed_pdf_sha256")
        == signature.get("signed_pdf_sha256")
    )


def assess_document_state(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the strongest truthful document state supported by the snapshot.

    A producer's release flag is necessary but insufficient.  Malformed or
    incomplete evidence is downgraded to a work document with explicit blocker
    codes.  Existing MP/1 ``validation.issuance`` values never become a final
    report by themselves.
    """

    qctx = qualification_context(snapshot)
    ctx = _mapping(report_context)
    expected_report_fingerprint = report_content_fingerprint(snapshot, ctx)
    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not qctx:
        blockers.append(
            {
                "code": "QUALIFICATION_CONTEXT_MISSING",
                "path": "provenance.qualification_context",
                "message": "Contexto de qualificação MP-QUAL/1 ausente.",
            }
        )

    schema_version = _text(qctx.get("schema_version"))
    if qctx and schema_version != "MP-QUAL/1":
        blockers.append(
            {
                "code": "QUALIFICATION_SCHEMA_UNSUPPORTED",
                "path": "provenance.qualification_context.schema_version",
                "message": f"Versão de qualificação não suportada: {schema_version or 'ausente'}.",
            }
        )

    profile = _profile(qctx)
    missing_profile = [name for name in PROFILE_FIELDS if not _text(profile.get(name))]
    if missing_profile:
        blockers.append(
            {
                "code": "QUALIFICATION_PROFILE_INCOMPLETE",
                "path": "provenance.qualification_context.profile",
                "message": "Perfil resolvido incompleto: " + ", ".join(missing_profile),
                "fields": missing_profile,
            }
        )

    calculation_status = _text(qctx.get("calculation_status")).lower()
    if calculation_status not in CALCULATION_OK:
        blockers.append(
            {
                "code": "CALCULATION_NOT_RELEASEABLE",
                "path": "provenance.qualification_context.calculation_status",
                "message": f"Estado de cálculo não libera emissão: {calculation_status or 'ausente'}.",
            }
        )

    grade_status = _text(qctx.get("grade_requirement_status")).lower()
    if grade_status not in GRADE_OK:
        blockers.append(
            {
                "code": "GRADE_REQUIREMENT_NOT_MET",
                "path": "provenance.qualification_context.grade_requirement_status",
                "message": f"Requisito de grau não atendido: {grade_status or 'ausente'}.",
            }
        )

    rule_results: List[Dict[str, Any]] = []
    for index, raw in enumerate(_list(qctx.get("rule_results"))):
        rule = _mapping(raw)
        status = _text(rule.get("status")).lower()
        rule_results.append(rule)
        material_optional_fields = {"observed", "criterion_ref", "evidence_refs"}
        missing_rule_fields = [
            name
            for name in RULE_FIELDS
            if (
                name not in rule
                or (name not in material_optional_fields and _empty(rule.get(name)))
                or (
                    name == "evidence_refs"
                    and not isinstance(rule.get(name), (list, tuple))
                )
            )
        ]
        if missing_rule_fields:
            blockers.append(
                {
                    "code": "RULE_RESULT_INCOMPLETE",
                    "path": f"provenance.qualification_context.rule_results[{index}]",
                    "message": f"Regra {rule.get('rule_id') or index} incompleta: "
                    + ", ".join(missing_rule_fields),
                    "rule_id": rule.get("rule_id"),
                    "fields": missing_rule_fields,
                }
            )
        if status not in RULE_STATUSES:
            blockers.append(
                {
                    "code": "RULE_STATUS_INVALID",
                    "path": f"provenance.qualification_context.rule_results[{index}].status",
                    "message": f"Estado de regra inválido: {status or 'ausente'}.",
                    "rule_id": rule.get("rule_id"),
                }
            )
        elif status in BLOCKING_RULE_STATUSES:
            # C05 is the release authority.  A non-passing rule remains fully
            # visible here, but C03 must not silently broaden the catalogue's
            # decisive set or contradict C05's release decision.
            warnings.append(
                {
                    "code": "QUALIFICATION_RULE_NONPASS",
                    "path": f"provenance.qualification_context.rule_results[{index}]",
                    "message": f"Regra {rule.get('rule_id') or index} permanece {status}.",
                    "rule_id": rule.get("rule_id"),
                    "status": status,
                }
            )
        elif status == "not_applicable" and not _text(rule.get("explanation")):
            blockers.append(
                {
                    "code": "NOT_APPLICABLE_WITHOUT_REASON",
                    "path": f"provenance.qualification_context.rule_results[{index}].explanation",
                    "message": f"Regra {rule.get('rule_id') or index} não aplicável sem justificativa.",
                    "rule_id": rule.get("rule_id"),
                }
            )

    if not rule_results:
        blockers.append(
            {
                "code": "QUALIFICATION_RULES_MISSING",
                "path": "provenance.qualification_context.rule_results",
                "message": "Nenhum resultado de regra foi fornecido pelo classificador canônico.",
            }
        )

    for producer_blocker in _list(qctx.get("release_blockers")):
        row = _mapping(producer_blocker)
        blockers.append(
            {
                "code": _text(row.get("code")) or "QUALIFICATION_RELEASE_BLOCKED",
                "path": "provenance.qualification_context.release_blockers",
                "message": _text(row.get("detail") or row.get("message"))
                or "C05 registrou impedimento de liberação.",
                **{key: value for key, value in row.items() if key not in {"code", "detail", "message"}},
            }
        )
    pending_manual = [str(item) for item in _list(qctx.get("pending_manual_rules"))]
    if pending_manual and _text(qctx.get("case_release_status")).lower() in FINAL_RELEASE_STATES:
        blockers.append(
            {
                "code": "PENDING_MANUAL_RULES_IN_FINAL_STATE",
                "path": "provenance.qualification_context.pending_manual_rules",
                "message": "Estado final contradiz regras manuais pendentes preservadas por C05.",
                "rule_ids": pending_manual,
            }
        )

    if qctx:
        provenance = _mapping(snapshot.get("provenance"))
        workflow = _mapping(provenance.get("workflow_context"))
        validation = _mapping(snapshot.get("validation"))
        documentary = _mapping(validation.get("documentary"))
        target = _mapping(snapshot.get("target"))
        value = _mapping(snapshot.get("value"))
        sample = _mapping(snapshot.get("sample"))
        model = _mapping(snapshot.get("model"))
        cost_route = bool(_mapping(provenance.get("cost_result")))
        required_content = {
            "applicant": ctx.get("applicant")
            or snapshot.get("applicant")
            or provenance.get("applicant"),
            "asset_identification": ctx.get("asset_identification")
            or ctx.get("asset")
            or ctx.get("subject")
            or workflow.get("subject_raw"),
            "rights": ctx.get("rights") or ctx.get("property_rights"),
            "reference_date": snapshot.get("reference_date"),
            "inspection_date": snapshot.get("inspection_date")
            or ctx.get("inspection_date"),
            "target_unit": target.get("unit"),
            "value_point": value.get("point"),
            "mean_ci80": value.get("mean_ci80"),
            "prediction_interval": value.get("prediction_interval"),
            "region_characterization": ctx.get("region_characterization"),
            "property_characterization": ctx.get("property_characterization"),
            "methodology_justification": ctx.get("methodology_justification"),
            "assumptions": ctx.get("assumptions") if "assumptions" in ctx else None,
            "sources": ctx.get("sources")
            or documentary.get("sources")
            or provenance.get("sources"),
            "used_row_ids": sample.get("used_row_ids"),
            "model_specification": model.get("coefficients") or model.get("formula"),
        }
        if cost_route:
            # Cost quantification has a BOM/memory, not a regression sample,
            # confidence/prediction intervals or model coefficients.
            for field in ("mean_ci80", "prediction_interval", "used_row_ids", "model_specification"):
                required_content.pop(field, None)
            required_content["cost_memory"] = ctx.get("cost_memory")
        missing_content = [
            name for name, value in required_content.items() if _empty(value)
        ]
        if missing_content:
            blockers.append(
                {
                    "code": "REPORT_REQUIRED_CONTENT_MISSING",
                    "path": "snapshot/report_context",
                    "message": "Conteúdo obrigatório do laudo ausente: "
                    + ", ".join(missing_content),
                    "fields": missing_content,
                }
            )
        critical_issues = [
            _mapping(item)
            for item in _list(snapshot.get("issues"))
            if _text(_mapping(item).get("severity")).lower()
            in {"error", "critical", "fatal"}
        ]
        if critical_issues:
            blockers.append(
                {
                    "code": "CRITICAL_RESULT_ISSUES_UNRESOLVED",
                    "path": "issues",
                    "message": "Há achados críticos não resolvidos no snapshot.",
                    "issue_codes": [item.get("code") for item in critical_issues],
                }
            )
        used_ids = _list(sample.get("used_row_ids"))
        excluded_ids = _list(sample.get("excluded_row_ids"))
        count_mismatches = []
        if sample.get("used") is not None and len(used_ids) != sample.get("used"):
            count_mismatches.append("used")
        if sample.get("excluded") is not None and len(excluded_ids) != sample.get(
            "excluded"
        ):
            count_mismatches.append("excluded")
        if count_mismatches:
            blockers.append(
                {
                    "code": "SAMPLE_COUNT_MISMATCH",
                    "path": "sample",
                    "message": "Contagens e identificadores da amostra divergem: "
                    + ", ".join(count_mismatches),
                    "fields": count_mismatches,
                }
            )
        blockers.extend(_row_evidence_blockers(sample, ctx))
        attachment_issues = []
        for item in _list(ctx.get("documentary_files")):
            attachment = _mapping(item)
            if not attachment.get("authorized_for_report"):
                attachment_issues.append(
                    {"filename": attachment.get("filename"), "state": "not_authorized_for_report"}
                )
            elif _text(attachment.get("attachment_state")) != "available":
                attachment_issues.append(
                    {
                        "filename": attachment.get("filename"),
                        "state": _text(attachment.get("attachment_state")) or "bytes_not_available",
                    }
                )
        if attachment_issues:
            blockers.append(
                {
                    "code": "DOCUMENTARY_ATTACHMENT_UNAVAILABLE",
                    "path": "report_context.documentary_files",
                    "message": "Anexo documental sem autorização ou sem bytes íntegros no armazenamento.",
                    "attachments": attachment_issues,
                }
            )

    review_events = [_mapping(item) for item in _list(qctx.get("review_events"))]
    expected_fingerprint = _text(qctx.get("result_fingerprint"))
    if not expected_fingerprint:
        blockers.append(
            {
                "code": "RESULT_FINGERPRINT_MISSING",
                "path": "provenance.qualification_context.result_fingerprint",
                "message": "Fingerprint canônico do resultado ausente.",
            }
        )
    approved_reviews = [
        event
        for event in review_events
        if _review_event_valid(event, expected_fingerprint, expected_report_fingerprint)
    ]
    if not approved_reviews:
        blockers.append(
            {
                "code": "PROFESSIONAL_REVIEW_NOT_EVIDENCED",
                "path": "provenance.qualification_context.review_events",
                "message": "Revisão aprovadora sem profissional, motivo ou versão vinculada.",
            }
        )

    release_status = _text(qctx.get("case_release_status")).lower() or "analysis_only"
    if release_status not in FINAL_RELEASE_STATES:
        blockers.append(
            {
                "code": "CASE_RELEASE_NOT_FINAL",
                "path": "provenance.qualification_context.case_release_status",
                "message": f"Caso permanece em {release_status}.",
            }
        )

    signature = _mapping(ctx.get("digital_signature") or qctx.get("digital_signature"))
    signature_status = _text(
        signature.get("status") or signature.get("integrity_status")
    ).lower()
    signature_valid = _signature_record_valid(
        signature,
        snapshot=snapshot,
        report_context=ctx,
        expected_result_fingerprint=expected_fingerprint,
        expected_report_fingerprint=expected_report_fingerprint,
    )
    if release_status == "signed_integrity_verified" and not signature_valid:
        blockers.append(
            {
                "code": "SIGNED_STATE_WITHOUT_VALID_SIGNATURE",
                "path": "digital_signature.status",
                "message": "Estado assinado sem verificação criptográfica válida vinculada ao PDF.",
            }
        )
    if signature_status in {"indeterminate", "not_verified", "invalid"}:
        warnings.append(
            {
                "code": "SIGNATURE_STATUS",
                "message": f"Assinatura digital: {signature_status}.",
            }
        )

    is_final = not blockers and release_status in FINAL_RELEASE_STATES
    if is_final and release_status == "signed_integrity_verified":
        document_kind = "Laudo final assinado — integridade verificada"
    elif is_final:
        document_kind = "Laudo final — pronto para assinatura profissional"
    elif qctx:
        document_kind = "Minuta técnica — emissão profissional bloqueada"
    else:
        document_kind = "Minuta de análise técnica — qualificação não fornecida"
    synthetic_test_only = bool(ctx.get("synthetic_test_only"))
    if synthetic_test_only:
        document_kind = "TESTE — " + document_kind

    return {
        "is_final": is_final,
        "document_kind": document_kind,
        "case_release_status": release_status,
        "calculation_status": calculation_status or "unknown",
        "grade_requirement_status": grade_status or "pending",
        "profile": profile,
        "rule_results": rule_results,
        "review_events": review_events,
        "stale_review_events": [
            _mapping(item) for item in _list(qctx.get("stale_review_events"))
        ],
        "approved_review_events": approved_reviews,
        "institution_acceptance": _mapping(qctx.get("institution_acceptance")),
        "result_fingerprint": _text(qctx.get("result_fingerprint")),
        "report_content_fingerprint": expected_report_fingerprint,
        "blockers": blockers,
        "warnings": warnings,
        "signature": signature,
        "synthetic_test_only": synthetic_test_only,
    }
