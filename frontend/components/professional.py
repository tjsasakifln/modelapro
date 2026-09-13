"""C02 professional flow: encomenda, profiles, evidence, review, recipients.

Pure functions, testable without Streamlit. C02 *chooses* known profiles; it
does not write C05 qualification rules or recompute Grau. Additive RequestSpec
fields only. Issuance statuses on the wire stay MP/1 (`draft` /
`review_required` / `ready_for_professional_review`); campaign names are a
presentation mapping.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Optional, Sequence

SCHEMA_VERSION = "MP/1"
QUALIFICATION_SCHEMA = "MP-QUAL/1"

# MP/1 issuance (C01/result_contract). Do not emit campaign strings here.
ISSUANCE_STATUSES = ("draft", "review_required", "ready_for_professional_review")

# Campaign case-release names (presentation / local review ledger only).
CASE_RELEASE_FLOW = (
    "analysis_only",
    "review_required",
    "ready_for_professional_signoff",
    "signed_integrity_verified",
)

ISSUANCE_TO_CASE_RELEASE = {
    "draft": "analysis_only",
    "review_required": "review_required",
    "ready_for_professional_review": "ready_for_professional_signoff",
}

CASE_RELEASE_TO_ISSUANCE = {
    "analysis_only": "draft",
    "review_required": "review_required",
    "ready_for_professional_signoff": "ready_for_professional_review",
    # signed_integrity_verified is a local event after imported signed file
    # verification; it is not an MP/1 issuance.status value.
}

HOMOLOGATION_FORBIDDEN_BADGES = (
    "aceito pelo banco",
    "aceito pela seguradora",
    "homologado pelo banco",
    "homologado pela seguradora",
    "aprovado pelo banco",
    "aprovado pela seguradora",
)

ART_ATTESTED_DEFAULTS = (
    "art_autenticada",
    "rrt_autenticada",
    "inspecao_realizada",
    "regularidade_atestada",
)

PROCEDENCIA_VALUES = (
    "professional_act",
    "received_information",
    "not_recorded",
)

GRADE_REQUIREMENT_STATUSES = (
    "not_requested",
    "met",
    "not_met",
    "pending",
    "error",
)

LIMITATION_KINDS = (
    "missing_data",
    "failed_rule",
    "unsupported_method",
    "human_review",
)

KNOWN_PURPOSES = (
    ("analise_exploratoria", "Análise exploratória (não liberada para emissão)"),
    ("avaliacao_profissional", "Avaliação profissional de valor de mercado"),
    ("garantia", "Garantia / crédito (destinatário bancário)"),
    ("seguro", "Seguro (destinatário seguradora)"),
)

KNOWN_ASSET_SCOPES = (
    ("imovel_urbano", "Imóvel urbano"),
    ("benfeitoria_imovel_urbano", "Benfeitoria de imóvel urbano"),
    ("imovel_urbano_residencial_financiado", "Imóvel residencial financiado"),
)

KNOWN_RIGHTS = (
    ("plena_propriedade", "Plena propriedade"),
    ("direitos_reais_limitados", "Direitos reais limitados"),
    ("nao_informado", "Não informado"),
)

KNOWN_VALUE_BASES = (
    ("valor_de_mercado", "Valor de mercado"),
    ("custo_de_reedicao", "Custo de reedição"),
    ("depreciated_value", "Valor atual / depreciado"),
    ("limite_maximo_de_garantia", "Limite máximo de garantia"),
    ("adopted_value", "Valor adotado / arbitrado"),
)

KNOWN_METHODS = (
    ("comparative_regression", "Comparativo de dados de mercado com regressão"),
    ("cost_reconstruction", "Custo de reconstrução / reposição (rota C01)"),
)

KNOWN_RECIPIENTS = (
    ("", "Sem destinatário institucional definido"),
    ("banco-do-brasil", "Banco do Brasil"),
    ("instituicoes-autorizadas-pelo-bcb", "Instituição autorizada pelo BCB"),
    ("caixa-economica-federal", "CAIXA"),
    ("seguradora-do-ramo-habitacional", "Seguradora do ramo habitacional"),
    ("internal_review", "Revisão interna / arquivo do profissional"),
    ("solicitante", "Solicitante da encomenda"),
    ("banco", "Instituição financeira (banco)"),
    ("seguradora", "Seguradora"),
)

CHECKLIST_LABELS = {
    "purpose_method_fit": "Método suportado para a finalidade da encomenda",
    "value_basis": "Base de valor identificada e coerente com o perfil",
    "sample_review": "Amostra, exclusões e mapa de colunas revisados",
    "inspection_record": "Vistoria registrada com procedência",
    "professional_identity": "Identidade profissional informada (não é autenticação do conselho)",
    "art_rrt": "ART/RRT ou referência documental exigida pelo perfil",
    "distinct_reviewer": "Revisor distinto do responsável pela emissão",
    "grade_requirement": "Pedido de grau e status (pending ≠ met)",
    "limitations_visible": "Limitações e avisos visíveis, sem selo global",
    "calculated_vs_adopted": "Valor calculado versus adotado (só se C05 admitir)",
    "recipient_package": "Pacote/instruções do destinatário e comprovante de retorno",
    "cost_route_c01": "Rota de custo de reconstrução/reposição (C01), não coeficiente de mercado",
}

BACKUP_NOTICE = (
    "Rotina de produto vendido: faça cópia de segurança dos projetos e "
    "revisões. Esta interface não envia dados a nuvem por padrão e não "
    "substitui o arquivo do profissional."
)

SYNTHETIC_DEMO_NOTICE = (
    "Demonstração com dados sintéticos explicitamente marcados — não é "
    "caso real nem aceite institucional."
)


# Presentation is derived from the installed C05 catalog; no parallel rule catalog.
def known_profiles() -> list:
    from modules.qualification_profile import known_profile_ids as catalog_ids, resolve_profile
    rows = []
    for pid in catalog_ids():
        row = resolve_profile({"id": pid})
        supported = row.get("method") in {
            "metodo_comparativo_direto_regressao", "metodo_quantificacao_de_custo",
        }
        rows.append({
            **row, "known": row.get("resolved") is True,
            "recipient_id": row.get("recipient_id"),
            "label": row.get("label") or pid,
            "announced_offer": supported, "method_supports_purpose": supported,
            "compatibility_status": row.get("state"),
            "homologation_status": "not_homologated", "requires_art_rrt": True,
            "requires_distinct_reviewer": bool(row.get("recipient_id")),
            "required_value_basis": row.get("value_basis"),
            "checklist_ids": tuple(r["id"] for r in row.get("requirements", [])),
        })
    return sorted(rows, key=lambda row: (row["id"] != "abnt-14653-2-regressao-mercado", row["id"]))


def known_profile_ids() -> tuple:
    return tuple(row["id"] for row in known_profiles())


def get_known_profile(profile_id: Optional[str]) -> Optional[dict]:
    return next((row for row in known_profiles() if row["id"] == profile_id), None)


def _label_map(pairs: Sequence[tuple]) -> dict:
    return {key: label for key, label in pairs}


def purpose_supports_method(purpose: str, method: str, *, profile: Optional[Mapping[str, Any]] = None) -> dict:
    """Immediate UI signal: does the announced method cover this finalidade?"""
    if isinstance(profile, Mapping) and "method_supports_purpose" in profile:
        supported = bool(profile.get("method_supports_purpose"))
        note = profile.get("method_support_note")
        if supported:
            note = note or "O método anunciado cobre esta finalidade no recorte da oferta."
        else:
            note = note or (
                "O método selecionado não cobre esta finalidade no recorte anunciado."
            )
        return {
            "supported": supported,
            "purpose": purpose,
            "method": method,
            "note": note,
            "hide_mismatch": False,
        }
    if purpose == "seguro" and method != "cost_reconstruction":
        return {
            "supported": False,
            "purpose": purpose,
            "method": method,
            "note": (
                "Finalidade securitária exige custo de reconstrução/reposição "
                "quando o produto/contrato pede essa base; não converter preço "
                "de mercado por coeficiente."
            ),
            "hide_mismatch": False,
        }
    if purpose in {"analise_exploratoria", "avaliacao_profissional", "garantia"} and method == "comparative_regression":
        return {
            "supported": True,
            "purpose": purpose,
            "method": method,
            "note": "Método comparativo com regressão cobre esta finalidade no núcleo anunciado.",
            "hide_mismatch": False,
        }
    return {
        "supported": False,
        "purpose": purpose,
        "method": method,
        "note": "Combinação finalidade/método fora da oferta anunciada.",
        "hide_mismatch": False,
    }


def select_qualification_profile(
    profile_id: Optional[str], *,
    purpose: Optional[str] = None, value_basis: Optional[str] = None,
    method: Optional[str] = None, asset_scope: Optional[str] = None,
    recipient_id: Optional[str] = None, version: Optional[str] = None,
    source_set_sha256: Optional[str] = None,
) -> dict:
    from modules.qualification_profile import resolve_profile
    known = get_known_profile(profile_id)
    if recipient_id == "":
        recipient_id = None
    request = {"id": profile_id}
    for key, value in {
        "purpose": purpose, "value_basis": value_basis, "method": method,
        "asset_scope": asset_scope, "recipient_id": recipient_id,
        "version": version, "source_set_sha256": source_set_sha256,
    }.items():
        if value is not None:
            request[key] = value
    resolved = resolve_profile(request)
    mismatch = bool(known) and any(
        key in request and request[key] != known.get(key)
        for key in ("purpose", "value_basis", "method", "asset_scope", "recipient_id",
                    "version", "source_set_sha256")
    )
    valid = resolved.get("resolved") is True and not mismatch
    supported = bool(known and known["method_supports_purpose"])
    blocked = not valid or not supported or resolved.get("state") != "verified"
    return {
        **(known or {}), **request,
        "known": valid, "resolved": valid,
        "version": resolved.get("version") if valid else version,
        "source_set_sha256": resolved.get("source_set_sha256") if valid else source_set_sha256,
        "label": (known or {}).get("label", "Perfil desconhecido"),
        "compatibility_status": resolved.get("state") if valid else "unknown",
        "announced_offer": bool(known and known["announced_offer"]),
        "homologation_status": "not_homologated", "homologation_badge": None,
        "sold_as_homologated": False, "institution_accepted": False,
        "method_supports_purpose": supported,
        "method_support": {"supported": supported, "hide_mismatch": False,
                           "note": "Escopo do catálogo instalado; liberação depende da avaliação do caso."},
        "blocks_ready_for_professional_signoff": blocked,
        "block_reason": "Perfil ausente, divergente ou com requisito pendente." if blocked else None,
        "mismatch_with_catalog": mismatch, "waiting_for": (),
        "requires_art_rrt": True, "requires_distinct_reviewer": bool((known or {}).get("recipient_id")),
        "checklist_ids": (known or {}).get("checklist_ids", ()),
        "required_value_basis": (known or {}).get("value_basis"),
    }


def qualification_profile_wire(profile: Optional[Mapping[str, Any]]) -> dict:
    """Additive RequestSpec.qualification_profile — only the contract fields."""
    profile = profile or {}
    return {
        "id": profile.get("id") or "",
        "version": str(profile.get("version") or "1"),
        "source_set_sha256": profile.get("source_set_sha256"),
        "purpose": profile.get("purpose") or "",
        "value_basis": profile.get("value_basis") or "",
        "method": profile.get("method") or "",
        "asset_scope": profile.get("asset_scope") or "",
        "recipient_id": profile.get("recipient_id"),
    }


def homologation_badge_for(profile: Optional[Mapping[str, Any]], *, institution_acceptance: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Never derive 'aceito pelo banco/seguradora' from compatibility alone."""
    del profile  # compatibility is not acceptance
    if not isinstance(institution_acceptance, Mapping):
        return None
    if institution_acceptance.get("status") != "accepted":
        return None
    if not institution_acceptance.get("authorized_act"):
        return None
    # Even a recorded act is presented as received evidence, not a software seal.
    return None


