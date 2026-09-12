"""Conformidade da SAÍDA contra o padrão documental de um destinatário.

Esta é a pergunta que decide se uma análise seria aceita **sem ressalvas** por um
padrão estabelecido por uma instituição — e ela é diferente das outras três que o
contrato já separa:

  * o SOFTWARE atende à regra?            -> rule_results (Tabela 1/2/5, Anexo A)
  * o PROFISSIONAL revisou e assinou?     -> review_events / signature
  * a INSTITUIÇÃO aceitou este trabalho?  -> institution_acceptance (ato real)
  * a SAÍDA contém tudo que o padrão exige? -> AQUI

Um laudo pode estar normativamente correto e ainda assim voltar com ressalva por
faltar um anexo que o manual do destinatário exige. Por isso o requisito de saída
é verificado contra o que o relatório REALMENTE contém, e não contra o que o
produto calcula: um valor que existe em memória e não chega ao laudo não cumpre
um requisito de conteúdo do laudo.

O produtor do manifesto de saída é a frente dona da apresentação (C03); C05
detém a regra e este verificador.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .schema import (
    APPLICABLE,
    NOT_APPLICABLE_BY_PROFILE,
    RULE_FAILED,
    RULE_NOT_APPLICABLE,
    RULE_PASSED,
    RULE_PENDING_MANUAL,
    RULE_UNSUPPORTED,
    make_rule_result,
)

#: Como cada requisito de saída é satisfeito.
KIND_CALCULATED = "calculated"          # o produto calcula e apresenta
KIND_CHART = "chart"                    # figura que precisa chegar ao laudo
KIND_ATTACHMENT = "attachment"          # arquivo anexo (PDF, Excel)
KIND_HUMAN = "human"                    # conteúdo que só o profissional fornece
KIND_TABLE = "table"                    # tabela/demonstrativo

OUTPUT_KINDS = (KIND_CALCULATED, KIND_CHART, KIND_ATTACHMENT, KIND_HUMAN, KIND_TABLE)

#: Estado do produto quanto a cada requisito, apurado por verificação no código
#: e na execução — não por inferência. Registrado no perfil como linha de base.
STATE_EMITTED = "emitted"               # o produto entrega hoje
STATE_PARTIAL = "partial"               # entrega algo próximo, não o exigido
STATE_MISSING = "missing"               # não entrega
STATE_HUMAN_INPUT = "human_input"       # depende de porta de entrada do profissional

BASELINE_STATES = (STATE_EMITTED, STATE_PARTIAL, STATE_MISSING, STATE_HUMAN_INPUT)

#: Estados que NÃO permitem dizer "seria aceito sem ressalvas".
NON_CONFORMING_BASELINE = (STATE_PARTIAL, STATE_MISSING)


class OutputRequirementError(ValueError):
    """Requisito de saída malformado no catálogo."""


def _validate(req: Mapping[str, Any], profile_id: str) -> None:
    for field in ("id", "clause", "requirement", "kind", "product_baseline"):
        if not req.get(field):
            raise OutputRequirementError(
                f"perfil {profile_id!r}: requisito de saída sem {field!r}: {req.get('id')!r}"
            )
    if req["kind"] not in OUTPUT_KINDS:
        raise OutputRequirementError(
            f"perfil {profile_id!r}: kind inválido em {req['id']!r}: {req['kind']!r}"
        )
    if req["product_baseline"] not in BASELINE_STATES:
        raise OutputRequirementError(
            f"perfil {profile_id!r}: product_baseline inválido em {req['id']!r}: "
            f"{req['product_baseline']!r}"
        )
    if req["product_baseline"] in NON_CONFORMING_BASELINE and not req.get("gap"):
        raise OutputRequirementError(
            f"perfil {profile_id!r}: {req['id']!r} está {req['product_baseline']!r} "
            "e precisa declarar 'gap' — uma lacuna sem descrição não é auditável"
        )
    if req["product_baseline"] in NON_CONFORMING_BASELINE and not req.get("owner"):
        raise OutputRequirementError(
            f"perfil {profile_id!r}: {req['id']!r} está {req['product_baseline']!r} "
            "e precisa declarar 'owner' — uma lacuna sem dono não é endereçável"
        )


def assess_output_conformance(
    profile: Mapping[str, Any],
    output_manifest: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Confere a saída de um caso contra os requisitos documentais do perfil.

    ``output_manifest`` é o que o relatório REALMENTE contém, produzido por quem
    monta o laudo: ``{requirement_id: evidence}``. Uma chave ausente é pendência,
    nunca conformidade. Aceita também ``{"items": {...}}``.

    O veredito ``would_be_accepted_without_reservations`` só é verdadeiro quando
    nenhum requisito aplicável está em estado não conforme E o manifesto cobre
    todos eles. Ele é sobre o TRABALHO atender ao padrão publicado — não é, e não
    substitui, aceitação pela instituição, que é ato real dela.
    """
    profile_id = str(profile.get("id"))
    requirements: Sequence[Mapping[str, Any]] = profile.get("output_requirements") or []
    manifest = dict(output_manifest or {})
    if "items" in manifest and isinstance(manifest["items"], Mapping):
        manifest = dict(manifest["items"])

    rule_results: List[Dict[str, Any]] = []
    blocking: List[Dict[str, Any]] = []
    product_gaps: List[Dict[str, Any]] = []
    awaiting_human: List[str] = []
    not_applicable: List[str] = []

    for req in requirements:
        _validate(req, profile_id)
        rid = req["id"]
        baseline = req["product_baseline"]
        provided = manifest.get(rid)

        # Requisito condicional cuja condição não ocorre neste caso.
        if req.get("applies_when") and not manifest.get(req["applies_when"]):
            rule_results.append(
                make_rule_result(
                    rule_id=rid,
                    source_id=profile_id,
                    edition_or_version=str(profile.get("version")),
                    clause=req["clause"],
                    status=RULE_NOT_APPLICABLE,
                    applicability=NOT_APPLICABLE_BY_PROFILE,
                    not_applicable_reason=(
                        f"condição {req['applies_when']!r} do perfil {profile_id!r} "
                        "não presente neste trabalho"
                    ),
                    explanation=req["requirement"],
                )
            )
            not_applicable.append(rid)
            continue

        if baseline in NON_CONFORMING_BASELINE:
            # O produto não entrega: nenhuma evidência de caso conserta isso, e
            # declarar o item como presente não o torna presente.
            status = RULE_FAILED if baseline == STATE_PARTIAL else RULE_UNSUPPORTED
            explanation = (
                f"{req['requirement']} — o produto está {baseline!r} quanto a este "
                f"requisito: {req.get('gap')}"
            )
            product_gaps.append({
                "requirement_id": rid,
                "clause": req["clause"],
                "baseline": baseline,
                "gap": req.get("gap"),
                "owner": req.get("owner"),
            })
            blocking.append({
                "code": f"output_requirement_{baseline}",
                "requirement_id": rid,
                "clause": req["clause"],
                "detail": explanation,
                "owner": req.get("owner"),
            })
        elif provided:
            status = RULE_PASSED
            explanation = req["requirement"]
        elif baseline == STATE_HUMAN_INPUT or req["kind"] == KIND_HUMAN:
            status = RULE_PENDING_MANUAL
            explanation = (
                f"{req['requirement']} — conteúdo do profissional; sem registro no "
                "manifesto de saída permanece pendente."
            )
            awaiting_human.append(rid)
            blocking.append({
                "code": "output_requirement_pending_human",
                "requirement_id": rid,
                "clause": req["clause"],
                "detail": explanation,
                "owner": req.get("owner") or "profissional responsável",
            })
        else:
            # O produto emite, mas este trabalho não declarou que emitiu.
            status = RULE_PENDING_MANUAL
            explanation = (
                f"{req['requirement']} — o produto emite este item "
                f"(baseline {baseline!r}), mas o manifesto de saída deste trabalho "
                "não o registra. Ausência no manifesto não é conformidade."
            )
            blocking.append({
                "code": "output_requirement_not_in_manifest",
                "requirement_id": rid,
                "clause": req["clause"],
                "detail": explanation,
                "owner": req.get("owner") or "C03",
            })

        rule_results.append(
            make_rule_result(
                rule_id=rid,
                source_id=profile_id,
                edition_or_version=str(profile.get("version")),
                clause=req["clause"],
                status=status,
                applicability=APPLICABLE,
                observed=provided,
                criterion_ref=req.get("criterion_ref") or req["kind"],
                evidence_refs=[provided] if provided else [],
                explanation=explanation,
            )
        )

    total = len(requirements)
    applicable = total - len(not_applicable)
    conforming = sum(1 for r in rule_results if r["status"] == RULE_PASSED)

    return {
        "profile_id": profile_id,
        "profile_version": profile.get("version"),
        "standard": profile.get("primary_edition") or profile.get("label"),
        "total_requirements": total,
        "applicable_requirements": applicable,
        "conforming": conforming,
        "rule_results": rule_results,
        "blocking": blocking,
        "product_gaps": product_gaps,
        "awaiting_human": awaiting_human,
        "not_applicable": not_applicable,
        "would_be_accepted_without_reservations": not blocking and applicable > 0,
        "note": (
            "Este veredito é sobre o TRABALHO atender ao padrão documental publicado "
            "pelo destinatário. Não é aceitação pela instituição, que é ato real dela, "
            "e não dispensa a revisão do profissional responsável."
        ),
    }


