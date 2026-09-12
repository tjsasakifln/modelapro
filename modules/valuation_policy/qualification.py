"""MP-QUAL/1 qualification context composed by C01; C05 owns the rule catalogue."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

QUALIFICATION_SCHEMA = "MP-QUAL/1"
PROFILE_REQUIRED = (
    "id",
    "version",
    "source_set_sha256",
    "purpose",
    "value_basis",
    "method",
    "asset_scope",
    "recipient_id",
)
RULE_STATUSES = frozenset(
    {
        "passed",
        "failed",
        "pending_manual",
        "not_applicable",
        "unsupported",
        "unverified",
        "error",
    }
)
GRADE_STATUSES = frozenset({"not_requested", "met", "not_met", "pending", "error"})
CASE_RELEASE_STATUSES = frozenset(
    {
        "analysis_only",
        "review_required",
        "ready_for_professional_signoff",
        "signed_integrity_verified",
    }
)
CALCULATION_STATUSES = frozenset(
    {"fitted", "rejected", "error", "cancelled", "unsupported", "not_computed"}
)

# Existing MP/1 issuance names remain the JSON values freeze accepts.
ISSUANCE_TO_RELEASE = {
    "draft": "analysis_only",
    "review_required": "review_required",
    "ready_for_professional_review": "ready_for_professional_signoff",
}
RELEASE_TO_ISSUANCE = {
    "analysis_only": "draft",
    "review_required": "review_required",
    "ready_for_professional_signoff": "ready_for_professional_review",
    "signed_integrity_verified": "ready_for_professional_review",
}

KNOWN_VALUE_BASES = frozenset(
    {
        "market",
        "reconstruction_cost",
        "replacement_cost",
        "depreciated_cost",
        "guarantee_limit",
        "adopted",
        "arbitrated",
    }
)
KNOWN_METHODS = frozenset({"comparative_regression", "reconstruction_cost", "replacement_cost"})
KNOWN_PURPOSES = frozenset(
    {
        "market_analysis",
        "professional_report",
        "mortgage",
        "insurance",
        "preview",
        "teste de contrato",
        "aceite-integracao",
        "p01-synthetic-acceptance",
        "c01-acceptance",
        "c01-gold",
        "c01-inapto",
    }
)


class QualificationProfileError(ValueError):
    def __init__(self, message: str, issues: Optional[Sequence[Mapping[str, Any]]] = None):
        super().__init__(message)
        self.issues = [dict(i) for i in (issues or [])]


def _issue(code: str, message: str, **evidence: Any) -> dict:
    from modules.result_contract import make_issue

    return make_issue(code, message, origin="c01.qualification", evidence=evidence or None)


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, Mapping):
        return dict(obj)
    return {}


def validate_qualification_profile(raw: Any) -> dict:
    """Structural validation. Unknown id is not a type error; it stays unresolved."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise QualificationProfileError(
            "qualification_profile must be a mapping",
            [_issue("TYPE_ERROR", "qualification_profile must be a mapping")],
        )
    profile = dict(raw)
    missing = [k for k in PROFILE_REQUIRED if k not in profile]
    if missing:
        raise QualificationProfileError(
            "qualification_profile missing required keys",
            [_issue("MISSING_FIELD", "qualification_profile missing keys", missing=missing)],
        )
    for key in PROFILE_REQUIRED:
        value = profile.get(key)
        if key == "source_set_sha256":
            if value is None:
                profile[key] = None
                continue
            if not isinstance(value, str) or len(value) < 16:
                raise QualificationProfileError(
                    "source_set_sha256 invalid",
                    [_issue("TYPE_ERROR", "source_set_sha256 must be a hex digest or null")],
                )
            continue
        if not isinstance(value, str) or not value.strip():
            raise QualificationProfileError(
                f"qualification_profile.{key} must be a non-empty string",
                [_issue("TYPE_ERROR", f"qualification_profile.{key} must be a non-empty string")],
            )
        profile[key] = value.strip()
    return profile


