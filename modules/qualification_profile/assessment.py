"""assess_qualification(context, profile) -> the MP-QUAL/1 block.

C05 provides this contract; C01 validates/resolves the profile and composes
the context and is the producer of ``provenance.qualification_context``.
This function never recalculates a grade: it consumes the single normative
authority (modules.nbr14653_validation.assess_normative) and decides
*release*, which is a different question from *grade*.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .. import normative_rules as rules
from ..provenance import canonical_json
from . import claims as claims_mod
from .catalog import ProfileError, resolve_profile
from .output_conformance import assess_output_conformance, product_conformance_baseline
from .schema import (
    APPLICABLE,
    CALC_ABSENT,
    CALC_DEGENERATE,
    CALC_FAILED,
    CALC_OK,
    CASE_ANALYSIS_ONLY,
    CASE_READY_FOR_SIGNOFF,
    CASE_REVIEW_REQUIRED,
    CASE_SIGNED_INTEGRITY_VERIFIED,
    GRADE_ERROR,
    GRADE_MET,
    GRADE_NOT_MET,
    GRADE_NOT_REQUESTED,
    GRADE_PENDING,
    NOT_APPLICABLE_BY_PROFILE,
    PROFILE_VERIFIED,
    RULE_ERROR,
    RULE_FAILED,
    RULE_NOT_APPLICABLE,
    RULE_PASSED,
    RULE_PENDING_MANUAL,
    RULE_UNSUPPORTED,
    RULE_UNVERIFIED,
    SCHEMA_VERSION,
    make_rule_result,
    satisfies,
)

_PART2 = rules.EDITION_PART2
_SRC2 = "abnt-nbr-14653-2-2011"
_SRC1 = "abnt-nbr-14653-1-2019"

_RECEIPT_STATUS = "received_declared_unverified"
_RECEIPT_DECLARATION = (
    "RECEIVED_DOCUMENT_RECORDED_WITHOUT_AUTHENTICITY_OR_ACCEPTANCE_VERIFICATION"
)
_RECEIPT_DETAIL = (
    "Comprovante registrado, recebido/declarado e com bytes íntegros; "
    "autenticidade e aceite institucional NÃO VERIFICADOS."
)


def result_fingerprint(payload: Mapping[str, Any]) -> str:
    """Digest of the facts a decision was taken on.

    Any material change to data, parameters, sample, profile, rule, model or
    document changes this fingerprint, which is what invalidates dependent
    decisions and signatures without erasing history.
    """
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_institution_receipt(
    value: Any, profile: Mapping[str, Any]
) -> Dict[str, Any]:
    """Validate a server receipt envelope without treating it as acceptance."""
    envelope = dict(value) if isinstance(value, Mapping) else {}
    record_value = envelope.get("record")
    record = dict(record_value) if isinstance(record_value, Mapping) else {}
    invalid_detail = (
        "Nenhum comprovante íntegro de retorno institucional foi registrado. "
        "Campos accepted/valid fornecidos pelo chamador não constituem aceite."
    )
    required_text = (
        "record_id",
        "idempotency_key",
        "event",
        "decision",
        "recipient_id",
        "profile_id",
        "profile_version",
        "profile_source_set_sha256",
        "protocol",
        "received_at",
        "recorded_at",
        "source",
        "operator_declaration",
        "filename",
        "stored_name",
        "media_type",
        "proof_sha256",
    )
    if not record or any(
        not isinstance(record.get(key), str) or not record[key].strip()
        for key in required_text
    ):
        return {"recorded": False, "record": record or None, "detail": invalid_detail}

    digest = str(record["proof_sha256"]).lower()
    record_id = str(record["record_id"]).lower()
    profile_digest = str(record["profile_source_set_sha256"]).lower()

    def hex_digest(item: str) -> bool:
        return len(item) == 64 and all(ch in "0123456789abcdef" for ch in item)

    try:
        received = datetime.fromisoformat(str(record["received_at"]))
        recorded = datetime.fromisoformat(str(record["recorded_at"]))
        timestamps_valid = received.tzinfo is not None and recorded.tzinfo is not None
        size_valid = (
            isinstance(record.get("size"), int)
            and not isinstance(record.get("size"), bool)
            and record["size"] > 0
        )
    except (TypeError, ValueError):
        timestamps_valid = False
        size_valid = False
    immutable_record = {
        str(key): item
        for key, item in record.items()
        if key not in {"record_id", "bytes_integrity"}
    }
    expected_record_id = hashlib.sha256(
        canonical_json(immutable_record).encode("utf-8")
    ).hexdigest()
    case_state = record.get("case_state_at_import")
    case_state = dict(case_state) if isinstance(case_state, Mapping) else {}
    artifact_hashes = case_state.get("artifact_sha256")
    artifact_hashes = dict(artifact_hashes) if isinstance(artifact_hashes, Mapping) else {}
    case_fingerprints_valid = all(
        value is None or (isinstance(value, str) and hex_digest(value.lower()))
        for value in (
            case_state.get("result_fingerprint"),
            case_state.get("report_content_fingerprint"),
        )
    )
    artifact_hashes_valid = set(artifact_hashes) == {
        "report.pdf",
        "signed_report.pdf",
        "submission.zip",
    } and all(
        value is None or (isinstance(value, str) and hex_digest(value.lower()))
        for value in artifact_hashes.values()
    )
    valid = all((
        envelope.get("recorded") is True,
        record.get("event") == "recipient_return",
        record.get("status") == _RECEIPT_STATUS,
        record.get("decision") == _RECEIPT_STATUS,
        record.get("institution_acceptance") is False,
        record.get("authenticity_verified") is False,
        record.get("bytes_integrity") == "verified",
        record.get("operator_declaration") == _RECEIPT_DECLARATION,
        record.get("profile_id") == profile.get("id"),
        record.get("profile_version") == profile.get("version"),
        profile_digest == str(profile.get("source_set_sha256") or "").lower(),
        record.get("recipient_id") == profile.get("recipient_id"),
        isinstance(record.get("synthetic_test_only"), bool),
        isinstance(record.get("authorized_for_report"), bool),
        case_state.get("association_to_sent_version_verified") is False,
        case_fingerprints_valid,
        artifact_hashes_valid,
        hex_digest(digest),
        hex_digest(profile_digest),
        hex_digest(record_id),
        hex_digest(str(record.get("idempotency_key") or "").lower()),
        record_id == expected_record_id,
        str(record["stored_name"]).startswith(f"recipient-return-{digest[:20]}-"),
        timestamps_valid,
        size_valid,
    ))
    return {
        "recorded": bool(valid),
        "record": record,
        "detail": _RECEIPT_DETAIL if valid else invalid_detail,
    }


def _calculation_status(assessment: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    cost_result = context.get("cost_result")
    if isinstance(cost_result, Mapping) and cost_result:
        if cost_result.get("schema_version") != "MP-COST/1":
            return CALC_FAILED
        return CALC_OK if cost_result.get("computable") is True else CALC_FAILED
    if context.get("calculation_failed"):
        return CALC_FAILED
    if not assessment:
        return CALC_ABSENT
    if context.get("singular") or context.get("degenerate"):
        return CALC_DEGENERATE
    for issue in assessment.get("issues") or []:
        if issue.get("severity") == "error" and issue.get("code") in (
            "singular_matrix", "invalid_domain", "corrupted_data",
        ):
            return CALC_DEGENERATE
    return CALC_OK


def _grade_requirement_status(
    requested: Any, achieved: Any, *, calculation_status: str
) -> str:
    if calculation_status in (CALC_FAILED, CALC_ABSENT):
        return GRADE_ERROR
    if requested is None:
        return GRADE_NOT_REQUESTED
    if isinstance(requested, bool):
        # bool is an int subclass; True would otherwise pass as Grau I.
        return GRADE_ERROR
    try:
        req = int(requested)
    except (TypeError, ValueError):
        return GRADE_ERROR
    # A fractional request is an error, not a truncation: silently reading 3.5
    # as Grau III would grant a grade that was never requested.
    try:
        if float(requested) != float(req):
            return GRADE_ERROR
    except (TypeError, ValueError):
        return GRADE_ERROR
    if req not in (1, 2, 3):
        return GRADE_ERROR
    if achieved is None:
        return GRADE_PENDING
    return GRADE_MET if int(achieved) >= req else GRADE_NOT_MET


def _tabela1_rule_results(assessment: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    fund = assessment.get("fundamentacao") or {}
    for item in fund.get("items") or []:
        ev = item.get("evidence_status")
        grade = item.get("grade")
        if ev == rules.EVIDENCE_PENDING or grade is None:
            status = RULE_PENDING_MANUAL if item["item"] in (1, 3) else RULE_UNVERIFIED
        elif ev == rules.EVIDENCE_DECLARED and not item.get("provenance_verified"):
            # Declared without verifiable provenance: an assertion, not
            # evidence. classify_documentary_item is the single place that
            # decides this; we consume its flag rather than re-deriving it.
            status = RULE_PENDING_MANUAL
        elif int(grade) <= 0:
            status = RULE_FAILED
        else:
            status = RULE_PASSED
        out.append(
            make_rule_result(
                rule_id=item.get("id") or f"tabela1.item{item['item']}",
                source_id=_SRC2,
                edition_or_version=_PART2,
                clause=f"Tabela 1 item {item['item']}",
                status=status,
                observed=grade,
                criterion_ref=(item.get("source") or {}).get("clause"),
                explanation=item.get("detail") or "",
                evidence_refs=[item.get("provenance")] if item.get("provenance") else [],
            )
        )
    return out


def _pressuposto_rule_results(assessment: Mapping[str, Any]) -> List[Dict[str, Any]]:
    mapping = {
        rules.PRESSUPOSTO_SATISFIED: RULE_PASSED,
        rules.PRESSUPOSTO_VIOLATED: RULE_FAILED,
        rules.PRESSUPOSTO_PENDING: RULE_UNVERIFIED,
        rules.PRESSUPOSTO_PROFESSIONAL: RULE_PENDING_MANUAL,
    }
    out: List[Dict[str, Any]] = []
    for pr in assessment.get("pressupostos") or []:
        out.append(
            make_rule_result(
                rule_id=pr["id"],
                source_id=_SRC2,
                edition_or_version=_PART2,
                clause=pr["clause"],
                status=mapping.get(pr["status"], RULE_UNVERIFIED),
                observed=pr.get("observed"),
                criterion_ref=pr.get("criterion"),
                explanation=pr.get("detail") or "",
            )
        )
    return out


def _micronumerosidade_rule_result(assessment: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    micro = assessment.get("micronumerosidade")
    if not micro:
        return None
    status = {
        rules.MICRO_OK: RULE_PASSED,
        rules.MICRO_VIOLATED: RULE_FAILED,
        rules.MICRO_PENDING: RULE_UNVERIFIED,
    }.get(micro["status"], RULE_UNVERIFIED)
    return make_rule_result(
        rule_id="anexoA.2.micronumerosidade",
        source_id=_SRC2,
        edition_or_version=_PART2,
        clause="Anexo A.2 a)",
        status=status,
        observed={"n": micro.get("n"), "violations": micro.get("violations")},
        criterion_ref=f"n >= {micro.get('n_minimum')}, n_i >= {micro.get('ni_minimum')}",
        explanation=micro.get("detail") or "",
    )


def _value_basis_rule_result(profile: Mapping[str, Any]) -> Dict[str, Any]:
    basis = profile.get("value_basis")
    method = profile.get("method")
    guard = rules.value_basis_guard(str(basis), str(method))
    status = {
        "ok": RULE_PASSED,
        "refused": RULE_FAILED,
        "unsupported": RULE_UNSUPPORTED,
    }[guard["status"]]
    return make_rule_result(
        rule_id="parte1.bases_de_valor",
        source_id=_SRC1,
        edition_or_version=rules.EDITION_PART1_2019,
        clause=guard.get("definition_clause") or "3.1.x",
        status=status,
        observed={"value_basis": basis, "method": method},
        criterion_ref="base de valor produzida pelo método declarado",
        explanation=guard["detail"],
    )


def _profile_rule_results(
    profile: Mapping[str, Any], context: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Requirements the profile itself declares, beyond the ABNT rules."""
    out: List[Dict[str, Any]] = []
    provided = context.get("profile_evidence") if isinstance(context.get("profile_evidence"), Mapping) else {}
    cost_result = context.get("cost_result") if isinstance(context.get("cost_result"), Mapping) else {}
    cost_items = {
        item.get("id"): item
        for item in ((cost_result.get("fundamentacao") or {}).get("items") or [])
        if isinstance(item, Mapping)
    }
    for req in profile.get("requirements") or []:
        rid = req.get("id")
        verification = req.get("verification", "professional_evidenced")
        evidence = provided.get(rid)
        if req.get("applies_when") and not context.get(req["applies_when"]):
            out.append(
                make_rule_result(
                    rule_id=rid,
                    source_id=profile.get("id", "profile"),
                    edition_or_version=str(profile.get("version")),
                    clause=req.get("clause") or profile.get("id", ""),
                    status=RULE_NOT_APPLICABLE,
                    applicability=NOT_APPLICABLE_BY_PROFILE,
                    not_applicable_reason=(
                        f"condição {req['applies_when']!r} do perfil "
                        f"{profile.get('id')!r} não presente neste caso"
                    ),
                    explanation=req.get("requirement") or "",
                )
            )
            continue
        if rid == "9.3.1.laudo_completo" and cost_result:
            output_manifest = context.get("output_manifest")
            content = (
                output_manifest.get("content")
                if isinstance(output_manifest, Mapping)
                and isinstance(output_manifest.get("content"), Mapping)
                else {}
            )
            required = (
                "applicant", "asset_identification", "rights", "reference_date",
                "inspection_date", "value_point", "fundamentacao",
                "region_characterization", "property_characterization",
                "methodology_justification", "assumptions", "documents",
                "sources", "cost_memory",
            )
            missing = [field for field in required if content.get(field) is not True]
            status = RULE_PASSED if not missing else RULE_PENDING_MANUAL
            evidence = "output_manifest:content" if not missing else None
            out.append(make_rule_result(
                rule_id=rid, source_id=profile.get("id", "profile"),
                edition_or_version=str(profile.get("version")),
                clause=req.get("clause") or "9.3.1", status=status,
                observed={"missing": missing},
                criterion_ref="MP-OUTPUT-MANIFEST/1.content",
                evidence_refs=[evidence] if evidence else [],
                explanation=(
                    "Conteúdo completo da representação documental verificado pelo manifesto C03."
                    if not missing else f"Laudo completo ainda sem conteúdo: {', '.join(missing)}."
                ),
            ))
            continue
        cost_item = cost_items.get(rid)
        if cost_item is not None:
            status = RULE_PASSED if (
                cost_item.get("grade") in (1, 2, 3)
                and cost_item.get("provenance_verified") is True
            ) else RULE_UNVERIFIED
            evidence = cost_item.get("provenance")
            explanation = cost_item.get("detail") or req.get("requirement") or ""
        elif rid == "metodos.custo.calculo" and cost_result:
            memory = cost_result.get("memory") if isinstance(cost_result.get("memory"), Mapping) else {}
            status = RULE_PASSED if (
                cost_result.get("schema_version") == "MP-COST/1"
                and cost_result.get("computable") is True
                and memory.get("total") == (cost_result.get("value") or {}).get("point")
                and memory.get("automatic_currency_or_date_adjustment") is False
            ) else RULE_FAILED
            evidence = "result:provenance.cost_result"
            explanation = (
                "Memória MP-COST/1 reproduz o valor sem fator de mercado nem atualização implícita."
                if status == RULE_PASSED else
                "Resultado MP-COST/1 ausente, inválido ou sem memória reproduzível."
            )
        elif rid == "metodos.custo.calculo":
            status = RULE_UNVERIFIED
            evidence = None
            explanation = "Resultado e memória MP-COST/1 não foram produzidos; declaração lateral não comprova cálculo."
        elif req.get("state") in ("blocked_external_evidence", "pending", "discovery"):
            status = RULE_UNVERIFIED
            explanation = (
                f"{req.get('requirement') or ''} — fonte do requisito em estado "
                f"{req['state']!r}: não verificada, portanto não aprovada."
            )
        elif evidence:
            status = RULE_PASSED
            explanation = req.get("requirement") or ""
        elif verification == "calculated":
            status = RULE_UNVERIFIED
            explanation = (
                f"{req.get('requirement') or ''} — requisito calculável sem valor "
                "informado pelo produtor do contexto."
            )
        else:
            status = RULE_PENDING_MANUAL
            explanation = (
                f"{req.get('requirement') or ''} — exige ato humano evidenciado; "
                "sem evidência registrada permanece pendente."
            )
        out.append(
            make_rule_result(
                rule_id=rid,
                source_id=profile.get("id", "profile"),
                edition_or_version=str(profile.get("version")),
                clause=req.get("clause") or profile.get("id", ""),
                status=status,
                observed=evidence,
                criterion_ref=req.get("criterion_ref"),
                evidence_refs=[str(evidence)] if evidence else [],
                explanation=explanation,
            )
        )
    return out