def assert_no_false_homologation(text: str) -> bool:
    blob = (text or "").lower()
    return not any(token in blob for token in HOMOLOGATION_FORBIDDEN_BADGES)


def build_encomenda(
    *,
    purpose: str = "",
    asset_scope: str = "urban_real_estate",
    rights: str = "nao_informado",
    reference_date: Optional[str] = None,
    target_unit: str = "",
    applicant: str = "",
    recipient_id: str = "",
    value_basis: str = "",
    profile: Optional[Mapping[str, Any]] = None,
) -> dict:
    profile = select_qualification_profile(
        (profile or {}).get("id") if isinstance(profile, Mapping) else profile,
        purpose=purpose or ((profile or {}).get("purpose") if isinstance(profile, Mapping) else None),
        value_basis=value_basis or ((profile or {}).get("value_basis") if isinstance(profile, Mapping) else None),
        method=(profile or {}).get("method") if isinstance(profile, Mapping) else None,
        asset_scope=asset_scope or ((profile or {}).get("asset_scope") if isinstance(profile, Mapping) else None),
        recipient_id=recipient_id or ((profile or {}).get("recipient_id") if isinstance(profile, Mapping) else None),
        version=(profile or {}).get("version") if isinstance(profile, Mapping) else None,
        source_set_sha256=(profile or {}).get("source_set_sha256") if isinstance(profile, Mapping) else None,
    )
    support = profile.get("method_support") or purpose_supports_method(
        profile.get("purpose") or purpose,
        profile.get("method") or "",
        profile=profile,
    )
    return {
        "purpose": profile.get("purpose") or purpose,
        "asset_scope": profile.get("asset_scope") or asset_scope,
        "rights": rights or "nao_informado",
        "reference_date": reference_date,
        "target_unit": target_unit or "",
        "applicant": applicant or "",
        "recipient_id": profile.get("recipient_id") or recipient_id,
        "value_basis": profile.get("value_basis") or value_basis,
        "qualification_profile": qualification_profile_wire(profile),
        "profile_resolution": profile,
        "method_supports_purpose": bool(support.get("supported")),
        "method_support_note": support.get("note"),
        "homologation_badge": None,
        "sold_as_homologated": False,
        "labels": {
            "purpose": _label_map(KNOWN_PURPOSES).get(profile.get("purpose") or purpose, purpose),
            "asset_scope": _label_map(KNOWN_ASSET_SCOPES).get(profile.get("asset_scope") or asset_scope, asset_scope),
            "rights": _label_map(KNOWN_RIGHTS).get(rights, rights),
            "value_basis": _label_map(KNOWN_VALUE_BASES).get(profile.get("value_basis") or value_basis, value_basis),
            "recipient": _label_map(KNOWN_RECIPIENTS).get(profile.get("recipient_id") or recipient_id, recipient_id),
        },
    }


