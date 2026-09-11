"""MP-PRO/1 provenance.workflow_context producer. Consumers do not reclassify."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .grade_policy import (
    CANONICAL_GRADE_KEY,
    classify_grade_requirement_status,
)

WORKFLOW_SCHEMA = "MP-PRO/1"
SELECTION_SCOPES = frozenset({"population_model", "subject_specific", "unknown"})


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    return {}


def build_workflow_context(
    *,
    request_spec: Optional[Mapping[str, Any]] = None,
    subject_raw: Any = None,
    validation: Optional[Mapping[str, Any]] = None,
    search_audit: Optional[Mapping[str, Any]] = None,
    frozen_project: Optional[Mapping[str, Any]] = None,
    limitation_codes: Optional[Sequence[str]] = None,
    issues: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    spec = _as_mapping(request_spec)
    search_policy = _as_mapping(spec.get("search_policy"))
    audit = _as_mapping(search_audit)
    frozen = _as_mapping(frozen_project)
    val = _as_mapping(validation)

    requested = search_policy.get(CANONICAL_GRADE_KEY)
    if requested is None and "target_degree" in search_policy:
        requested = search_policy.get("target_degree")

    fundamentacao = _as_mapping(val.get("fundamentacao"))
    documentary = _as_mapping(val.get("documentary"))
    verification = val.get("normative_verification_status") or val.get("verification_status")
    grade_status = classify_grade_requirement_status(
        requested=requested,
        fundamentacao=fundamentacao,
        documentary=documentary,
        verification_status=verification,
    )

    scope = (
        audit.get("selection_scope")
        or frozen.get("model_scope")
        or search_policy.get("model_scope")
        or spec.get("model_scope")
    )
    if scope not in SELECTION_SCOPES:
        scope = "unknown" if scope is None else (
            scope if scope in SELECTION_SCOPES else "unknown"
        )
    if frozen.get("model_scope") in SELECTION_SCOPES and scope == "unknown":
        scope = frozen.get("model_scope")
    if search_policy.get("model_scope") in SELECTION_SCOPES and scope == "unknown":
        scope = search_policy.get("model_scope")
    if frozen.get("model_scope") in {"population_model", "subject_specific"}:
        # Freeze is the reusable declaration; audit may refine conditioning.
        scope = frozen.get("model_scope") if frozen.get("model_scope") in SELECTION_SCOPES else scope

    conditioned = audit.get("selection_conditioned_on_subject")
    if conditioned is None:
        conditioned = frozen.get("selection_conditioned_on_subject")
    if conditioned is None and scope == "subject_specific":
        conditioned = True
    if conditioned is None and scope == "population_model":
        conditioned = False

    codes: List[str] = []
    for item in limitation_codes or []:
        if item and str(item) not in codes:
            codes.append(str(item))
    for issue in issues or []:
        if not isinstance(issue, Mapping):
            continue
        code = issue.get("code")
        if code and str(code) not in codes and issue.get("severity") in {"warning", "error"}:
            codes.append(str(code))
    for item in list(_as_mapping(val.get("statistical")).get("limitations") or []):
        if item and str(item) not in codes:
            codes.append(str(item))

    subject = None
    if isinstance(subject_raw, Mapping):
        subject = dict(subject_raw)
    elif subject_raw is None:
        subject = None

    try:
        requested_out = None if requested is None else int(requested)
    except (TypeError, ValueError):
        requested_out = None
        if grade_status != "error":
            grade_status = "error"

    return {
        "schema_version": WORKFLOW_SCHEMA,
        "subject_raw": subject,
        "requested_minimum_grade": requested_out,
        "grade_requirement_status": grade_status if grade_status in {
            "not_requested", "met", "not_met", "pending", "error"
        } else "error",
        "selection_scope": scope if scope in SELECTION_SCOPES else "unknown",
        "selection_conditioned_on_subject": None if conditioned is None else bool(conditioned),
        "limitation_codes": codes,
    }