def _decide_release(
    *,
    profile: Mapping[str, Any],
    rule_results: Sequence[Mapping[str, Any]],
    calculation_status: str,
    grade_status: str,
    review_events: Sequence[Mapping[str, Any]],
    signature: Optional[Mapping[str, Any]],
    fingerprint: str,
    report_fingerprint: Optional[str],
) -> Dict[str, Any]:
    """Decide case_release_status with the reasons that bound it.

    A calculable result stays savable and studiable as analysis_only; it is
    the QUALIFIED emission that missing requirements gate.
    """
    blockers: List[Dict[str, Any]] = []

    if not profile.get("resolved"):
        blockers.append({
            "code": "profile_unknown",
            "detail": profile.get("detail") or "perfil não resolvido",
        })
    elif profile.get("state") != PROFILE_VERIFIED:
        blockers.append({
            "code": "profile_not_verified",
            "detail": (
                f"perfil {profile.get('id')!r} em estado {profile.get('state')!r}: "
                "um perfil não verificado não habilita emissão qualificada."
            ),
        })

    for ob in profile.get("_output_blocking") or []:
        if (
            ob.get("code") == "output_requirement_pending_signature"
            and (
                signature is None
                or signature.get("required_output_signature_verified") is True
            )
        ):
            # Stage boundary: the reviewed unsigned bytes must exist before an
            # external signer can sign them. This pending item is still exposed
            # by output_conformance and blocks a signed package, but it cannot
            # make creation of the signature request impossible.
            continue
        blockers.append({
            "code": ob["code"],
            "rule_id": ob.get("requirement_id"),
            "detail": ob["detail"],
            "owner": ob.get("owner"),
        })

    for prohibited in profile.get("_model_use_prohibited") or []:
        blockers.append({
            "code": "model_use_prohibited",
            "rule_id": prohibited.get("rule_id"),
            "detail": (
                f"{prohibited.get('clause')}: {prohibited.get('prohibition')}. "
                "A norma veda a utilização do modelo neste caso; não é aviso e não "
                "se supera por revisão profissional."
            ),
        })

    if calculation_status != CALC_OK:
        blockers.append({
            "code": f"calculation_{calculation_status}",
            "detail": (
                f"calculation_status={calculation_status!r}: singularidade, domínio "
                "inválido, categoria sem suporte ou dado corrompido não são aceitos "
                "pelo simples acréscimo de aviso."
            ),
        })

    if grade_status in (GRADE_NOT_MET, GRADE_PENDING, GRADE_ERROR):
        blockers.append({
            "code": f"grade_{grade_status}",
            "detail": (
                f"grade_requirement_status={grade_status!r}: cálculo tecnicamente "
                "válido sem grau atendido é análise não liberada, nunca avaliação "
                "final aprovada."
            ),
        })

    decisive = set(profile.get("decisive_rules") or [])
    by_id = {r["rule_id"]: r for r in rule_results}
    for rule_id in sorted(decisive):
        res = by_id.get(rule_id)
        if res is None:
            blockers.append({
                "code": "decisive_rule_absent",
                "rule_id": rule_id,
                "detail": (
                    f"regra decisiva {rule_id!r} do perfil não foi avaliada: "
                    "ausência não é aprovação."
                ),
            })
        elif not satisfies(res):
            blockers.append({
                "code": "decisive_rule_not_satisfied",
                "rule_id": rule_id,
                "status": res["status"],
                "detail": (
                    f"regra decisiva {rule_id!r} com status {res['status']!r}. "
                    "unverified/pending não equivale a passed."
                ),
            })

    for res in rule_results:
        if res["status"] == RULE_FAILED and res["rule_id"] not in decisive:
            blockers.append({
                "code": "rule_failed",
                "rule_id": res["rule_id"],
                "status": RULE_FAILED,
                "detail": res.get("explanation") or "",
            })

    pending_manual = [
        r["rule_id"] for r in rule_results
        if r["status"] == RULE_PENDING_MANUAL
        and r["rule_id"] != "bb.guiar.assinatura_icp"
    ]

    def review_result_fingerprint(event: Mapping[str, Any]) -> Any:
        return event.get("result_fingerprint") or event.get("fingerprint")

    def review_report_fingerprint(event: Mapping[str, Any]) -> Any:
        return event.get("report_content_fingerprint") or event.get(
            "document_fingerprint"
        )

    def report_fingerprint_matches(event: Mapping[str, Any]) -> bool:
        event_report = review_report_fingerprint(event)
        # Historical contexts without a report digest retain result-only
        # semantics. Once a document digest exists, an event must bind it.
        return not report_fingerprint or event_report == report_fingerprint

    def structurally_reviewable(event: Mapping[str, Any]) -> bool:
        return bool(
            review_result_fingerprint(event)
            and event.get("professional_id")
            and event.get("motive")
            and event.get("version")
        )

    valid_reviews = [
        e for e in review_events
        if review_result_fingerprint(e) == fingerprint
        and report_fingerprint_matches(e)
        and structurally_reviewable(e)
        and e.get("valid") is not False
        and e.get("decision") not in ("rejected", "cancelled")
    ]
    stale_reviews = [
        e for e in review_events
        if review_result_fingerprint(e) not in (None, fingerprint)
        or (structurally_reviewable(e) and not report_fingerprint_matches(e))
    ]

    if stale_reviews and not valid_reviews:
        blockers.append({
            "code": "review_invalidated_by_material_change",
            "detail": (
                f"{len(stale_reviews)} revisão(ões) registrada(s) sobre outro "
                "result_fingerprint ou report_content_fingerprint. Mudança material de "
                "dado, parâmetro, amostra, perfil, regra, modelo ou documento invalida "
                "as decisões dependentes; "
                "o histórico é preservado em stale_review_events."
            ),
            "stale_fingerprints": sorted(
                {str(e.get("fingerprint")) for e in stale_reviews}
            ),
            "stale_report_fingerprints": sorted({
                str(review_report_fingerprint(e)) for e in stale_reviews
                if review_report_fingerprint(e) is not None
            }),
        })

    if blockers and not (
        len(blockers) == 1 and blockers[0]["code"] == "review_invalidated_by_material_change"
    ):
        status = CASE_ANALYSIS_ONLY
    elif pending_manual or not valid_reviews:
        status = CASE_REVIEW_REQUIRED
    else:
        status = CASE_READY_FOR_SIGNOFF
        if signature and signature.get("integrity_verified") is not False:
            bound_result = signature.get("result_fingerprint") or signature.get("fingerprint")
            bound_report = signature.get("report_content_fingerprint")
            signed_sha = signature.get("signed_pdf_sha256") or signature.get("signed_bytes_sha256")
            unsigned_sha = signature.get("unsigned_pdf_sha256") or signature.get("unsigned_bytes_sha256")
            digest_fields_valid = all(
                isinstance(value, str)
                and len(value) == 64
                and all(ch in "0123456789abcdefABCDEF" for ch in value)
                for value in (signed_sha, unsigned_sha)
            )
            signature_valid = bool(
                signature.get("integrity_verified") is True
                and bound_result == fingerprint
                and report_fingerprint
                and bound_report == report_fingerprint
                and digest_fields_valid
            )
            if signature_valid:
                status = CASE_SIGNED_INTEGRITY_VERIFIED
            else:
                status = CASE_REVIEW_REQUIRED
                blockers.append({
                    "code": (
                        "signature_stale"
                        if bound_result not in (None, fingerprint)
                        or bound_report not in (None, report_fingerprint)
                        else "signature_unverified"
                    ),
                    "detail": (
                        "A assinatura não está vinculada simultaneamente ao "
                        "result_fingerprint, report_content_fingerprint e aos hashes "
                        "dos bytes PDF antes/depois da assinatura."
                    ),
                })

    return {
        "case_release_status": status,
        "blockers": blockers,
        "pending_manual_rules": pending_manual,
        "valid_review_events": valid_reviews,
        "stale_review_events": stale_reviews,
        "note": (
            "Assinatura e registro de autoria comprovam autoria/integridade e NÃO "
            "validam o conteúdo técnico. Submissão e aceitação institucional são "
            "registros de eventos reais, não estados deste fluxo."
        ),
    }