def empty_inspection_record() -> dict:
    """Empty vistoria: absence is not an attested inspection."""
    return {
        "recorded": False,
        "responsible": "",
        "date": None,
        "verified_characteristics": "",
        "cadastral_divergences": "",
        "physical_divergences": "",
        "special_assumptions": "",
        "limitations": "",
        "procedencia": "not_recorded",
        "auto_attested": False,
        "third_party_act": False,
        "attested_regularity": False,
        "attested_inspection": False,
    }


def build_inspection_record(
    *,
    responsible: str = "",
    date: Optional[str] = None,
    verified_characteristics: str = "",
    cadastral_divergences: str = "",
    physical_divergences: str = "",
    special_assumptions: str = "",
    limitations: str = "",
    procedencia: str = "not_recorded",
    third_party_source: Optional[str] = None,
) -> dict:
    if procedencia not in PROCEDENCIA_VALUES:
        raise ValueError(f"procedencia inválida: {procedencia!r}")
    has_content = any(
        [
            responsible,
            date,
            verified_characteristics,
            cadastral_divergences,
            physical_divergences,
            special_assumptions,
            limitations,
            procedencia != "not_recorded",
        ]
    )
    third_party = procedencia == "received_information"
    return {
        "recorded": bool(has_content),
        "responsible": responsible or "",
        "date": date,
        "verified_characteristics": verified_characteristics or "",
        "cadastral_divergences": cadastral_divergences or "",
        "physical_divergences": physical_divergences or "",
        "special_assumptions": special_assumptions or "",
        "limitations": limitations or "",
        "procedencia": procedencia,
        "procedencia_label": {
            "professional_act": "Ato do profissional responsável",
            "received_information": "Informação recebida de terceiro — não é ato atestado por esta tela",
            "not_recorded": "Vistoria não registrada",
        }[procedencia],
        "third_party_act": third_party,
        "third_party_source": third_party_source if third_party else None,
        "auto_attested": False,
        "attested_regularity": False,
        "attested_inspection": False,
        "defaults_fabricated": False,
    }