def product_conformance_baseline(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Conformidade do PRODUTO (não de um caso) contra o padrão do perfil.

    Responde: "o produto, hoje, consegue produzir um trabalho que atenda a este
    padrão sem ressalva?" Independe de qualquer caso concreto — é o que se pode
    alegar sobre a versão do software.
    """
    profile_id = str(profile.get("id"))
    requirements: Sequence[Mapping[str, Any]] = profile.get("output_requirements") or []
    by_state: Dict[str, List[str]] = {s: [] for s in BASELINE_STATES}
    gaps: List[Dict[str, Any]] = []
    for req in requirements:
        _validate(req, profile_id)
        by_state[req["product_baseline"]].append(req["id"])
        if req["product_baseline"] in NON_CONFORMING_BASELINE:
            gaps.append({
                "requirement_id": req["id"],
                "clause": req["clause"],
                "requirement": req["requirement"],
                "baseline": req["product_baseline"],
                "gap": req.get("gap"),
                "owner": req.get("owner"),
            })
    blocking_gaps = [g for g in gaps]
    return {
        "profile_id": profile_id,
        "profile_version": profile.get("version"),
        "counts": {s: len(ids) for s, ids in by_state.items()},
        "by_state": by_state,
        "product_gaps": blocking_gaps,
        "product_can_meet_standard": not blocking_gaps,
        "requires_human_input": by_state[STATE_HUMAN_INPUT],
        "detail": (
            f"{len(by_state[STATE_EMITTED])} de {len(requirements)} requisitos de saída "
            f"emitidos pelo produto; {len(by_state[STATE_HUMAN_INPUT])} dependem do "
            f"profissional; {len(blocking_gaps)} são lacunas do produto."
        ),
        "claim_note": (
            "product_can_meet_standard=False impede a alegação 'compatível com o perfil "
            "documental P': há requisito do padrão que o produto não entrega. "
            "product_can_meet_standard=True não é aceitação pela instituição."
        ),
    }
