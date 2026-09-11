"""Read search coverage/method from ``search.audit``, not from row counts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, List, Optional


_APPROXIMATE_MODES = frozenset(
    {
        "approximate",
        "heuristic",
        "top_n",
        "fallback",
        "non_exhaustive",
        "partial",
        "budgeted",
    }
)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def interpret_search(search: Any) -> Dict[str, Any]:
    """Describe enumeration coverage from the snapshot search block.

    Prefers ``search.audit.coverage`` (C10 shape). Does not infer exhaustiveness
    from the number of used rows and does not claim a global optimum on a
    partial search.
    """
    block = _as_mapping(search)
    audit = _as_mapping(block.get("audit") or block.get("search_audit"))
    coverage = _as_mapping(audit.get("coverage"))
    budget_raw = audit.get("budget") if "budget" in audit else block.get("budget")
    budget_map = _as_mapping(budget_raw) if isinstance(budget_raw, Mapping) else {}

    enumeration = _text(coverage.get("enumeration")).lower()
    exact_optimum = coverage.get("exact_optimum_guaranteed")
    if exact_optimum is not None:
        exact_optimum = bool(exact_optimum)

    mode = (
        block.get("mode")
        or block.get("kind")
        or audit.get("mode")
        or audit.get("requested_mode")
    )
    mode_text = _text(mode)
    exhaustive_flag = block.get("exhaustive")
    if exhaustive_flag is None and enumeration:
        if enumeration == "exhaustive":
            exhaustive_flag = True
        elif enumeration == "partial":
            exhaustive_flag = False

    approximate = False
    if exhaustive_flag is False:
        approximate = True
    elif exact_optimum is False:
        approximate = True
    elif enumeration == "partial":
        approximate = True
    elif mode_text.lower() in _APPROXIMATE_MODES:
        approximate = True

    evaluated = _as_int(block.get("combinations_tested") or block.get("evaluated") or audit.get("evaluated"))
    possible = _as_int(audit.get("possible") or coverage.get("possible"))
    generated = _as_int(audit.get("generated"))
    rejected = _as_int(audit.get("rejected"))
    budget_max = _as_int(budget_map.get("max_evaluations") if budget_map else None)
    if budget_max is None and not isinstance(budget_raw, Mapping):
        budget_max = _as_int(budget_raw) or _as_int(block.get("budget"))

    limitations: List[str] = []
    for item in (
        list(block.get("limitations") or [])
        + list(audit.get("limitations") or [])
        + ([coverage.get("optimum_disclaimer")] if coverage.get("optimum_disclaimer") else [])
    ):
        text = _text(item)
        if not text:
            continue
        # Drop English implementation jargon; Portuguese explanation is composed below.
        if "exact_optimum_guaranteed" in text or "Partial coverage or an unproven prune" in text:
            continue
        if text not in limitations:
            limitations.append(text)

    coverage_known = bool(
        enumeration
        or exact_optimum is not None
        or exhaustive_flag is not None
        or mode_text
    )

    summary = ""
    if approximate:
        parts = [
            "A busca não enumerou todo o espaço considerado, ou não aplicou o "
            "critério de ranking completo a cada especificação."
        ]
        if evaluated is not None and possible is not None and possible > 0:
            parts.append(
                f"Foram avaliadas {evaluated} especificações de {possible} possíveis no espaço declarado."
            )
        elif evaluated is not None:
            parts.append(f"Foram avaliadas {evaluated} especificações.")
        parts.append(
            "O resultado selecionado é o melhor entre as especificações efetivamente "
            "avaliadas; isso não é garantia de ótimo global."
        )
        summary = " ".join(parts)
        if not any("ótimo global" in item for item in limitations):
            limitations.append(
                "Cobertura parcial da busca não autoriza afirmar ótimo global nem "
                "avaliação completa do critério de ranking."
            )
    elif exhaustive_flag is True or enumeration == "exhaustive":
        extra = f" ({evaluated} especificações avaliadas)" if evaluated is not None else ""
        if exact_optimum is False:
            summary = (
                f"A enumeração foi declarada exaustiva{extra}, mas o critério de ranking "
                "completo não foi aplicado a todos os candidatos. Não há garantia de ótimo global."
            )
            approximate = True
        else:
            summary = (
                f"A busca enumerou o espaço declarado{extra} e o critério de ranking "
                "completo foi o utilizado na seleção. Isso descreve a cobertura da "
                "enumeração, não uma aprovação do valor."
            )
    elif not coverage_known:
        summary = ""
    else:
        summary = (
            "A cobertura da busca foi registrada no snapshot; a ausência de ótimo "
            "global explícito não é preenchida por esta minuta."
        )

    objective = _text(block.get("objective") or _as_mapping(audit.get("objective")).get("name") or "")
    if not objective:
        obj_map = _as_mapping(audit.get("objective"))
        objective = _text(obj_map.get("primary") or obj_map.get("kind") or "")

    return {
        "audit": audit,
        "coverage": coverage,
        "enumeration": enumeration or None,
        "exact_optimum_guaranteed": exact_optimum,
        "exhaustive": exhaustive_flag,
        "approximate": approximate,
        "coverage_known": coverage_known,
        "mode": mode_text,
        "evaluated": evaluated,
        "possible": possible,
        "generated": generated,
        "rejected": rejected,
        "budget": budget_max,
        "objective": objective,
        "summary": summary,
        "limitations": limitations,
        "message": _text(block.get("message")),
        "winner_candidate_id": _text(block.get("winner_candidate_id") or audit.get("best_so_far_candidate_id")),
    }