def build_document_record(
    *,
    title: str = "",
    source: str = "",
    date: Optional[str] = None,
    procedencia: str = "not_recorded",
    content_sha256: Optional[str] = None,
) -> dict:
    if procedencia not in PROCEDENCIA_VALUES:
        raise ValueError(f"procedencia inválida: {procedencia!r}")
    return {
        "title": title or "",
        "source": source or "",
        "date": date,
        "procedencia": procedencia,
        "content_sha256": content_sha256,
        "auto_attested": False,
        "received_information": procedencia == "received_information",
    }


def build_professional_identity(
    *,
    name: str = "",
    registration: str = "",
    council: str = "",
    art_rrt: str = "",
    documentary_reference: str = "",
) -> dict:
    """Identity fields. Valid format is not conselho authentication."""
    art = (art_rrt or "").strip()
    looks_like_art = bool(re.fullmatch(r"[A-Za-z0-9./-]{5,32}", art)) if art else False
    return {
        "name": name or "",
        "registration": registration or "",
        "council": council or "",
        "art_rrt": art,
        "art_rrt_format_valid": looks_like_art,
        "conselho_authenticated": False,
        "documentary_reference": documentary_reference or "",
        "auto_filled": False,
        "attested_by_software": False,
        "recorded": bool(name or registration or art or documentary_reference),
    }


def art_is_not_conselho_auth(identity: Optional[Mapping[str, Any]]) -> bool:
    identity = identity or {}
    if identity.get("conselho_authenticated"):
        return False
    if identity.get("attested_by_software"):
        return False
    if identity.get("auto_filled"):
        return False
    return True


def record_justified_exclusion(
    *,
    row_id: Any,
    reason: str,
    reviewer: str,
    effect: str,
    fingerprint: Optional[str] = None,
) -> dict:
    if not str(reason or "").strip():
        raise ValueError("exclusão exige motivo explícito")
    if not str(reviewer or "").strip():
        raise ValueError("exclusão exige profissional identificado")
    return {
        "row_id": row_id,
        "reason": str(reason).strip(),
        "reviewer": str(reviewer).strip(),
        "effect": effect or "",
        "fingerprint": fingerprint,
        "automatic_to_improve_r2": False,
        "silent": False,
    }


