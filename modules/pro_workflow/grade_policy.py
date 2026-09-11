"""Normalize historical minimum-fundamentação grade aliases at the contract boundary."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

CANONICAL_GRADE_KEY = "minimum_fundamentacao_grade"
GRADE_ALIAS_CONFLICT = "GRADE_ALIAS_CONFLICT"

# Historical spellings actually accepted by API, legacy adapter, UI payload, or ranking.
SEARCH_ALIASES = (
    "minimum_fundamentacao_grade",
    "min_fundamentacao_grade",
    "target_degree",
)
EVAL_ALIASES = (
    "minimum_fundamentacao_grade",
    "min_fundamentacao_grade",
    "target_degree",
)
TOPLEVEL_ALIASES = (
    "minimum_fundamentacao_grade",
    "min_fundamentacao_grade",
    "target_degree",
)

GRADE_REQUIREMENT_STATUSES = frozenset(
    {"not_requested", "met", "not_met", "pending", "error"}
)


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    return {}


def canonical_minimum_grade(spec: Mapping[str, Any]) -> Optional[int]:
    search = _as_mapping(spec.get("search_policy"))
    if CANONICAL_GRADE_KEY in search:
        value = search.get(CANONICAL_GRADE_KEY)
        return None if value is None else int(value)
    return None


def _collect_alias_values(spec: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    found: List[Tuple[str, Any]] = []
    for key in TOPLEVEL_ALIASES:
        if key in spec:
            found.append((key, spec.get(key)))
    search = spec.get("search_policy")
    if isinstance(search, Mapping):
        for key in SEARCH_ALIASES:
            if key in search:
                found.append((f"search_policy.{key}", search.get(key)))
    evaluation = spec.get("evaluation_policy")
    if isinstance(evaluation, Mapping):
        for key in EVAL_ALIASES:
            if key in evaluation:
                found.append((f"evaluation_policy.{key}", evaluation.get(key)))
    return found


def _normalize_int_or_null(value: Any, field: str, validate_degree) -> Optional[int]:
    return validate_degree(value, field=field)


def normalize_grade_aliases(
    spec: MutableMapping[str, Any],
    *,
    validate_degree,
    request_spec_error,
    make_issue,
) -> List[dict]:
    """Fold historical aliases into search_policy.minimum_fundamentacao_grade.

    Conflicting present values raise request_spec_error. Equivalent values
    are kept on the original keys and copied to the canonical key. Internal
    ranking may keep min_fundamentacao_grade as an equivalent adapter key.
    """
    issues: List[dict] = []
    collected = _collect_alias_values(spec)
    if not collected:
        search = dict(_as_mapping(spec.get("search_policy")))
        if search and CANONICAL_GRADE_KEY not in search:
            search[CANONICAL_GRADE_KEY] = None
            spec["search_policy"] = search
        return issues

    normalized: List[Tuple[str, Optional[int]]] = []
    for field, raw in collected:
        normalized.append((field, _normalize_int_or_null(raw, field, validate_degree)))

    values = [item[1] for item in normalized]
    unique = {v for v in values}
    if len(unique) > 1:
        evidence = {field: value for field, value in normalized}
        raise request_spec_error(
            "conflicting minimum fundamentacao grade aliases",
            [
                make_issue(
                    GRADE_ALIAS_CONFLICT,
                    "Aliases of the minimum fundamentação grade disagree; no silent precedence.",
                    evidence={"aliases": evidence},
                )
            ],
        )

    canonical = values[0]
    search = dict(_as_mapping(spec.get("search_policy")))
    evaluation = dict(_as_mapping(spec.get("evaluation_policy")))
    search[CANONICAL_GRADE_KEY] = canonical
    # Preserve historical keys when they were present so adapters remain equivalent.
    if "target_degree" in search or any(k.endswith("target_degree") for k, _ in collected):
        search["target_degree"] = canonical
    evaluation[CANONICAL_GRADE_KEY] = canonical
    # Ranking adapter currently reads min_fundamentacao_grade.
    evaluation["min_fundamentacao_grade"] = canonical
    spec["search_policy"] = search
    if spec.get("evaluation_policy") is not None or evaluation:
        spec["evaluation_policy"] = evaluation
    return issues


def classify_grade_requirement_status(
    *,
    requested: Any,
    fundamentacao: Any,
    documentary: Any = None,
    verification_status: Any = None,
) -> str:
    """Producer-only status from evidence. Missing is not not_requested and not met."""
    if requested is None:
        return "not_requested"
    try:
        requested_i = int(requested)
    except (TypeError, ValueError):
        return "error"

    fund = _as_mapping(fundamentacao)
    doc = _as_mapping(documentary)
    pending_items = fund.get("pending_items")
    evidence_status = fund.get("evidence_status") or fund.get("status")
    grade = fund.get("grade")
    if grade is None and "grau" in fund:
        grade = fund.get("grau")

    if verification_status == "error":
        return "error"
    if evidence_status in {"error"}:
        return "error"

    documentary_pending = False
    if isinstance(pending_items, (list, tuple)) and pending_items:
        documentary_pending = True
    if evidence_status in {"pending", "pendente"}:
        documentary_pending = True
    doc_status = doc.get("status")
    if doc_status in {"pending", "pendente"}:
        documentary_pending = True
    if fund.get("grade") is None and requested_i is not None:
        # C03: null/pending is not approval. A requested grade cannot be met.
        if documentary_pending or evidence_status in {None, "pending", "pendente"}:
            return "pending"
        if verification_status in {"pending", None} and grade is None:
            return "pending"

    if grade is None:
        return "pending"
    try:
        grade_i = int(grade)
    except (TypeError, ValueError):
        return "error"
    if documentary_pending:
        return "pending"
    if grade_i >= requested_i:
        return "met"
    return "not_met"