def resolve_qualification_profile(spec: Mapping[str, Any]) -> Dict[str, Any]:
    raw = spec.get("qualification_profile")
    if not raw:
        return {
            "resolved": False,
            "reason": "not_provided",
            "profile": None,
            "known": False,
        }
    profile = validate_qualification_profile(raw)
    catalogue = _try_c05_catalogue()
    known = False
    if catalogue is not None:
        getter = getattr(catalogue, "get_profile", None) or getattr(catalogue, "resolve", None)
        if callable(getter):
            found = getter(profile)
            known = bool(found)
        elif isinstance(catalogue, Mapping):
            known = profile["id"] in catalogue
    return {
        "resolved": True,
        "reason": "provided",
        "profile": profile,
        "known": known if catalogue is not None else False,
        "catalogue_available": catalogue is not None,
    }


def _try_c05_catalogue() -> Any:
    try:
        from modules import qualification_profile as qp  # type: ignore
    except Exception:
        return None
    return qp


def _try_assess_qualification(context: Mapping[str, Any], profile: Optional[Mapping[str, Any]]) -> Any:
    try:
        from modules.qualification_profile import assess_qualification  # type: ignore
    except Exception:
        return None
    if not callable(assess_qualification) or not profile:
        return None
    return assess_qualification(context, profile)


