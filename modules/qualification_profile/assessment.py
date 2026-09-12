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
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .. import normative_rules as rules
from . import claims as claims_mod
from .catalog import ProfileError, resolve_profile
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


def result_fingerprint(payload: Mapping[str, Any]) -> str:
    """Digest of the facts a decision was taken on.

    Any material change to data, parameters, sample, profile, rule, model or
    document changes this fingerprint, which is what invalidates dependent
    decisions and signatures without erasing history.
    """
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _calculation_status(assessment: Mapping[str, Any], context: Mapping[str, Any]) -> str:
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
        if req.get("state") in ("blocked_external_evidence", "pending", "discovery"):
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
                evidence_refs=[evidence] if evidence else [],
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

    pending_manual = [r["rule_id"] for r in rule_results if r["status"] == RULE_PENDING_MANUAL]

    valid_reviews = [
        e for e in review_events
        if e.get("fingerprint") == fingerprint
        and e.get("professional_id")
        and e.get("motive")
        and e.get("version")
    ]
    stale_reviews = [
        e for e in review_events if e.get("fingerprint") not in (None, fingerprint)
    ]

    if stale_reviews and not valid_reviews:
        blockers.append({
            "code": "review_invalidated_by_material_change",
            "detail": (
                f"{len(stale_reviews)} revisão(ões) registrada(s) sobre outro "
                "result_fingerprint. Mudança material de dado, parâmetro, amostra, "
                "perfil, regra, modelo ou documento invalida as decisões dependentes; "
                "o histórico é preservado em stale_review_events."
            ),
            "stale_fingerprints": sorted(
                {str(e.get("fingerprint")) for e in stale_reviews}
            ),
        })

    if blockers and not (
        len(blockers) == 1 and blockers[0]["code"] == "review_invalidated_by_material_change"
    ):
        status = CASE_ANALYSIS_ONLY
    elif pending_manual or not valid_reviews:
        status = CASE_REVIEW_REQUIRED
    else:
        status = CASE_READY_FOR_SIGNOFF
        if signature and signature.get("integrity_verified"):
            if signature.get("fingerprint") == fingerprint:
                status = CASE_SIGNED_INTEGRITY_VERIFIED
            else:
                status = CASE_REVIEW_REQUIRED
                blockers.append({
                    "code": "signature_stale",
                    "detail": (
                        "assinatura registrada sobre outro result_fingerprint: mudança "
                        "material invalida decisões dependentes sem apagar o histórico."
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
    try:
        resolved = resolve_profile(profile)
    except ProfileError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": {"id": (profile or {}).get("id"), "resolved": False,
                        "state": "error", "detail": str(exc)},
            "result_fingerprint": None,
            "calculation_status": CALC_ABSENT,
            "rule_results": [],
            "grade_requirement_status": GRADE_ERROR,
            "case_release_status": CASE_ANALYSIS_ONLY,
            "review_events": [],
            "institution_acceptance": None,
            "claims": [],
            "error": {"code": "profile_error", "detail": str(exc)},
        }

    assessment = ctx.get("normative_assessment") or {}
    calculation_status = _calculation_status(assessment, ctx)

    achieved = (assessment.get("fundamentacao") or {}).get("grade")
    requested = ctx.get("requested_minimum_grade")
    if requested is None:
        requested = (ctx.get("search_policy") or {}).get("minimum_fundamentacao_grade")
    if requested is None:
        requested = resolved.get("minimum_fundamentacao_grade")
    grade_status = _grade_requirement_status(
        requested, achieved, calculation_status=calculation_status
    )

    rule_results: List[Dict[str, Any]] = []
    if assessment:
        rule_results.extend(_tabela1_rule_results(assessment))
        micro = _micronumerosidade_rule_result(assessment)
        if micro:
            rule_results.append(micro)
        rule_results.extend(_pressuposto_rule_results(assessment))
    rule_results.append(_value_basis_rule_result(resolved))
    rule_results.extend(_profile_rule_results(resolved, ctx))

    precisao = assessment.get("precisao") or {}
    intervals = assessment.get("intervals") or {}
    fingerprint = result_fingerprint({
        "profile_id": resolved.get("id"),
        "profile_version": resolved.get("version"),
        "source_set_sha256": resolved.get("source_set_sha256"),
        "rule_results": [
            {"rule_id": r["rule_id"], "status": r["status"], "observed": r["observed"]}
            for r in rule_results
        ],
        "grade": achieved,
        "fundamentacao_points": (assessment.get("fundamentacao") or {}).get("points"),
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
    })

    review_events = list(ctx.get("review_events") or [])
    release_profile = dict(resolved)
    release_profile["_model_use_prohibited"] = assessment.get("model_use_prohibited") or []
    release = _decide_release(
        profile=release_profile,
        rule_results=rule_results,
        calculation_status=calculation_status,
        grade_status=grade_status,
        review_events=review_events,
        signature=ctx.get("signature"),
        fingerprint=fingerprint,
    )

    acceptance = ctx.get("institution_acceptance")
    acceptance_block = {
        "recorded": bool(acceptance),
        "record": acceptance,
        "detail": (
            "Aceitação institucional registrada a partir de ato real."
            if acceptance else
            "Nenhuma aceitação institucional registrada. Ausência de aprovação NÃO é "
            "aprovação implícita nem proibição universal de vender com alegações mais "
            "restritas."
        ),
    }

    claim_results = _evaluate_profile_claims(resolved, ctx, release["case_release_status"])

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
        "calculation_status": calculation_status,
        "rule_results": rule_results,
        "grade_requirement_status": grade_status,
        "requested_minimum_grade": requested,
        "achieved_fundamentacao_grade": achieved,
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
    acceptance = ctx.get("institution_acceptance") or {}
    out.append(claims_mod.evaluate_claim(
        claims_mod.CLAIM_INSTITUTION_ACCEPTED,
        profile_state=state,
        evidence=evidence.get(claims_mod.CLAIM_INSTITUTION_ACCEPTED),
        subject={
            "institution": acceptance.get("institution") or profile.get("recipient_id") or "?",
            "act": acceptance.get("act") or "?",
            "act_version": acceptance.get("act_version") or "?",
            "act_scope": acceptance.get("act_scope") or "?",
        },
    ))
    for claim in out:
        claim["case_release_status_at_evaluation"] = case_release_status
    return out
