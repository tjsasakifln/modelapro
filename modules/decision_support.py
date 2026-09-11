"""Diagnóstico acionável para concluir a avaliação (contrato MP/1).

`recommend_next_actions(snapshot, feature_schema=None)` converte pendências já
presentes no rascunho de resultado em uma lista determinística de ações para o
avaliador. Não classifica grau, não reexecuta modelo e não chama API de língua.

Cada ação: code, priority (menor = mais urgente), reason, next_step,
evidence_refs, limitations. Avisos originais do snapshot não são apagados.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ACTION_KEYS: Tuple[str, ...] = (
    "code",
    "priority",
    "reason",
    "next_step",
    "evidence_refs",
    "limitations",
)

# Códigos estáveis — consumidores (composição de resultado, relatório, interface)
# devem reutilizar estes literais, não paráfrases.
CODE_RESOLVE_UNIT_OR_PARSE = "resolve_unit_or_parse"
CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE = "resolve_imputed_or_ambiguous_price"
CODE_PROVIDE_SUBJECT_CHARACTERISTIC = "provide_subject_characteristic"
CODE_DOCUMENT_SOURCE = "document_source"
CODE_REVIEW_INFLUENTIAL_POINT = "review_influential_point"
CODE_INVESTIGATE_EXTRAPOLATION = "investigate_extrapolation"
CODE_IMPROVE_SAMPLE_SUPPORT = "improve_sample_support"
CODE_CHECK_ASSUMPTION = "check_assumption"
CODE_DEFINE_REFERENCE_DATE = "define_reference_date"
CODE_RECOVER_FAILED_ARTIFACT = "recover_failed_artifact"
CODE_PRECISION_NOT_COMPUTED = "precision_not_computed"
CODE_PRECISION_UNCLASSIFIED = "precision_unclassified"
CODE_IMPROVE_FIT_QUALITY = "improve_fit_quality"
CODE_REVIEW_VALUE_SENSITIVITY = "review_value_sensitivity"
CODE_INCOMPATIBLE_ALTERNATIVE_COMPARISON = "incompatible_alternative_comparison"

# Integridade (unidade/parse, preço imputado/ambíguo, artefato, data-base)
# precede sugestão cosmética de ajuste (R²).
P_INTEGRITY = 10
P_ARTIFACT = 15
P_DATE = 20
P_SUBJECT = 30
P_SOURCE = 40
P_SAMPLE = 50
P_EXTRAPOLATION = 55
P_INFLUENCE = 60
P_PRECISION_NOT_COMPUTED = 65
P_PRECISION_UNCLASSIFIED = 70
P_ASSUMPTION = 75
P_INCOMPATIBLE = 80
P_SENSITIVITY = 85
P_FIT_QUALITY = 90

_LIMIT_NO_PERCENT = "Sem dados suficientes para estimar o ganho desta ação."
_LIMIT_NO_DEFICIT = (
    "Déficit numérico não calculado: n, k ou regra verificada indisponíveis."
)

_K_PLUS_1_RULE = re.compile(
    r"(?P<coeff>\d+)\s*\*?\s*\(\s*k\s*\+\s*1\s*\)",
    re.IGNORECASE,
)

_VERIFIED_STATUSES = frozenset(
    {
        "verified",
        "calculated",
        "verified_rules_listed",
        "verified_rule",
        "verificada",
        "verificado",
        "calculada",
        "calculado",
    }
)

_DECLARED_STATUSES = frozenset(
    {
        "declared",
        "declared_only",
        "declarada",
        "declarado",
        "declared-only",
        "informada",
        "informado",
    }
)

_ISSUE_CODE_TO_ACTION: Mapping[str, str] = {
    "imputed_target": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "imputed_price": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "price_imputed": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "target_imputed": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "ambiguous_price": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "target_ambiguous": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "preco_imputado": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "preco_ambiguo": CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE,
    "parse_error": CODE_RESOLVE_UNIT_OR_PARSE,
    "parse_ambiguous": CODE_RESOLVE_UNIT_OR_PARSE,
    "unit_ambiguous": CODE_RESOLVE_UNIT_OR_PARSE,
    "unit_pending": CODE_RESOLVE_UNIT_OR_PARSE,
    "unit_unresolved": CODE_RESOLVE_UNIT_OR_PARSE,
    "target_unit_pending": CODE_RESOLVE_UNIT_OR_PARSE,
    "ambiguous_unit": CODE_RESOLVE_UNIT_OR_PARSE,
    "unidade_pendente": CODE_RESOLVE_UNIT_OR_PARSE,
    "influential_observation": CODE_REVIEW_INFLUENTIAL_POINT,
    "influential_point": CODE_REVIEW_INFLUENTIAL_POINT,
    "high_leverage": CODE_REVIEW_INFLUENTIAL_POINT,
    "high_cooks_distance": CODE_REVIEW_INFLUENTIAL_POINT,
    "cooks_distance": CODE_REVIEW_INFLUENTIAL_POINT,
    "observacao_influente": CODE_REVIEW_INFLUENTIAL_POINT,
    "extrapolation": CODE_INVESTIGATE_EXTRAPOLATION,
    "subject_out_of_sample": CODE_INVESTIGATE_EXTRAPOLATION,
    "item4_extrapolation": CODE_INVESTIGATE_EXTRAPOLATION,
    "extrapolacao": CODE_INVESTIGATE_EXTRAPOLATION,
    "sample_insufficient": CODE_IMPROVE_SAMPLE_SUPPORT,
    "insufficient_n": CODE_IMPROVE_SAMPLE_SUPPORT,
    "item2_sample": CODE_IMPROVE_SAMPLE_SUPPORT,
    "suporte_amostral": CODE_IMPROVE_SAMPLE_SUPPORT,
    "heteroscedasticity": CODE_CHECK_ASSUMPTION,
    "non_normal_residuals": CODE_CHECK_ASSUMPTION,
    "non_normality": CODE_CHECK_ASSUMPTION,
    "autocorrelation": CODE_CHECK_ASSUMPTION,
    "assumption_violation": CODE_CHECK_ASSUMPTION,
    "heterocedasticidade": CODE_CHECK_ASSUMPTION,
    "reference_date_missing": CODE_DEFINE_REFERENCE_DATE,
    "date_base_pending": CODE_DEFINE_REFERENCE_DATE,
    "missing_reference_date": CODE_DEFINE_REFERENCE_DATE,
    "data_base_pendente": CODE_DEFINE_REFERENCE_DATE,
    "pdf_failed": CODE_RECOVER_FAILED_ARTIFACT,
    "artifact_failed": CODE_RECOVER_FAILED_ARTIFACT,
    "report_failed": CODE_RECOVER_FAILED_ARTIFACT,
    "pdf_generation_failed": CODE_RECOVER_FAILED_ARTIFACT,
    "pdf_render_error": CODE_RECOVER_FAILED_ARTIFACT,
    "declared_only_source": CODE_DOCUMENT_SOURCE,
    "documentary_declared": CODE_DOCUMENT_SOURCE,
    "source_declared_only": CODE_DOCUMENT_SOURCE,
    "fonte_declarada": CODE_DOCUMENT_SOURCE,
    "missing_subject_characteristic": CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
    "subject_feature_missing": CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
    "item1_pending": CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
    "low_r2": CODE_IMPROVE_FIT_QUALITY,
    "improve_r2": CODE_IMPROVE_FIT_QUALITY,
    "r2_marginal": CODE_IMPROVE_FIT_QUALITY,
    "low_r2_adjusted": CODE_IMPROVE_FIT_QUALITY,
    "precision_not_computed": CODE_PRECISION_NOT_COMPUTED,
    "precisao_nao_calculada": CODE_PRECISION_NOT_COMPUTED,
    "not_computed": CODE_PRECISION_NOT_COMPUTED,
    "precision_unclassified": CODE_PRECISION_UNCLASSIFIED,
    "precisao_nao_classificavel": CODE_PRECISION_UNCLASSIFIED,
    "unclassified_precision": CODE_PRECISION_UNCLASSIFIED,
    "unclassified": CODE_PRECISION_UNCLASSIFIED,
}


def recommend_next_actions(
    snapshot: Optional[Mapping[str, Any]] = None,
    feature_schema: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Converte um rascunho MP/1 (completo ou parcial) em ações rastreáveis.

    Parameters
    ----------
    snapshot:
        Mapeamento no formato estrutural MP/1. DataFrames e objetos de modelo
        não são aceitos. ``None`` equivale a mapeamento vazio.
    feature_schema:
        Esquema opcional de variáveis-base (colunas/papéis) para detectar
        característica do sujeito ausente. Não é usado para reajustar modelo.

    Returns
    -------
    list of dict
        Ações com as chaves de ACTION_KEYS, estáveis para o mesmo snapshot.
    """
    if snapshot is None:
        snapshot = {}
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot deve ser um mapeamento MP/1, não DataFrame nem objeto de modelo")
    if feature_schema is not None and not isinstance(feature_schema, Mapping):
        raise TypeError("feature_schema deve ser um mapeamento ou None")

    drafts: List[Dict[str, Any]] = []
    drafts.extend(_actions_from_issues(snapshot))
    drafts.extend(_actions_from_precision(snapshot))
    drafts.extend(_actions_from_documentary(snapshot))
    drafts.extend(_actions_from_sample_rule(snapshot))
    drafts.extend(_actions_from_target_unit(snapshot))
    drafts.extend(_actions_from_reference_date(snapshot))
    drafts.extend(_actions_from_artifacts(snapshot))
    drafts.extend(_actions_from_subject(snapshot, feature_schema))
    drafts.extend(_actions_from_item_pendencies(snapshot))
    drafts.extend(_actions_from_alternatives(snapshot))

    merged = _consolidate(drafts)
    merged.sort(key=lambda row: (int(row["priority"]), str(row["code"])))
    return merged