def assess_qualification(
    context: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> Dict[str, Any]:
    """Produce the MP-QUAL/1 qualification block for one case and one profile.

    ``context`` keys consumed (all optional unless noted):
      normative_assessment  -- output of assess_normative (required in practice)
      requested_minimum_grade
      calculation_failed / singular / degenerate
      profile_evidence      -- {requirement_id: evidence_ref}
      review_events         -- [{professional_id, motive, version, fingerprint, ...}]
      signature             -- {integrity_verified, fingerprint, ...}
      software_version, claim_evidence
      institution_acceptance -- a RECORD of a real act, never inferred
    """
    ctx = dict(context or {})
    assessment = ctx.get("normative_assessment") or {}
    raw_signature = ctx.get("signature")
    signature = raw_signature if isinstance(raw_signature, Mapping) else None
    review_events = [
        dict(event)
        for event in (ctx.get("review_events") or [])
        if isinstance(event, Mapping)
    ]
    try:
        resolved = resolve_profile(profile)
    except ProfileError as exc:
        if ctx.get("result_material"):
            calculation_status = _calculation_status(assessment, ctx)
            requested = ctx.get("requested_minimum_grade")
            achieved = (assessment.get("fundamentacao") or {}).get("grade")
            grade_status = _grade_requirement_status(
                requested, achieved, calculation_status=calculation_status
            )
        else:
            calculation_status = CALC_ABSENT
            grade_status = GRADE_ERROR
        unresolved_fingerprint = (
            result_fingerprint({
                "profile": dict(profile or {}),
                "result_material": ctx.get("result_material") or {},
                "output_manifest": ctx.get("output_manifest") or {},
            })
            if ctx.get("result_material")
            else None
        )
        stale_reviews = [
            event
            for event in review_events
            if event.get("fingerprint") not in (None, unresolved_fingerprint)
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": {"id": (profile or {}).get("id"), "resolved": False,
                        "state": "error", "detail": str(exc)},
            "result_fingerprint": unresolved_fingerprint,
            "calculation_status": calculation_status,
            "rule_results": [],
            "grade_requirement_status": grade_status,
            "case_release_status": CASE_ANALYSIS_ONLY,
            "release_blockers": [{
                "code": "profile_unknown",
                "detail": str(exc),
            }],
            "pending_manual_rules": [],
            "review_events": review_events,
            "stale_review_events": stale_reviews,
            "report_content_fingerprint": ctx.get("report_content_fingerprint"),
            "signed_bytes_sha256": (
                signature.get("signed_pdf_sha256")
                or signature.get("signed_bytes_sha256")
                if signature
                else None
            ),
            "institution_acceptance": None,
            "claims": [],
            "error": {"code": "profile_error", "detail": str(exc)},
        }

    calculation_status = _calculation_status(assessment, ctx)

    cost_result = ctx.get("cost_result") if isinstance(ctx.get("cost_result"), Mapping) else {}
    achieved = (
        (cost_result.get("fundamentacao") or {}).get("grade")
        if cost_result else (assessment.get("fundamentacao") or {}).get("grade")
    )
    if cost_result and achieved == 3:
        ctx["targets_grau_iii"] = True
    requested = ctx.get("requested_minimum_grade")
    if requested is None:
        requested = (ctx.get("search_policy") or {}).get("minimum_fundamentacao_grade")
    if requested is None:
        requested = resolved.get("minimum_fundamentacao_grade")
    grade_status = _grade_requirement_status(
        requested, achieved, calculation_status=calculation_status
    )

    rule_results: List[Dict[str, Any]] = []
    if assessment and not cost_result:
        rule_results.extend(_tabela1_rule_results(assessment))
        micro = _micronumerosidade_rule_result(assessment)
        if micro:
            rule_results.append(micro)
        rule_results.extend(_pressuposto_rule_results(assessment))
    if cost_result:
        cost_fund = cost_result.get("fundamentacao") or {}
        rule_results.append(make_rule_result(
            rule_id="tabela6_7.custo.enquadramento",
            source_id=_SRC2,
            edition_or_version=_PART2,
            clause="Tabelas 6 e 7 / 9.3",
            status=RULE_PASSED if cost_fund.get("grade") in (1, 2, 3) else RULE_UNVERIFIED,
            observed={"grade": cost_fund.get("grade"), "points": cost_fund.get("points")},
            criterion_ref="modules.normative_rules.classify_custo_fundamentacao",
            evidence_refs=["result:provenance.cost_result.fundamentacao"],
            explanation=cost_fund.get("detail") or "Enquadramento de custo pendente.",
        ))
    rule_results.append(_value_basis_rule_result(resolved))
    rule_results.extend(_profile_rule_results(resolved, ctx))

    precisao = assessment.get("precisao") or {}
    intervals = assessment.get("intervals") or {}
    output_manifest = ctx.get("output_manifest")
    report_fingerprint = ctx.get("report_content_fingerprint")
    fingerprint = result_fingerprint({
        "profile_id": resolved.get("id"),
        "profile_version": resolved.get("version"),
        "source_set_sha256": resolved.get("source_set_sha256"),
        "rule_results": [
            {"rule_id": r["rule_id"], "status": r["status"], "observed": r["observed"]}
            for r in rule_results
        ],
        "grade": achieved,
        "fundamentacao_points": (
            (cost_result.get("fundamentacao") or {}).get("points")
            if cost_result else (assessment.get("fundamentacao") or {}).get("points")
        ),
        "requested_minimum_grade": requested,
        "calculation_status": calculation_status,
        # Precisão, the interval roles and n/k are material facts: changing the
        # amplitude of the 80% CI changes the grau de precisão (Tabela 5) and
        # must therefore invalidate a signature taken over the previous result.
        "precisao": {
            "grade": precisao.get("grade"),
            "status": precisao.get("status"),
            "amplitude_pct": precisao.get("amplitude_pct"),
        },
        "intervals": {
            key: intervals.get(key)
            for key in sorted(intervals)
            if key not in ("note", "notes", "detail")
        },
        "n": assessment.get("n"),
        "k": assessment.get("k"),
        "intercept": assessment.get("intercept"),
        "documentary_provenance": {
            item: ((assessment.get("documentary") or {}).get(item) or {}).get("provenance")
            for item in ("item1", "item3")
        },
        "edition": assessment.get("edition"),
        "source_documents": {
            sid: doc.get("sha256")
            for sid, doc in sorted((assessment.get("source_documents") or {}).items())
        },
        "result_snapshot_id": ctx.get("result_snapshot_id"),
        # Facts from the actual calculation surface (value, coefficients,
        # units, dates, sample and policies) are supplied by C01. Review and
        # signature events stay outside this material so the two-pass protocol
        # can bind them to the stable first-pass digest.
        "result_material": ctx.get("result_material") or {},
        # Output completeness participates in the case decision. The report's
        # own content digest remains a separate identifier below.
        "output_manifest": output_manifest or {},
    })

    # Conformidade da SAÍDA contra o padrão documental do destinatário. Um laudo
    # normativamente correto ainda volta com ressalva se faltar anexo que o
    # manual do destinatário exige, então isto bloqueia a liberação.
    conformance_manifest = dict(output_manifest or {})
    if (
        signature
        and signature.get("required_output_signature_verified") is True
        and isinstance(signature.get("output_evidence"), Mapping)
    ):
        conformance_items = dict(conformance_manifest.get("items") or {})
        conformance_items.update(signature["output_evidence"])
        conformance_manifest["items"] = conformance_items
    output = assess_output_conformance(resolved, conformance_manifest)
    rule_results.extend(output["rule_results"])

    release_profile = dict(resolved)
    release_profile["_output_blocking"] = output["blocking"]
    release_profile["_model_use_prohibited"] = assessment.get("model_use_prohibited") or []
    release = _decide_release(
        profile=release_profile,
        rule_results=rule_results,
        calculation_status=calculation_status,
        grade_status=grade_status,
        review_events=review_events,
        signature=signature,
        fingerprint=fingerprint,
        report_fingerprint=report_fingerprint,
    )

    acceptance_block = normalize_institution_receipt(
        ctx.get("institution_acceptance"), resolved
    )

    claim_results = _evaluate_profile_claims(
        resolved, ctx, release["case_release_status"], acceptance_block
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "profile": {
            "id": resolved.get("id"),
            "version": resolved.get("version"),
            "state": resolved.get("state"),
            "resolved": resolved.get("resolved", False),
            "source_set_sha256": resolved.get("source_set_sha256"),
            "purpose": resolved.get("purpose"),
            "value_basis": resolved.get("value_basis"),
            "method": resolved.get("method"),
            "asset_scope": resolved.get("asset_scope"),
            "recipient_id": resolved.get("recipient_id"),
            "act_type_established": resolved.get("act_type_established"),
            "sources": resolved.get("sources") or [],
        },
        "result_fingerprint": fingerprint,
        "report_content_fingerprint": report_fingerprint,
        "signed_bytes_sha256": (
            signature.get("signed_pdf_sha256")
            or signature.get("signed_bytes_sha256")
            if signature
            else None
        ),
        "calculation_status": calculation_status,
        "rule_results": rule_results,
        "grade_requirement_status": grade_status,
        "requested_minimum_grade": requested,
        "achieved_fundamentacao_grade": achieved,
        "output_conformance": output,
        "product_conformance_baseline": product_conformance_baseline(resolved),
        "case_release_status": release["case_release_status"],
        "release_blockers": release["blockers"],
        "pending_manual_rules": release["pending_manual_rules"],
        "review_events": review_events,
        "stale_review_events": release["stale_review_events"],
        "institution_acceptance": acceptance_block,
        "claims": claim_results,
        "notes": [release["note"]],
    }