def fingerprint_result(
    *,
    value: Mapping[str, Any],
    model: Mapping[str, Any],
    sample: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    input_sha256: str,
    code_sha: str,
    calculation_version: Any = None,
) -> str:
    payload = {
        "value": dict(value),
        "model": {
            "candidate_id": model.get("candidate_id"),
            "coefficients": model.get("coefficients"),
            "formula": model.get("formula"),
        },
        "sample": {
            "used_row_ids": list(sample.get("used_row_ids") or []),
            "used": sample.get("used"),
            "observed_target": sample.get("observed_target"),
        },
        "search_policy": (request_spec.get("search_policy") or {}),
        "evaluation_policy": (request_spec.get("evaluation_policy") or {}),
        "qualification_profile": (request_spec.get("qualification_profile") or {}),
        "input_sha256": input_sha256,
        "code_sha": code_sha,
        "calculation_version": calculation_version,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _empty_rule(
    *,
    rule_id: str,
    status: str,
    explanation: str,
    applicability: str = "applicable",
    source_id: str = "c01.engine",
    clause: str = "",
    observed: Any = None,
    evidence_refs: Optional[Sequence[str]] = None,
) -> dict:
    if status not in RULE_STATUSES:
        status = "error"
    return {
        "rule_id": rule_id,
        "source_id": source_id,
        "edition_or_version": "MP-COM/2",
        "clause": clause,
        "applicability": applicability,
        "status": status,
        "observed": observed,
        "criterion_ref": rule_id,
        "evidence_refs": list(evidence_refs or []),
        "explanation": explanation,
    }


def _calculation_status(winner: Any, issues: Sequence[Mapping[str, Any]]) -> str:
    codes = {i.get("code") for i in issues if isinstance(i, Mapping)}
    if "NO_WINNER" in codes and winner is None:
        return "rejected"
    if any(i.get("severity") == "error" and i.get("code") in {"rank_deficient", "numerical_failure"} for i in issues if isinstance(i, Mapping)):
        return "error"
    if winner is None:
        return "rejected"
    status = winner.get("status") if isinstance(winner, Mapping) else getattr(winner, "status", None)
    if status in CALCULATION_STATUSES:
        return str(status)
    return "fitted"


def derive_case_release_status(
    *,
    grade_status: str,
    calculation_status: str,
    profile_resolved: bool,
    profile_known: bool,
    rule_results: Sequence[Mapping[str, Any]],
    cost_blocked: bool = False,
) -> str:
    if calculation_status in {"error", "rejected", "unsupported"}:
        return "analysis_only"
    decisive_unverified = False
    decisive_failed = False
    for rule in rule_results:
        if not isinstance(rule, Mapping):
            continue
        if rule.get("applicability") not in {None, "applicable", "decisive"}:
            continue
        if rule.get("status") == "failed":
            decisive_failed = True
        if rule.get("status") in {"unverified", "unsupported", "error"}:
            decisive_unverified = True
        if rule.get("status") == "not_applicable" and not rule.get("explanation"):
            decisive_unverified = True
    if cost_blocked or decisive_failed:
        return "analysis_only"
    if calculation_status != "fitted":
        return "analysis_only"
    if grade_status in {"not_met", "error"}:
        return "analysis_only"
    if not profile_resolved:
        if grade_status == "met":
            return "review_required"
        if grade_status == "pending":
            return "review_required"
        return "analysis_only"
    if not profile_known or decisive_unverified:
        if grade_status in {"met", "pending"}:
            return "review_required"
        return "analysis_only"
    if grade_status in {"met", "not_requested"}:
        return "ready_for_professional_signoff"
    if grade_status == "pending":
        return "review_required"
    return "analysis_only"


def map_issuance_status(case_release_status: str) -> str:
    return RELEASE_TO_ISSUANCE.get(case_release_status, "draft")


def invalidate_reviews_on_material_change(
    previous_fingerprint: Optional[str],
    current_fingerprint: str,
    review_events: Sequence[Mapping[str, Any]],
) -> List[dict]:
    out: List[dict] = []
    for event in review_events or []:
        if not isinstance(event, Mapping):
            continue
        item = dict(event)
        bound = item.get("result_fingerprint") or item.get("fingerprint")
        if bound and bound != current_fingerprint:
            item["valid"] = False
            item["invalidated_reason"] = "material_change"
            item["superseded_by_fingerprint"] = current_fingerprint
        elif previous_fingerprint and previous_fingerprint != current_fingerprint:
            item["valid"] = False
            item["invalidated_reason"] = "material_change"
            item["superseded_by_fingerprint"] = current_fingerprint
        out.append(item)
    return out


def compose_qualification_context(
    *,
    request_spec: Mapping[str, Any],
    snapshot_draft: Mapping[str, Any],
    winner: Any = None,
    search_audit: Optional[Mapping[str, Any]] = None,
    issues: Optional[Sequence[Mapping[str, Any]]] = None,
    review_events: Optional[Sequence[Mapping[str, Any]]] = None,
    cost_result: Optional[Mapping[str, Any]] = None,
    previous_fingerprint: Optional[str] = None,
) -> Dict[str, Any]:
    spec = dict(request_spec)
    resolved = resolve_qualification_profile(spec)
    profile = resolved.get("profile")
    workflow = _as_mapping(_as_mapping(snapshot_draft.get("provenance")).get("workflow_context"))
    grade_status = workflow.get("grade_requirement_status") or "not_requested"
    if grade_status not in GRADE_STATUSES:
        grade_status = "error"
    issue_list = [dict(i) for i in (issues or snapshot_draft.get("issues") or []) if isinstance(i, Mapping)]
    calc_status = _calculation_status(winner if isinstance(winner, Mapping) else _as_mapping(winner), issue_list)

    engine_rules: List[dict] = []
    engine_rules.append(
        _empty_rule(
            rule_id="c01.numeric_fit",
            status="passed" if calc_status == "fitted" else "failed",
            explanation="Numeric/technical fit of the comparative-regression engine.",
            observed={"calculation_status": calc_status},
            evidence_refs=["model.diagnostics"],
        )
    )
    if grade_status == "not_requested":
        engine_rules.append(
            _empty_rule(
                rule_id="c01.grade_requirement",
                status="not_applicable",
                applicability="not_applicable",
                explanation="No minimum fundamentação grade was requested on this profile.",
                observed={"grade_requirement_status": grade_status},
            )
        )
    elif grade_status == "met":
        engine_rules.append(
            _empty_rule(
                rule_id="c01.grade_requirement",
                status="passed",
                explanation="Requested minimum fundamentação grade is met by C05/legacy classifier facts.",
                observed={"grade_requirement_status": grade_status},
                evidence_refs=["validation.fundamentacao"],
            )
        )
    elif grade_status in {"not_met", "pending"}:
        engine_rules.append(
            _empty_rule(
                rule_id="c01.grade_requirement",
                status="pending_manual" if grade_status == "pending" else "failed",
                explanation="Requested grade is not demonstrated; calculation may still be an analysis.",
                observed={"grade_requirement_status": grade_status},
                evidence_refs=["validation.fundamentacao"],
            )
        )
    else:
        engine_rules.append(
            _empty_rule(
                rule_id="c01.grade_requirement",
                status="error",
                explanation="Grade requirement could not be classified.",
                observed={"grade_requirement_status": grade_status},
            )
        )

    cost_blocked = False
    if cost_result:
        if not cost_result.get("computable"):
            cost_blocked = True
            engine_rules.append(
                _empty_rule(
                    rule_id="c01.reconstruction_cost",
                    status="failed" if cost_result.get("items") else "unverified",
                    explanation=str(cost_result.get("reason") or "Cost route not computable."),
                    observed={"computable": False},
                )
            )
        else:
            engine_rules.append(
                _empty_rule(
                    rule_id="c01.reconstruction_cost",
                    status="passed",
                    explanation="Reconstruction/replacement cost computed from an explicit BOM.",
                    observed={"point": (cost_result.get("value") or {}).get("point")},
                    evidence_refs=["cost_bom"],
                )
            )

    c05_bundle = None
    if resolved.get("resolved") and profile:
        context = {
            "request_spec": spec,
            "snapshot": snapshot_draft,
            "search_audit": dict(search_audit or {}),
            "engine_rules": engine_rules,
            "calculation_status": calc_status,
            "grade_requirement_status": grade_status,
        }
        c05_bundle = _try_assess_qualification(context, profile)

    rule_results = list(engine_rules)
    if isinstance(c05_bundle, Mapping):
        extra = c05_bundle.get("rule_results") or c05_bundle.get("rules") or []
        for item in extra:
            if isinstance(item, Mapping) and item.get("rule_id"):
                status = item.get("status")
                if status not in RULE_STATUSES:
                    item = dict(item)
                    item["status"] = "error"
                if item.get("status") == "not_applicable" and not item.get("explanation"):
                    item = dict(item)
                    item["status"] = "unverified"
                    item["explanation"] = "not_applicable requires a profile/source reason"
                if item.get("status") == "passed" and item.get("unverified"):
                    item = dict(item)
                    item["status"] = "unverified"
                rule_results.append(dict(item))
    elif resolved.get("resolved") and profile and not resolved.get("catalogue_available"):
        rule_results.append(
            _empty_rule(
                rule_id="c05.catalogue",
                status="unverified",
                source_id="c05.qualification_profile",
                explanation="C05 assess_qualification is not importable on this HEAD; decisive rules stay unverified.",
                applicability="decisive",
            )
        )
    elif resolved.get("resolved") and profile and not resolved.get("known"):
        rule_results.append(
            _empty_rule(
                rule_id="c05.profile_unknown",
                status="unsupported",
                source_id="c05.qualification_profile",
                explanation="Profile id is not in the C05 catalogue.",
                applicability="decisive",
                observed={"id": profile.get("id")},
            )
        )

    fingerprint = fingerprint_result(
        value=_as_mapping(snapshot_draft.get("value")),
        model=_as_mapping(snapshot_draft.get("model")),
        sample=_as_mapping(snapshot_draft.get("sample")),
        request_spec=spec,
        input_sha256=str(snapshot_draft.get("input_sha256") or ""),
        code_sha=str(snapshot_draft.get("code_sha") or ""),
        calculation_version=_as_mapping(snapshot_draft.get("provenance")).get("calculation_version"),
    )
    events = invalidate_reviews_on_material_change(previous_fingerprint, fingerprint, review_events or [])
    release = derive_case_release_status(
        grade_status=grade_status,
        calculation_status=calc_status,
        profile_resolved=bool(resolved.get("resolved") and profile),
        profile_known=bool(resolved.get("known")),
        rule_results=rule_results,
        cost_blocked=cost_blocked,
    )
    if any(r.get("status") == "unverified" and r.get("applicability") == "decisive" for r in rule_results):
        if release == "ready_for_professional_signoff":
            release = "review_required"

    return {
        "schema_version": QUALIFICATION_SCHEMA,
        "profile": profile,
        "profile_resolved": bool(resolved.get("resolved") and profile),
        "profile_known": bool(resolved.get("known")),
        "versions": {
            "qualification_schema": QUALIFICATION_SCHEMA,
            "result_schema": snapshot_draft.get("schema_version"),
            "calculation_version": _as_mapping(snapshot_draft.get("provenance")).get("calculation_version"),
        },
        "result_fingerprint": fingerprint,
        "calculation_status": calc_status,
        "rule_results": rule_results,
        "grade_requirement_status": grade_status,
        "case_release_status": release,
        "review_events": events,
        "institution_acceptance": None,
        "limitations": list(
            _as_mapping(_as_mapping(snapshot_draft.get("validation")).get("statistical")).get("limitations")
            or []
        ),
    }