def _action(
    code: str,
    priority: int,
    reason: str,
    next_step: str,
    evidence_refs: Optional[Sequence[Any]] = None,
    limitations: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "priority": int(priority),
        "reason": reason,
        "next_step": next_step,
        "evidence_refs": list(evidence_refs or []),
        "limitations": list(limitations or []),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if value.is_integer():
            return int(value)
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _norm_code(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    return text


def _issues(snapshot: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    raw = snapshot.get("issues")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _issue_ref(issue: Mapping[str, Any]) -> Dict[str, Any]:
    ref: Dict[str, Any] = {
        "kind": "issue",
        "code": issue.get("code"),
        "origin": issue.get("origin"),
        "affected_ids": list(issue.get("affected_ids") or []),
        "message": issue.get("message"),
    }
    evidence = issue.get("evidence")
    if isinstance(evidence, Mapping):
        ref["evidence"] = dict(evidence)
    return ref


def _item_ref(item: Mapping[str, Any], path: str) -> Dict[str, Any]:
    return {
        "kind": "item",
        "id": item.get("id") or item.get("item"),
        "item": item.get("item"),
        "path": path,
        "evidence_status": item.get("evidence_status") or item.get("status"),
        "source": item.get("source"),
    }


def _action_code_for_issue(issue: Mapping[str, Any]) -> Optional[str]:
    ncode = _norm_code(issue.get("code"))
    if ncode in _ISSUE_CODE_TO_ACTION:
        return _ISSUE_CODE_TO_ACTION[ncode]

    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), Mapping) else {}
    ev_code = _norm_code(evidence.get("code") if isinstance(evidence, Mapping) else None)
    if ev_code in _ISSUE_CODE_TO_ACTION:
        return _ISSUE_CODE_TO_ACTION[ev_code]

    if "imput" in ncode:
        blob = ncode + " " + _norm_code(evidence.get("column") if isinstance(evidence, Mapping) else "")
        blob += " " + _norm_code(evidence.get("role") if isinstance(evidence, Mapping) else "")
        if any(token in blob for token in ("price", "preco", "target", "alvo", "valor")):
            return CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE

    if ncode in {"failed", "error"} and "pdf" in str(issue.get("message") or "").lower():
        return CODE_RECOVER_FAILED_ARTIFACT
    return None


def _actions_from_issues(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for issue in _issues(snapshot):
        code = _action_code_for_issue(issue)
        if not code:
            continue
        if code == CODE_IMPROVE_SAMPLE_SUPPORT:
            out.append(_sample_support_action(snapshot, extra_refs=[_issue_ref(issue)]))
            continue
        template = _TEMPLATE_BY_CODE[code]
        refs = [_issue_ref(issue)]
        out.append(
            _action(
                code,
                template["priority"],
                template["reason"],
                template["next_step"],
                refs,
                template["limitations"],
            )
        )
    return out


def _validation(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(snapshot.get("validation"))


def _iter_fundamentacao_items(snapshot: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    fund = _mapping(_validation(snapshot).get("fundamentacao"))
    items = fund.get("items")
    if isinstance(items, Mapping):
        for key, item in items.items():
            if not isinstance(item, Mapping):
                continue
            if item.get("item") is None:
                enriched = dict(item)
                try:
                    enriched["item"] = int(key)
                except (TypeError, ValueError):
                    enriched["item"] = key
                if not enriched.get("id"):
                    enriched["id"] = key
                yield enriched
            else:
                yield item
        return
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                yield item


def _status_in(value: Any, bucket: Mapping[str, Any] | frozenset) -> bool:
    if value is None:
        return False
    return str(value).strip().lower().replace("-", "_") in bucket


def _is_verified(node: Mapping[str, Any]) -> bool:
    for key in ("evidence_status", "status", "verification_status", "rule_status"):
        if _status_in(node.get(key), _VERIFIED_STATUSES):
            return True
    calc = node.get("calculation")
    if isinstance(calc, Mapping):
        for key in ("evidence_status", "status", "rule_status"):
            if _status_in(calc.get(key), _VERIFIED_STATUSES):
                return True
    return False


def _is_declared(node: Mapping[str, Any]) -> bool:
    for key in ("evidence_status", "status", "provenance", "verification_status"):
        if _status_in(node.get(key), _DECLARED_STATUSES):
            return True
    return False


def _rule_text(rule: Any) -> Optional[str]:
    if rule is None:
        return None
    if isinstance(rule, Mapping):
        rule = (
            rule.get("expression")
            or rule.get("formula")
            or rule.get("text")
            or rule.get("rule")
        )
    if rule is None:
        return None
    return str(rule)


def _parse_k_plus_1_requirements(rule: Any, k: Optional[int]) -> List[Dict[str, Any]]:
    if k is None:
        return []
    text = _rule_text(rule)
    if not text:
        return []
    found: List[Dict[str, Any]] = []
    seen = set()
    for match in _K_PLUS_1_RULE.finditer(text):
        coeff = int(match.group("coeff"))
        requirement = coeff * (k + 1)
        label = match.group(0).replace(" ", "")
        key = (coeff, requirement)
        if key in seen:
            continue
        seen.add(key)
        found.append({"coeff": coeff, "requirement": requirement, "label": label})
    return found


def _choose_unmet_requirement(
    parsed: Sequence[Mapping[str, Any]],
    n: Optional[int],
) -> Optional[Dict[str, Any]]:
    if n is None or not parsed:
        return None
    unmet = [row for row in parsed if int(row["requirement"]) - n > 0]
    if not unmet:
        return None
    return max(unmet, key=lambda row: int(row["coeff"]))


def _fold_status(value: Any) -> str:
    text = _norm_code(value)
    return text.translate(str.maketrans("áàâãäéêíóôõúüç", "aaaaaeeiooouuc"))


def _is_sample_quantity_item(item: Mapping[str, Any]) -> bool:
    ident = item.get("item")
    if ident in (2, "2", "item_2", "item2"):
        return True
    blob = " ".join(
        str(item.get(key) or "") for key in ("id", "description", "name", "title")
    ).lower()
    return any(
        token in blob
        for token in ("quantidade", "amostra", "dados de mercado", "item_2", "item2")
    )


def _extract_n(snapshot: Mapping[str, Any], calc: Mapping[str, Any]) -> Optional[int]:
    for candidate in (
        calc.get("n"),
        _mapping(_validation(snapshot).get("statistical")).get("n"),
        _mapping(_validation(snapshot).get("statistical")).get("n_samples"),
        _mapping(snapshot.get("sample")).get("used"),
        _mapping(snapshot.get("sample")).get("n"),
        _mapping(snapshot.get("sample")).get("n_samples"),
        _mapping(snapshot.get("model")).get("n"),
    ):
        parsed = _as_int(candidate)
        if parsed is not None:
            return parsed
    return None


def _extract_k(snapshot: Mapping[str, Any], calc: Mapping[str, Any]) -> Optional[int]:
    for candidate in (
        calc.get("k"),
        _mapping(_validation(snapshot).get("statistical")).get("k"),
        _mapping(_validation(snapshot).get("statistical")).get("k_vars"),
        _mapping(snapshot.get("model")).get("k"),
        _mapping(snapshot.get("model")).get("n_predictors"),
        _mapping(snapshot.get("model")).get("n_variables"),
    ):
        parsed = _as_int(candidate)
        if parsed is not None:
            return parsed
    return None


def _candidate_from_node(
    snapshot: Mapping[str, Any],
    node: Mapping[str, Any],
    calc: Mapping[str, Any],
    rule: Any,
    *,
    treat_as_sample: bool,
    source_kind: str,
) -> Optional[Dict[str, Any]]:
    if not treat_as_sample:
        return None
    n = _extract_n(snapshot, calc)
    k = _extract_k(snapshot, calc)
    parsed = _parse_k_plus_1_requirements(rule, k)
    if n is None or k is None or not parsed:
        return None
    chosen = _choose_unmet_requirement(parsed, n)
    if chosen is None:
        return None
    return {
        "node": node,
        "calc": calc,
        "rule_label": chosen["label"],
        "n": n,
        "k": k,
        "requirement": int(chosen["requirement"]),
        "deficit": int(chosen["requirement"]) - n,
        "is_item2": _is_sample_quantity_item(node),
        "source_kind": source_kind,
    }


def _collect_unmet_sample_candidates(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for item in _iter_fundamentacao_items(snapshot):
        if not _is_verified(item):
            continue
        calc = item.get("calculation") if isinstance(item.get("calculation"), Mapping) else {}
        rule = calc.get("rule") or calc.get("formula") or item.get("rule")
        ident = item.get("item")
        treat = _is_sample_quantity_item(item) or ident in (None, 2, "2")
        found = _candidate_from_node(
            snapshot, item, calc, rule, treat_as_sample=treat, source_kind="item"
        )
        if found:
            candidates.append(found)
    statistical = _mapping(_validation(snapshot).get("statistical"))
    if _is_verified(statistical):
        rule = statistical.get("rule") or statistical.get("sample_rule")
        found = _candidate_from_node(
            snapshot,
            statistical,
            statistical,
            rule,
            treat_as_sample=True,
            source_kind="statistical",
        )
        if found:
            candidates.append(found)
    for issue in _issues(snapshot):
        evidence = issue.get("evidence") if isinstance(issue.get("evidence"), Mapping) else {}
        if not evidence:
            continue
        if not (_is_verified(evidence) or _is_verified(issue)):
            continue
        rule = evidence.get("rule") or evidence.get("formula")
        found = _candidate_from_node(
            snapshot, issue, evidence, rule, treat_as_sample=True, source_kind="issue"
        )
        if found:
            candidates.append(found)
    return candidates


def _pick_sample_candidate(candidates: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if not candidates:
        return None
    item2 = [row for row in candidates if row.get("is_item2")]
    pool: Sequence[Mapping[str, Any]] = item2 or candidates
    return max(pool, key=lambda row: int(row["deficit"]))


def _refs_for_sample_candidate(
    candidate: Mapping[str, Any],
    extra_refs: Optional[Sequence[Any]] = None,
) -> List[Any]:
    refs: List[Any] = list(extra_refs or [])
    node = candidate.get("node")
    if not isinstance(node, Mapping):
        return refs
    if candidate.get("source_kind") == "issue" or node.get("code"):
        refs.append(_issue_ref(node))
    elif candidate.get("source_kind") == "statistical":
        refs.append(
            {
                "kind": "field",
                "path": "validation.statistical",
                "rule": candidate.get("rule_label"),
            }
        )
    else:
        refs.append(_item_ref(node, "validation.fundamentacao.items"))
    return refs


def _sample_support_from_numbers(
    n: int,
    k: int,
    rule_label: str,
    requirement: int,
    deficit: int,
    refs: Sequence[Any],
) -> Dict[str, Any]:
    reason = (
        f"Déficit de {deficit} para este item "
        f"(n={n}, k={k}, requisito {rule_label}={requirement}). "
        "Este déficit refere-se somente a este item e não garante o grau global "
        "de fundamentação."
    )
    next_step = (
        "Ampliar a amostra com dados de mercado comparáveis e verificáveis "
        "para este item. Não adicionar registros aleatórios. Dados futuros "
        "podem alterar o ajuste, o suporte amostral e os demais itens."
    )
    limitations = [
        "O déficit numérico vale apenas para este item com a n, k e regra "
        "verificada atualmente disponíveis.",
        "Não garante o grau global de fundamentação nem a prontidão de emissão.",
        _LIMIT_NO_PERCENT,
    ]
    return _action(
        CODE_IMPROVE_SAMPLE_SUPPORT,
        P_SAMPLE,
        reason,
        next_step,
        refs,
        limitations,
    )


def _sample_support_limitation(refs: Sequence[Any]) -> Dict[str, Any]:
    return _action(
        CODE_IMPROVE_SAMPLE_SUPPORT,
        P_SAMPLE,
        "O suporte amostral está pendente, mas n, k e a regra quantitativa "
        "verificada não estão todos disponíveis para calcular o déficit.",
        "Conferir n efetivo, k do modelo e a regra quantitativa já verificada "
        "antes de projetar quantidade a complementar. Não incluir observações "
        "sintéticas sem lastro de mercado.",
        refs,
        [_LIMIT_NO_DEFICIT, _LIMIT_NO_PERCENT],
    )


def _sample_support_action(
    snapshot: Mapping[str, Any],
    extra_refs: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    candidate = _pick_sample_candidate(_collect_unmet_sample_candidates(snapshot))
    refs = _refs_for_sample_candidate(candidate, extra_refs) if candidate else list(extra_refs or [])
    if candidate:
        return _sample_support_from_numbers(
            int(candidate["n"]),
            int(candidate["k"]),
            str(candidate["rule_label"]),
            int(candidate["requirement"]),
            int(candidate["deficit"]),
            refs,
        )
    return _sample_support_limitation(refs)


def _actions_from_sample_rule(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidate = _pick_sample_candidate(_collect_unmet_sample_candidates(snapshot))
    if not candidate:
        return []
    return [
        _sample_support_from_numbers(
            int(candidate["n"]),
            int(candidate["k"]),
            str(candidate["rule_label"]),
            int(candidate["requirement"]),
            int(candidate["deficit"]),
            _refs_for_sample_candidate(candidate),
        )
    ]


def _actions_from_precision(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    precisao = _mapping(_validation(snapshot).get("precisao"))
    if not precisao:
        return []
    status = _fold_status(precisao.get("status"))
    refs = [{"kind": "field", "path": "validation.precisao", "status": precisao.get("status")}]
    if status in {"not_computed", "error", "nao_calculado"}:
        tmpl = _TEMPLATE_BY_CODE[CODE_PRECISION_NOT_COMPUTED]
        return [
            _action(
                CODE_PRECISION_NOT_COMPUTED,
                tmpl["priority"],
                tmpl["reason"],
                tmpl["next_step"],
                refs,
                tmpl["limitations"],
            )
        ]
    if status in {"unclassified", "not_classifiable", "nao_classificavel"}:
        tmpl = _TEMPLATE_BY_CODE[CODE_PRECISION_UNCLASSIFIED]
        return [
            _action(
                CODE_PRECISION_UNCLASSIFIED,
                tmpl["priority"],
                tmpl["reason"],
                tmpl["next_step"],
                refs,
                tmpl["limitations"],
            )
        ]
    return []


def _actions_from_documentary(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    documentary = _mapping(_validation(snapshot).get("documentary"))
    refs: List[Any] = []
    declared = False
    if documentary:
        if _is_declared(documentary):
            declared = True
            refs.append(
                {
                    "kind": "field",
                    "path": "validation.documentary",
                    "status": documentary.get("status") or documentary.get("provenance"),
                }
            )
        items = documentary.get("items")
        seq = items if isinstance(items, list) else (list(items.values()) if isinstance(items, Mapping) else [])
        for item in seq:
            if isinstance(item, Mapping) and _is_declared(item):
                declared = True
                refs.append(_item_ref(item, "validation.documentary.items"))
    if not declared:
        return []
    tmpl = _TEMPLATE_BY_CODE[CODE_DOCUMENT_SOURCE]
    return [
        _action(
            CODE_DOCUMENT_SOURCE,
            tmpl["priority"],
            tmpl["reason"],
            tmpl["next_step"],
            refs,
            tmpl["limitations"],
        )
    ]


def _actions_from_target_unit(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    target = snapshot.get("target")
    if not isinstance(target, Mapping) or not target:
        return []
    unit = target.get("unit")
    if unit not in (None, "", "pending"):
        return []
    tmpl = _TEMPLATE_BY_CODE[CODE_RESOLVE_UNIT_OR_PARSE]
    return [
        _action(
            CODE_RESOLVE_UNIT_OR_PARSE,
            tmpl["priority"],
            tmpl["reason"],
            tmpl["next_step"],
            [{"kind": "field", "path": "target.unit", "unit": unit}],
            tmpl["limitations"],
        )
    ]


def _actions_from_reference_date(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if snapshot.get("schema_version") != "MP/1":
        return []
    if snapshot.get("reference_date") not in (None, "", "pending"):
        return []
    tmpl = _TEMPLATE_BY_CODE[CODE_DEFINE_REFERENCE_DATE]
    return [
        _action(
            CODE_DEFINE_REFERENCE_DATE,
            tmpl["priority"],
            tmpl["reason"],
            tmpl["next_step"],
            [{"kind": "field", "path": "reference_date", "reference_date": snapshot.get("reference_date")}],
            tmpl["limitations"],
        )
    ]


def _iter_artifact_states(snapshot: Mapping[str, Any]) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    for container in (
        snapshot.get("artifact_states"),
        _mapping(snapshot.get("provenance")).get("artifact_states"),
        _mapping(snapshot.get("provenance")).get("artifacts"),
    ):
        if not isinstance(container, Mapping):
            continue
        for name, state in container.items():
            if isinstance(state, Mapping):
                yield str(name), state
            elif _norm_code(state) == "failed":
                yield str(name), {"state": "failed"}


def _actions_from_artifacts(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Any] = []
    for name, state in _iter_artifact_states(snapshot):
        if _norm_code(state.get("state")) != "failed":
            continue
        refs.append(
            {
                "kind": "artifact",
                "name": name,
                "state": state.get("state"),
                "error": state.get("error"),
            }
        )
    if not refs:
        return []
    tmpl = _TEMPLATE_BY_CODE[CODE_RECOVER_FAILED_ARTIFACT]
    return [
        _action(
            CODE_RECOVER_FAILED_ARTIFACT,
            tmpl["priority"],
            tmpl["reason"],
            tmpl["next_step"],
            refs,
            tmpl["limitations"],
        )
    ]


def _subject_mapping(snapshot: Mapping[str, Any]) -> Tuple[Mapping[str, Any], bool]:
    for key in ("subject_raw", "subject"):
        if key in snapshot and isinstance(snapshot[key], Mapping):
            return snapshot[key], True
    return {}, False


def _missing_predictors(
    subject: Mapping[str, Any],
    feature_schema: Mapping[str, Any],
) -> List[str]:
    columns = feature_schema.get("columns")
    if not isinstance(columns, Mapping):
        return []
    missing: List[str] = []
    for internal, meta in columns.items():
        if not isinstance(meta, Mapping):
            continue
        role = str(meta.get("role") or "").lower()
        if role not in {"predictor"}:
            continue
        original = meta.get("original_name") or internal
        aliases = {str(internal), str(original)}
        if any(alias in subject for alias in aliases):
            continue
        missing.append(str(original))
    return missing


def _actions_from_subject(
    snapshot: Mapping[str, Any],
    feature_schema: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if not feature_schema:
        return []
    subject, present = _subject_mapping(snapshot)
    if not present:
        return []
    missing = _missing_predictors(subject, feature_schema)
    if not missing:
        return []
    listed = ", ".join(missing)
    return [
        _action(
            CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
            P_SUBJECT,
            f"Característica do sujeito ausente para o modelo: {listed}.",
            "Fornecer a característica do sujeito na unidade e na categoria "
            "compatíveis com o esquema de variáveis-base. Sem esse valor a "
            "previsão do avaliando permanece pendente.",
            [
                {
                    "kind": "field",
                    "path": "subject_raw",
                    "missing": missing,
                }
            ],
            [
                "A ausência de característica não é preenchida por imputação silenciosa.",
                _LIMIT_NO_PERCENT,
            ],
        )
    ]


def _actions_from_item_pendencies(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in _iter_fundamentacao_items(snapshot):
        ident = item.get("item")
        status = _norm_code(item.get("evidence_status") or item.get("status"))
        if ident in (1, "1", "item_1", "item1") and status in {"pending", "not_applicable"}:
            tmpl = _TEMPLATE_BY_CODE[CODE_PROVIDE_SUBJECT_CHARACTERISTIC]
            out.append(
                _action(
                    CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
                    tmpl["priority"],
                    tmpl["reason"],
                    tmpl["next_step"],
                    [_item_ref(item, "validation.fundamentacao.items")],
                    tmpl["limitations"],
                )
            )
        if ident in (4, "4", "item_4", "item4") and (
            status in {"pending"} or item.get("grade") == 0
        ):
            tmpl = _TEMPLATE_BY_CODE[CODE_INVESTIGATE_EXTRAPOLATION]
            out.append(
                _action(
                    CODE_INVESTIGATE_EXTRAPOLATION,
                    tmpl["priority"],
                    tmpl["reason"],
                    tmpl["next_step"],
                    [_item_ref(item, "validation.fundamentacao.items")],
                    tmpl["limitations"],
                )
            )
    return out


def _finite_point(value: Any) -> Optional[float]:
    if isinstance(value, Mapping):
        value = value.get("point")
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _fmt_number(number: float) -> str:
    if float(number).is_integer():
        return str(int(number))
    return format(float(number), ".10g")


def _alternative_identity(alt: Mapping[str, Any]) -> Tuple[Any, Any, Any]:
    target = alt.get("target") if isinstance(alt.get("target"), Mapping) else {}
    unit = target.get("unit")
    estimand = target.get("estimand")
    date = alt.get("reference_date")
    if date is None and isinstance(alt.get("value"), Mapping):
        date = alt["value"].get("reference_date")
    return unit, date, estimand


def _identity_complete(identity: Tuple[Any, Any, Any]) -> bool:
    return all(part not in (None, "") for part in identity)


def _actions_from_alternatives(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = snapshot.get("alternatives")
    if not isinstance(raw, list):
        return []
    alts = [item for item in raw if isinstance(item, Mapping)]
    if len(alts) < 2:
        return []

    complete: List[Tuple[Tuple[Any, Any, Any], Mapping[str, Any], float]] = []
    incomplete: List[Mapping[str, Any]] = []
    for alt in alts:
        point = _finite_point(alt.get("value") if "value" in alt else alt.get("point"))
        identity = _alternative_identity(alt)
        if point is None or not _identity_complete(identity):
            incomplete.append(alt)
            continue
        complete.append((identity, alt, point))

    out: List[Dict[str, Any]] = []
    identities = {item[0] for item in complete}
    if incomplete or len(identities) > 1:
        refs = []
        for alt in alts:
            ident = _alternative_identity(alt)
            refs.append(
                {
                    "kind": "alternative",
                    "candidate_id": alt.get("candidate_id"),
                    "unit": ident[0],
                    "reference_date": ident[1],
                    "estimand": ident[2],
                }
            )
        out.append(
            _action(
                CODE_INCOMPATIBLE_ALTERNATIVE_COMPARISON,
                P_INCOMPATIBLE,
                "Há alternativas com unidade, data-base ou estimand distintos ou ausentes; "
                "a comparação numérica entre elas não é válida nessas condições.",
                "Revisar unidade, data-base e estimand até que as alternativas sejam "
                "comparáveis. Não tratar a diferença entre especificações como medida de precisão.",
                refs,
                [
                    "Comparações só usam valores na mesma unidade, data-base e estimand.",
                    "Ausência de unidade ou data não é preenchida por BRL, BRL/m2 ou data atual.",
                ],
            )
        )
        # O conjunto não é comparável: não emitir sensibilidade numérica
        # (evita fundir grupos com unidade/data/estimand distintos).
        return out

    grouped: Dict[Tuple[Any, Any, Any], List[float]] = defaultdict(list)
    grouped_refs: Dict[Tuple[Any, Any, Any], List[Any]] = defaultdict(list)
    for identity, alt, point in complete:
        grouped[identity].append(point)
        grouped_refs[identity].append(
            {
                "kind": "alternative",
                "candidate_id": alt.get("candidate_id"),
                "unit": identity[0],
                "reference_date": identity[1],
                "estimand": identity[2],
                "point": point,
            }
        )

    for identity, points in grouped.items():
        if len(points) < 2:
            continue
        if max(points) == min(points):
            continue
        pmin, pmax = min(points), max(points)
        out.append(
            _action(
                CODE_REVIEW_VALUE_SENSITIVITY,
                P_SENSITIVITY,
                (
                    "Alternativas com a mesma unidade, data-base e estimand produzem "
                    f"valores pontuais distintos ({_fmt_number(pmin)} e {_fmt_number(pmax)}). "
                    "Isso indica sensibilidade de valor e exige revisão; a diferença "
                    "entre especificações não substitui intervalo de confiança nem o grau de precisão."
                ),
                "Revisar as especificações que geram a divergência e documentar a "
                "sensibilidade de valor. Não tratar essa diferença como medida de precisão.",
                grouped_refs[identity],
                [
                    "A diferença entre alternativas não é intervalo de confiança.",
                    "A diferença entre alternativas não substitui o grau de precisão.",
                    _LIMIT_NO_PERCENT,
                ],
            )
        )
    return out


def _ref_key(ref: Any) -> Tuple[Any, ...]:
    if isinstance(ref, Mapping):
        affected = ref.get("affected_ids")
        missing = ref.get("missing")
        return (
            ref.get("kind"),
            ref.get("code"),
            ref.get("id"),
            ref.get("path"),
            ref.get("name"),
            ref.get("candidate_id"),
            tuple(affected) if isinstance(affected, list) else affected,
            tuple(missing) if isinstance(missing, list) else missing,
            str(ref.get("evidence")),
            ref.get("column") if not isinstance(ref.get("evidence"), Mapping) else None,
        )
    return ("literal", str(ref))


def _merge_refs(left: Sequence[Any], right: Sequence[Any]) -> List[Any]:
    merged: List[Any] = []
    seen = set()
    for ref in list(left) + list(right):
        key = _ref_key(ref)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return merged


def _merge_limitations(left: Sequence[str], right: Sequence[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for item in list(left) + list(right):
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _reason_rank(action: Mapping[str, Any]) -> Tuple[int, int]:
    reason = str(action.get("reason") or "")
    has_deficit = 1 if re.search(r"Déficit de \d+", reason) else 0
    return (has_deficit, len(reason))


def _consolidate(drafts: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    for draft in drafts:
        code = str(draft["code"])
        if code not in index:
            index[code] = len(ordered)
            ordered.append(
                {
                    "code": code,
                    "priority": int(draft["priority"]),
                    "reason": draft["reason"],
                    "next_step": draft["next_step"],
                    "evidence_refs": list(draft.get("evidence_refs") or []),
                    "limitations": list(draft.get("limitations") or []),
                }
            )
            continue
        current = ordered[index[code]]
        current["priority"] = min(int(current["priority"]), int(draft["priority"]))
        current["evidence_refs"] = _merge_refs(current["evidence_refs"], draft.get("evidence_refs") or [])
        current["limitations"] = _merge_limitations(
            current["limitations"], draft.get("limitations") or []
        )
        if _reason_rank(draft) > _reason_rank(current):
            current["reason"] = draft["reason"]
            current["next_step"] = draft["next_step"]
    return ordered


_TEMPLATE_BY_CODE: Dict[str, Dict[str, Any]] = {
    CODE_RESOLVE_UNIT_OR_PARSE: {
        "priority": P_INTEGRITY,
        "reason": "Há unidade não resolvida ou valor com parse ambíguo na entrada.",
        "next_step": (
            "Resolver a unidade e o parse dos valores afetados (locale, separador e "
            "unidade declarada) antes de reprocessar. Não presumir BRL, BRL/m² nem "
            "preencher o alvo ausente."
        ),
        "limitations": [
            "Colisão de nomes ou valores ambíguos não é resolvida silenciosamente.",
            _LIMIT_NO_PERCENT,
        ],
    },
    CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE: {
        "priority": P_INTEGRITY,
        "reason": "Há preço imputado ou ambíguo na variável-alvo; a integridade do valor observado está comprometida.",
        "next_step": (
            "Substituir o preço imputado/ambíguo pelo valor observado de mercado ou "
            "excluir o registro com justificativa. Nenhum valor-alvo ausente deve "
            "ser imputado para fabricar amostra, grau ou R²."
        ),
        "limitations": [
            "Imputação de alvo não é política admissível neste fluxo.",
            _LIMIT_NO_PERCENT,
        ],
    },
    CODE_PROVIDE_SUBJECT_CHARACTERISTIC: {
        "priority": P_SUBJECT,
        "reason": "Falta característica do sujeito (imóvel avaliando) exigida pelo esquema.",
        "next_step": (
            "Fornecer a característica do sujeito na mesma base e unidade das "
            "variáveis do modelo."
        ),
        "limitations": [
            "Sem a característica, extrapolação e previsão do avaliando permanecem pendentes.",
            _LIMIT_NO_PERCENT,
        ],
    },
    CODE_DOCUMENT_SOURCE: {
        "priority": P_SOURCE,
        "reason": "Há fonte documental apenas declarada; ela não foi verificada automaticamente neste resultado.",
        "next_step": (
            "Documentar a fonte no dossiê (comprovante, data e origem) para conferência "
            "do avaliador. Dado declarado não vira comprovação automática."
        ),
        "limitations": [
            "Pontuação documental declarada não é comprovação.",
            "A verificação da fonte é responsabilidade do avaliador.",
        ],
    },
    CODE_REVIEW_INFLUENTIAL_POINT: {
        "priority": P_INFLUENCE,
        "reason": "Há observação influente (alavancagem ou distância de Cook) que pode condicionar o ajuste.",
        "next_step": (
            "Revisar a observação influente no contexto do mercado e da coleta. "
            "Investigar; não remover automaticamente um ponto válido."
        ),
        "limitations": [
            "Influência exige investigação, não exclusão automática.",
            "Excluir um ponto válido só para forçar enquadramento ou coeficiente de determinação não é procedimento aceitável.",
        ],
    },
    CODE_INVESTIGATE_EXTRAPOLATION: {
        "priority": P_EXTRAPOLATION,
        "reason": "Há extrapolação ou característica do avaliando fora do intervalo amostral.",
        "next_step": (
            "Investigar a extrapolação: conferir a característica do avaliando e a "
            "cobertura da amostra. Não forçar o ponto para dentro do intervalo."
        ),
        "limitations": [
            "Extrapolação identificada não autoriza recorte silencioso da amostra.",
            _LIMIT_NO_PERCENT,
        ],
    },
    CODE_CHECK_ASSUMPTION: {
        "priority": P_ASSUMPTION,
        "reason": "Há pressuposto estatístico sinalizado (normalidade, homocedasticidade ou correlato).",
        "next_step": (
            "Conferir o pressuposto com os diagnósticos já calculados e registrar a "
            "limitação no laudo se ele permanecer violado."
        ),
        "limitations": [
            "Pressuposto auxiliar não substitui o enquadramento das tabelas normativas.",
            _LIMIT_NO_PERCENT,
        ],
    },
    CODE_DEFINE_REFERENCE_DATE: {
        "priority": P_DATE,
        "reason": "A data-base da avaliação não está definida.",
        "next_step": (
            "Definir a data-base (e, se couber, a data de vistoria) no pedido. "
            "Não presumir a data atual."
        ),
        "limitations": [
            "Sem data-base, comparações de valor e atualização temporal ficam pendentes.",
        ],
    },
    CODE_RECOVER_FAILED_ARTIFACT: {
        "priority": P_ARTIFACT,
        "reason": "A geração de artefato (PDF ou correlato) falhou.",
        "next_step": (
            "Recuperar o artefato falho: reexecutar a geração do PDF/laudo após "
            "corrigir a causa registrada, sem alterar o cálculo já obtido."
        ),
        "limitations": [
            "Falha de artefato é distinta de falha de cálculo; o valor não deve ser substituído por zero.",
        ],
    },
    CODE_PRECISION_NOT_COMPUTED: {
        "priority": P_PRECISION_NOT_COMPUTED,
        "reason": "O grau de precisão não foi calculado.",
        "next_step": (
            "Informar o imóvel avaliando e os intervalos necessários para apurar a "
            "amplitude e o grau de precisão."
        ),
        "limitations": [
            "Não calculado não é zero nem grau I implícito.",
            "Sem o cálculo não há amplitude classificável.",
        ],
    },
    CODE_PRECISION_UNCLASSIFIED: {
        "priority": P_PRECISION_UNCLASSIFIED,
        "reason": "A precisão foi apurada, mas não é classificável no enquadramento vigente.",
        "next_step": (
            "Revisar amostra, modelo e amplitude; registrar justificativa se a "
            "precisão permanecer não classificável."
        ),
        "limitations": [
            "Não classificável não equivale a grau calculado nem a intervalo normativo extra.",
        ],
    },
    CODE_IMPROVE_FIT_QUALITY: {
        "priority": P_FIT_QUALITY,
        "reason": (
            "O ajuste (R²/R² ajustado) foi sinalizado como limitado para o uso "
            "pretendido. A norma não define piso obrigatório de R²."
        ),
        "next_step": (
            "Revisar especificação, qualidade dos dados e adequação do modelo ao uso. "
            "Não alterar a codificação nem o preço observado só para forçar enquadramento ou o coeficiente de determinação."
        ),
        "limitations": [
            _LIMIT_NO_PERCENT,
            "R² não é critério de enquadramento das tabelas de fundamentação.",
        ],
    },
}


__all__ = [
    "recommend_next_actions",
    "ACTION_KEYS",
    "CODE_RESOLVE_UNIT_OR_PARSE",
    "CODE_RESOLVE_IMPUTED_OR_AMBIGUOUS_PRICE",
    "CODE_PROVIDE_SUBJECT_CHARACTERISTIC",
    "CODE_DOCUMENT_SOURCE",
    "CODE_REVIEW_INFLUENTIAL_POINT",
    "CODE_INVESTIGATE_EXTRAPOLATION",
    "CODE_IMPROVE_SAMPLE_SUPPORT",
    "CODE_CHECK_ASSUMPTION",
    "CODE_DEFINE_REFERENCE_DATE",
    "CODE_RECOVER_FAILED_ARTIFACT",
    "CODE_PRECISION_NOT_COMPUTED",
    "CODE_PRECISION_UNCLASSIFIED",
    "CODE_IMPROVE_FIT_QUALITY",
    "CODE_REVIEW_VALUE_SENSITIVITY",
    "CODE_INCOMPATIBLE_ALTERNATIVE_COMPARISON",
]