def preserve_mapping_if_compatible(
    *,
    stored_token: Optional[str],
    current_token: Optional[str],
    stored_mapping: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Keep mapping only when file/schema fingerprint still matches."""
    compatible = bool(stored_token) and stored_token == current_token
    return {
        "compatible": compatible,
        "mapping": dict(stored_mapping) if compatible and isinstance(stored_mapping, Mapping) else None,
        "reused": compatible and stored_mapping is not None,
    }


def feature_map_to_original(
    coefficients: Optional[Mapping[str, Any]],
    feature_schema: Optional[Mapping[str, Any]] = None,
) -> list:
    """Show original characteristic, not dummy names, as the professional label."""
    columns = dict((feature_schema or {}).get("columns") or {})
    dummy_to_base = {}
    for internal, meta in columns.items():
        meta = meta or {}
        if meta.get("dummy_of") or meta.get("base_variable"):
            dummy_to_base[internal] = meta.get("original_name") or meta.get("base_variable") or meta.get("dummy_of")
        source = meta.get("original_name") or internal
        dummy_to_base.setdefault(internal, source)
    rows = []
    for name, value in (coefficients or {}).items():
        original = dummy_to_base.get(name)
        if original is None:
            # Heuristic: bairro_Centro → bairro (never required as input).
            if "_" in str(name):
                head = str(name).split("_", 1)[0]
                original = (columns.get(head) or {}).get("original_name") or head
            else:
                original = name
        rows.append({
            "feature": name,
            "original_characteristic": original,
            "value": value,
            "dummy_name_required": False,
        })
    return rows


def present_independent_validation_coverage(
    snapshot: Optional[Mapping[str, Any]],
    request_spec: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Coverage of independent validation. Train metrics are not external."""
    snapshot = snapshot or {}
    method = None
    if request_spec:
        method = ((request_spec.get("evaluation_policy") or {}).get("method"))
    validation = snapshot.get("validation") or {}
    statistical = validation.get("statistical") if isinstance(validation.get("statistical"), Mapping) else {}
    train_like = {}
    model = snapshot.get("model") or {}
    if isinstance(model, Mapping):
        diagnostics = model.get("diagnostics") or {}
        if isinstance(diagnostics, Mapping):
            for key in (
                "r2",
                "r_squared",
                "r2_adjusted",
                "adj_r2",
                "rmse_train",
                "mae_train",
            ):
                if key in diagnostics:
                    train_like[key] = diagnostics[key]
    requested = str(method or "none") not in {"none", "not_requested", "skip", "", "None"}
    procedure = (
        statistical.get("procedure")
        if isinstance(statistical.get("procedure"), Mapping)
        else {}
    )
    procedure_method = str(procedure.get("method") or "none")
    method_executed = procedure_method not in {
        "none",
        "not_requested",
        "skip",
        "",
        "None",
    }
    coverage = procedure.get("coverage")
    metrics = procedure.get("metrics")
    partition = procedure.get("partition")
    predictions = procedure.get("predictions")
    coverage_evidence = (
        isinstance(coverage, Mapping)
        and isinstance(coverage.get("n_reserved"), int)
        and not isinstance(coverage.get("n_reserved"), bool)
        and coverage["n_reserved"] > 0
        and isinstance(coverage.get("n_covered"), int)
        and not isinstance(coverage.get("n_covered"), bool)
        and 0 < coverage["n_covered"] <= coverage["n_reserved"]
    )
    metrics_evidence = isinstance(metrics, Mapping) and any(
        value is not None for value in metrics.values()
    )
    partition_evidence = (
        isinstance(partition, Mapping)
        and isinstance(partition.get("folds"), list)
        and bool(partition["folds"])
    )
    predictions_evidence = isinstance(predictions, list) and bool(predictions)
    # worker._map_validation publishes independent evidence only under the
    # procedure block.  The surrounding statistical mapping also contains
    # in-sample n/k/intercept and normative precision data, so its mere
    # non-emptiness cannot establish an external run.
    has_external = (
        requested
        and method_executed
        and coverage_evidence
        and metrics_evidence
        and partition_evidence
        and predictions_evidence
    )
    return {
        "requested": requested,
        "method": method or "none",
        "external_available": bool(has_external),
        "train_metrics_are_not_external": True,
        "train_metrics": train_like,
        "label": (
            "Validação independente com cobertura reportada"
            if has_external
            else (
                "Validação independente não executada"
                if not requested
                else "Validação independente solicitada — cobertura ainda não veio no resultado"
            )
        ),
        "presented_train_as_external": False,
    }


def map_issuance_to_case_release(issuance_status: Optional[str]) -> dict:
    """Presentation mapping. Does not rewrite MP/1 issuance.status."""
    status = issuance_status if issuance_status in ISSUANCE_STATUSES else None
    campaign = ISSUANCE_TO_CASE_RELEASE.get(status) if status else None
    return {
        "issuance_status": status,
        "case_release_status": campaign,
        "emitted_illegal_issuance": False,
        "known_issuance": status is not None,
    }


def case_release_to_issuance(case_release_status: Optional[str]) -> dict:
    if case_release_status == "signed_integrity_verified":
        return {
            "issuance_status": "ready_for_professional_review",
            "case_release_status": case_release_status,
            "local_only": True,
            "emitted_illegal_issuance": False,
            "note": (
                "Integridade da assinatura importada é evento local; não altera "
                "issuance.status para um valor fora de MP/1."
            ),
        }
    if case_release_status not in CASE_RELEASE_TO_ISSUANCE:
        return {
            "issuance_status": None,
            "case_release_status": case_release_status,
            "emitted_illegal_issuance": False,
            "unknown": True,
        }
    return {
        "issuance_status": CASE_RELEASE_TO_ISSUANCE[case_release_status],
        "case_release_status": case_release_status,
        "local_only": False,
        "emitted_illegal_issuance": False,
    }


def present_qualification_context(
    snapshot: Optional[Mapping[str, Any]] = None,
    *,
    selected_profile: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Consume C01 provenance.qualification_context when present; never invent passed rules."""
    snapshot = snapshot or {}
    provenance = snapshot.get("provenance") if isinstance(snapshot.get("provenance"), Mapping) else {}
    ctx = provenance.get("qualification_context") if isinstance(provenance, Mapping) else None
    selected = dict(selected_profile or {})
    if not isinstance(ctx, Mapping):
        return {
            "available": False,
            "schema_version": None,
            "integration": "WAITING_FOR_COMPONENTS",
            "waiting_for": ("C01.qualification_context", "C05.assess_qualification"),
            "selected_profile": qualification_profile_wire(selected) if selected else None,
            "homologation_badge": None,
            "rule_results": [],
            "grade_requirement_status": None,
            "case_release_status": None,
            "review_events": [],
            "institution_acceptance": None,
            "unverified_treated_as_passed": False,
        }
    schema = ctx.get("schema_version")
    rules = list(ctx.get("rule_results") or [])
    unverified_as_passed = False
    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        status = rule.get("status")
        if status == "unverified":
            # unverified is not passed
            if status == "passed":
                unverified_as_passed = True
        normalized_rules.append(dict(rule))
        if status == "unverified" and rule.get("treated_as") == "passed":
            unverified_as_passed = True
    acceptance = ctx.get("institution_acceptance")
    return {
        "available": True,
        "schema_version": schema,
        "integration": None if schema == QUALIFICATION_SCHEMA else "WAITING_FOR_COMPONENTS",
        "resolved_profile": ctx.get("profile") or ctx.get("resolved_profile"),
        "result_fingerprint": ctx.get("result_fingerprint"),
        "calculation_status": ctx.get("calculation_status"),
        "rule_results": normalized_rules,
        "grade_requirement_status": ctx.get("grade_requirement_status"),
        "case_release_status": ctx.get("case_release_status"),
        "review_events": list(ctx.get("review_events") or []),
        "institution_acceptance": acceptance if isinstance(acceptance, Mapping) else None,
        "homologation_badge": homologation_badge_for(selected, institution_acceptance=acceptance if isinstance(acceptance, Mapping) else None),
        "unverified_treated_as_passed": unverified_as_passed,
        "selected_profile": qualification_profile_wire(selected) if selected else None,
    }


def classify_limitation(
    *,
    missing_data: bool = False,
    failed_rule: bool = False,
    unsupported_method: bool = False,
    human_review: bool = False,
    message: str = "",
    field: Optional[str] = None,
    action: Optional[str] = None,
) -> dict:
    if unsupported_method:
        kind = "unsupported_method"
    elif failed_rule:
        kind = "failed_rule"
    elif missing_data:
        kind = "missing_data"
    else:
        kind = "human_review"
    return {
        "kind": kind,
        "message": message,
        "field": field,
        "action": action,
        "kinds_distinct": True,
    }


def present_aptidao(
    *,
    grade_requirement_status: Optional[str] = None,
    calculation_status: Optional[str] = None,
    profile: Optional[Mapping[str, Any]] = None,
    limitations: Optional[Sequence[Mapping[str, Any]]] = None,
    issuance_status: Optional[str] = None,
) -> dict:
    """apto / inapto / pendente without collapsing into a single green."""
    profile = profile or {}
    status = grade_requirement_status if grade_requirement_status in GRADE_REQUIREMENT_STATUSES else None
    unsupported = (
        calculation_status in {"unsupported", "invalid_domain", "singular"}
        or profile.get("method_supports_purpose") is False
    )
    not_released = calculation_status in {"valid_not_released", "analysis_only"} or (
        issuance_status in {None, "draft"} and not unsupported
    )
    pending = status in {"pending", None} and not unsupported
    met = status == "met"
    not_met = status == "not_met"
    if unsupported:
        ui = "inapto"
        headline = "Caso sem suporte — valor não é avaliação aprovada"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif not_met:
        ui = "inapto"
        headline = "Grau mínimo não atingido — análise acessível, não liberada"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif profile.get("blocks_ready_for_professional_signoff"):
        ui = "pendente"
        headline = profile.get("block_reason") or "Requisitos do perfil ainda impedem a liberação"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif met and issuance_status == "ready_for_professional_review":
        ui = "apto"
        headline = "Requisitos do pedido atendidos — pode preparar o laudo final"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = True
    elif status == "pending":
        ui = "pendente"
        headline = "Grau mínimo ainda pendente — análise acessível, não liberada"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif status == "error":
        ui = "pendente"
        headline = "Erro ao verificar o grau mínimo"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif status == "not_requested":
        ui = "pendente"
        headline = "Grau mínimo não solicitado — sem selo de emissão"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif met:
        ui = "pendente"
        headline = "Grau atingido; emissão ainda depende de revisão e evidências"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    elif not_released:
        ui = "pendente"
        headline = "Análise calculável, não liberada"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    else:
        ui = "pendente"
        headline = "Estado pendente — sem selo global"
        may_show_approved_value = False
        global_green = False
        can_prepare_laudo = False
    kinds = [item.get("kind") for item in (limitations or []) if isinstance(item, Mapping)]
    return {
        "ui_status": ui,
        "headline": headline,
        "grade_requirement_status": status,
        "calculation_status": calculation_status,
        "global_green": global_green,
        "may_show_approved_value": may_show_approved_value,
        "can_prepare_laudo": can_prepare_laudo,
        "analysis_accessible": not unsupported,
        "limitations": list(limitations or []),
        "limitation_kinds": kinds,
        "pending_is_not_met": status != "met" if status == "pending" else True,
        "not_met_is_not_pending": status != "pending" if status == "not_met" else True,
        "not_requested_is_not_met": status != "met" if status == "not_requested" else True,
        "single_indicator_success": False,
        "homologation_badge": None,
    }


def present_valid_not_released(
    *,
    reason: str,
    field: Optional[str] = None,
    action: Optional[str] = None,
    requested_grade: Optional[int] = None,
) -> dict:
    return {
        "accessible": True,
        "released": False,
        "reason": reason,
        "field": field,
        "action": action,
        "requested_grade_preserved": requested_grade,
        "labeled_approved": False,
        "global_green": False,
    }


def build_profile_checklist(profile: Optional[Mapping[str, Any]]) -> list:
    profile = profile or {}
    items = []
    for req_id in profile.get("checklist_ids") or ():
        items.append({
            "requirement_id": req_id,
            "label": CHECKLIST_LABELS.get(req_id, req_id),
            "required": True,
            "status": "pending",
            "evidence": None,
            "from_c05_rule": False,
        })
    if profile.get("requires_art_rrt") and not any(i["requirement_id"] == "art_rrt" for i in items):
        items.append({
            "requirement_id": "art_rrt",
            "label": CHECKLIST_LABELS["art_rrt"],
            "required": True,
            "status": "pending",
            "evidence": None,
            "from_c05_rule": False,
        })
    if profile.get("requires_distinct_reviewer") and not any(i["requirement_id"] == "distinct_reviewer" for i in items):
        items.append({
            "requirement_id": "distinct_reviewer",
            "label": CHECKLIST_LABELS["distinct_reviewer"],
            "required": True,
            "status": "pending",
            "evidence": None,
            "from_c05_rule": False,
        })
    return items


def record_review_event(
    *,
    fingerprint: str,
    professional_id: str,
    decision: str,
    motive: str,
    version: str,
    checklist_item_id: Optional[str] = None,
    evidence: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    distinct_reviewer_required: bool = False,
) -> dict:
    if not fingerprint:
        raise ValueError("revisão exige fingerprint do resultado")
    if not str(professional_id or "").strip():
        raise ValueError("revisão exige profissional identificado")
    if not str(motive or "").strip():
        raise ValueError("revisão exige motivo")
    if distinct_reviewer_required:
        if not reviewer_id or reviewer_id == professional_id:
            raise ValueError("este perfil exige revisor distinto do responsável")
    return {
        "fingerprint": fingerprint,
        "professional_id": professional_id,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "motive": motive,
        "version": version,
        "checklist_item_id": checklist_item_id,
        "evidence": evidence,
        "stale": False,
        "consent_reusable": False,
        "signature_image_reused": False,
    }


def invalidate_review_events(
    events: Sequence[Mapping[str, Any]],
    *,
    current_fingerprint: str,
) -> list:
    """Material change: mark events stale, keep history, refuse old consent."""
    out = []
    for event in events or []:
        item = dict(event)
        if item.get("fingerprint") != current_fingerprint:
            item["stale"] = True
            item["consent_reusable"] = False
            item["signature_image_reused"] = False
            item["invalidated_reason"] = (
                "Mudança material (dado, amostra, avaliando, perfil, regra, "
                "modelo ou documento). A revisão anterior permanece no histórico "
                "e não autoriza emissão."
            )
        out.append(item)
    return out


def may_reuse_prior_consent(events: Sequence[Mapping[str, Any]], *, current_fingerprint: str) -> bool:
    """Refuse prior consent/signature when the fingerprint moved or an event is stale.

    A previous fingerprint's decision never authorizes the current version.
    """
    if not current_fingerprint:
        return False
    if not events:
        return False
    for event in events:
        if event.get("stale") or event.get("fingerprint") != current_fingerprint:
            return False
        if event.get("consent_reusable") or event.get("signature_image_reused"):
            return False
    return True


def gate_ready_for_professional_signoff(
    *,
    profile: Optional[Mapping[str, Any]],
    qualification_context: Optional[Mapping[str, Any]] = None,
    essential_evidence_present: bool = False,
    current_fingerprint: Optional[str] = None,
    review_events: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict:
    profile = profile or {}
    ctx = qualification_context or {}
    reasons = []
    if not profile.get("known"):
        reasons.append("perfil desconhecido")
    if profile.get("blocks_ready_for_professional_signoff"):
        reasons.append(profile.get("block_reason") or "perfil impede liberação")
    rules = list(ctx.get("rule_results") or [])
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        status = rule.get("status")
        decisive = rule.get("applicability") in {"decisive", "applicable", True} or rule.get("decisive")
        if decisive and status in {"unverified", "unsupported", "error", "failed", "pending_manual"}:
            reasons.append(
                f"regra decisiva {rule.get('rule_id') or ''} com status {status} (unverified ≠ passed)"
            )
    if not essential_evidence_present:
        reasons.append("evidência essencial ausente")
    live_events = [
        event for event in (review_events or [])
        if isinstance(event, Mapping)
        and event.get("fingerprint") == current_fingerprint
        and not event.get("stale")
    ]
    allowed = not reasons
    return {
        "allowed": allowed,
        "blocked": not allowed,
        "reasons": reasons,
        "case_release_status": "ready_for_professional_signoff" if allowed else "review_required",
        "issuance_status_if_emitted": (
            "ready_for_professional_review" if allowed else "review_required"
        ),
        "live_review_events": len(live_events),
        "emitted_illegal_issuance": False,
    }


def present_calculated_vs_adopted(
    *,
    calculated_point: Any,
    adopted_point: Any = None,
    justification: Optional[str] = None,
    c05_admits: Optional[bool] = None,
) -> dict:
    """Adopted value only when C05 admits it. Absence of C05 is not permission."""
    if c05_admits is None:
        return {
            "calculated": calculated_point,
            "adopted": None,
            "recorded": False,
            "admitted": False,
            "waiting_for": "C05.adopted_value_rule",
            "silent_override": False,
            "note": "C05 ainda não admitiu valor adotado distinto do calculado.",
        }
    if not c05_admits:
        return {
            "calculated": calculated_point,
            "adopted": None,
            "recorded": False,
            "admitted": False,
            "silent_override": False,
            "note": "Perfil não admite substituir o valor calculado.",
        }
    if adopted_point is None or adopted_point == calculated_point:
        return {
            "calculated": calculated_point,
            "adopted": calculated_point,
            "recorded": False,
            "admitted": True,
            "same_as_calculated": True,
            "silent_override": False,
        }
    if not str(justification or "").strip():
        return {
            "calculated": calculated_point,
            "adopted": None,
            "recorded": False,
            "admitted": True,
            "blocked": True,
            "silent_override": False,
            "note": "Valor adotado distinto exige justificativa do profissional.",
        }
    return {
        "calculated": calculated_point,
        "adopted": adopted_point,
        "justification": justification,
        "recorded": True,
        "admitted": True,
        "silent_override": False,
    }


def record_institution_submission(
    *,
    recipient_id: str,
    package_name: str,
    instructions_version: str,
    proof_sha256: Optional[str] = None,
    http_status: Optional[int] = None,
    imported_proof: bool = False,
) -> dict:
    """Submission is a professional-imported record. Local HTTP 200 is not acceptance."""
    accepted = False
    if http_status == 200 and not imported_proof:
        # Explicitly not acceptance.
        accepted = False
    return {
        "event": "submission",
        "recipient_id": recipient_id,
        "package_name": package_name,
        "instructions_version": instructions_version,
        "proof_sha256": proof_sha256,
        "imported_proof": bool(imported_proof),
        "http_status": http_status,
        "institution_acceptance": False,
        "local_http_200_is_not_acceptance": True,
        "simulated_portal": False,
        "accepted": accepted,
        "automated_portal": False,
    }


def record_institution_return(
    *,
    recipient_id: str,
    imported_filename: str,
    proof_sha256: str,
    decision: str,
    authorized_act: bool = False,
) -> dict:
    """Return is accepted only as imported proof of a real act, never from a stub."""
    if not proof_sha256:
        raise ValueError("retorno institucional exige hash do comprovante importado")
    if not imported_filename:
        raise ValueError("retorno institucional exige arquivo original importado")
    accepted = bool(authorized_act) and decision == "accepted"
    return {
        "event": "return",
        "recipient_id": recipient_id,
        "imported_filename": imported_filename,
        "proof_sha256": proof_sha256,
        "decision": decision,
        "authorized_act": bool(authorized_act),
        "institution_acceptance": accepted,
        "simulated_portal": False,
        "local_http_200_is_not_acceptance": True,
        "note": (
            None
            if accepted
            else "Comprovante importado registrado. Sem ato autorizado, não há aceite institucional."
        ),
    }


def export_recipient_package_manifest(
    *,
    profile: Mapping[str, Any],
    fingerprint: str,
    artifact_names: Optional[Sequence[str]] = None,
) -> dict:
    return {
        "profile_id": profile.get("id"),
        "profile_version": profile.get("version"),
        "recipient_id": profile.get("recipient_id"),
        "value_basis": profile.get("value_basis"),
        "method": profile.get("method"),
        "fingerprint": fingerprint,
        "artifacts": list(artifact_names or ()),
        "homologated": False,
        "instructions_version": f"{profile.get('id') or 'unknown'}@{profile.get('version') or '1'}",
        "simulated_send": False,
    }


def present_seguro_value_basis(profile: Optional[Mapping[str, Any]]) -> dict:
    profile = profile or {}
    required = profile.get("required_value_basis") or profile.get("value_basis")
    mismatch = required and profile.get("value_basis") and required != profile.get("value_basis")
    market_as_cost = (
        profile.get("purpose") == "seguro"
        and profile.get("method") == "comparative_regression"
        and required == "reconstruction_cost"
    )
    return {
        "required_value_basis": required,
        "required_label": _label_map(KNOWN_VALUE_BASES).get(required, required),
        "method": profile.get("method"),
        "mismatch_hidden": False,
        "mismatch": bool(mismatch) or market_as_cost,
        "market_converted_to_cost": False,
        "note": (
            "Base de valor de seguro depende do produto/contrato. "
            "Custo de reconstrução/reposição não é preço de mercado."
        ),
        "c01_items_visible": True,
    }


def redact_diagnostic(text: Optional[str]) -> str:
    """Drop client PII from support diagnostics. Keep structural codes."""
    if not text:
        return ""
    out = str(text)
    out = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", "[cpf-redacted]", out)
    out = re.sub(r"\b\d{11}\b", "[id-redacted]", out)
    out = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[email-redacted]", out)
    out = re.sub(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}", "[phone-redacted]", out)
    return out


def diagnostic_contains_pii(text: Optional[str]) -> bool:
    if not text:
        return False
    if re.search(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", text):
        return True
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
        return True
    if re.search(r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}", text):
        return True
    return False


def session_binding_token(
    *,
    filename: Optional[str] = None,
    nbytes: Optional[int] = None,
    project_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    input_sha256: Optional[str] = None,
) -> str:
    parts = [
        str(filename or ""),
        str(nbytes if nbytes is not None else ""),
        str(project_id or ""),
        str(profile_id or ""),
        str(input_sha256 or ""),
    ]
    dumped = "|".join(parts)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def declared_fingerprint_from_imported(payload: bytes) -> Optional[str]:
    """Read fingerprint declared in an imported original (JSON package). PDFs have none."""
    if not payload:
        return None
    try:
        text = payload.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    package = data.get("package") if isinstance(data.get("package"), Mapping) else data
    declared = package.get("fingerprint") if isinstance(package, Mapping) else None
    if declared:
        return str(declared)
    nested = data.get("fingerprint")
    return str(nested) if nested else None


def verify_imported_signature_link(
    *,
    fingerprint: str,
    imported_sha256: str,
    declared_fingerprint: Optional[str] = None,
) -> dict:
    if not imported_sha256:
        return {
            "linked": False,
            "fingerprint": fingerprint,
            "imported_sha256": imported_sha256,
            "reused_old_image": False,
            "signed_in_product_name": False,
            "status": "unlinked",
            "note": "Arquivo assinado original ausente — vínculo não verificado.",
        }
    linked = bool(declared_fingerprint) and declared_fingerprint == fingerprint
    return {
        "linked": linked,
        "fingerprint": fingerprint,
        "imported_sha256": imported_sha256,
        "declared_fingerprint": declared_fingerprint,
        "reused_old_image": False,
        "signed_in_product_name": False,
        "status": "linked" if linked else "unlinked",
        "note": (
            "Arquivo original importado vinculado ao fingerprint atual."
            if linked
            else "Arquivo importado sem vínculo com o fingerprint atual — não reutiliza consentimento antigo."
        ),
    }


def value_basis_mismatch_hidden(view: Mapping[str, Any]) -> bool:
    return bool(view.get("mismatch_hidden"))


def producer_example_request_spec() -> dict:
    """Example additive producer payload for the C02→C01 contract."""
    profile = select_qualification_profile("urban-comparative-market-professional")
    return {
        "schema_version": SCHEMA_VERSION,
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {"preco": "target", "area": "predictor", "bairro": "predictor"},
        "target_unit": "BRL",
        "reference_date": "2024-01-15",
        "applicant": "Solicitante sintético",
        "purpose": profile["purpose"],
        "rights": "plena_propriedade",
        "recipient_id": profile["recipient_id"],
        "value_basis": profile["value_basis"],
        "asset_scope": profile["asset_scope"],
        "qualification_profile": qualification_profile_wire(profile),
        "search_policy": {"minimum_fundamentacao_grade": 2},
        "synthetic": True,
    }


def consumer_example_qualification_context() -> dict:
    """Example consumer shape of provenance.qualification_context (C01)."""
    return {
        "schema_version": QUALIFICATION_SCHEMA,
        "profile": qualification_profile_wire(
            select_qualification_profile("urban-comparative-market-professional")
        ),
        "result_fingerprint": "abc123",
        "calculation_status": "valid_not_released",
        "rule_results": [
            {
                "rule_id": "example.pending_c05",
                "source_id": "C05.catalog",
                "edition_or_version": None,
                "clause": None,
                "applicability": "applicable",
                "status": "unverified",
                "observed": None,
                "criterion_ref": None,
                "evidence_refs": [],
                "explanation": "Catálogo C05 ainda não publicado nesta BASE_SHA.",
            }
        ],
        "grade_requirement_status": "pending",
        "case_release_status": "review_required",
        "review_events": [],
        "institution_acceptance": None,
    }