def _evaluate_profile_claims(
    profile: Mapping[str, Any],
    ctx: Mapping[str, Any],
    case_release_status: str,
    institution_receipt: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Which claims this profile+case licenses. Case facts never license a
    product-level claim, and vice versa."""
    evidence = dict(ctx.get("claim_evidence") or {})
    version = ctx.get("software_version") or "não identificada"
    out: List[Dict[str, Any]] = []

    state = profile.get("state")
    out.append(claims_mod.evaluate_claim(
        claims_mod.CLAIM_IMPLEMENTS_REQUIREMENTS,
        profile_state=state,
        evidence=evidence.get(claims_mod.CLAIM_IMPLEMENTS_REQUIREMENTS),
        subject={
            "requirements": profile.get("implemented_requirements_label")
                            or "Tabela 1, Tabela 2 e Tabela 5",
            "edition": profile.get("primary_edition") or rules.EDITION_PART2,
        },
    ))
    out.append(claims_mod.evaluate_claim(
        claims_mod.CLAIM_PROFILE_COMPATIBLE,
        profile_state=state,
        evidence=evidence.get(claims_mod.CLAIM_PROFILE_COMPATIBLE),
        subject={"profile": profile.get("id"), "profile_version": profile.get("version")},
    ))
    # No profile_state here, deliberately: calculation_verified is scoped to the
    # SOFTWARE VERSION (CLAIM_SCOPE), not to a profile. An unverified profile
    # says nothing about whether the arithmetic was checked against an
    # independent numeric reference. Do not "fix" this by adding the argument.
    out.append(claims_mod.evaluate_claim(
        claims_mod.CLAIM_CALCULATION_VERIFIED,
        evidence=evidence.get(claims_mod.CLAIM_CALCULATION_VERIFIED),
        subject={"reference": (evidence.get(claims_mod.CLAIM_CALCULATION_VERIFIED) or {})
                 .get("reference_label", "referência não identificada"),
                 "version": version},
    ))
    acceptance = dict((institution_receipt or {}).get("record") or {})
    out.append(claims_mod.evaluate_claim(
        claims_mod.CLAIM_INSTITUTION_ACCEPTED,
        profile_state=state,
        # A received receipt is deliberately not an institutional approval
        # act, even if client input also supplies valid=true/accepted or a
        # fully shaped claim-evidence mapping.
        evidence=None,
        subject={
            "institution": acceptance.get("recipient_id") or profile.get("recipient_id") or "?",
            "act": "comprovante recebido, não verificado",
            "act_version": acceptance.get("protocol") or "?",
            "act_scope": acceptance.get("proof_sha256") or "?",
        },
    ))
    for claim in out:
        claim["case_release_status_at_evaluation"] = case_release_status
    return out
