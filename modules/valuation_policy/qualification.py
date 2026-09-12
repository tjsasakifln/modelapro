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
    """Validate a complete wire reference against the installed C05 catalog.

    A profile reference is an immutable identity, not client supplied metadata.
    The id, version, source digest and semantic fields must all describe the
    same catalog row.  This also makes an empty/missing installed catalog fail
    closed at the RequestSpec boundary.
    """
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
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in value)
            ):
                raise QualificationProfileError(
                    "source_set_sha256 invalid",
                    [_issue("TYPE_ERROR", "source_set_sha256 must be a 64-character hex digest")],
                )
            profile[key] = value.lower()
            continue
        if not isinstance(value, str) or not value.strip():
            raise QualificationProfileError(
                f"qualification_profile.{key} must be a non-empty string",
                [_issue("TYPE_ERROR", f"qualification_profile.{key} must be a non-empty string")],
            )
        profile[key] = value.strip()
    recipient = profile.get("recipient_id")
    if recipient is not None:
        if not isinstance(recipient, str) or not recipient.strip():
            raise QualificationProfileError(
                "qualification_profile.recipient_id must be a non-empty string when provided",
                [_issue("TYPE_ERROR", "qualification_profile.recipient_id must be a non-empty string")],
            )
        profile["recipient_id"] = recipient.strip()
    resolved = resolve_qualification_profile({"qualification_profile": profile}, validate=False)
    if not resolved.get("known"):
        raise QualificationProfileError(
            "qualification_profile does not match the installed catalog",
            list(resolved.get("issues") or [
                _issue(
                    "QUALIFICATION_PROFILE_UNKNOWN",
                    "qualification_profile could not be resolved by the installed catalog",
                    profile_id=profile.get("id"),
                )
            ]),
        )
    return profile


def resolve_qualification_profile(
    spec: Mapping[str, Any], *, validate: bool = True
) -> Dict[str, Any]:
    raw = spec.get("qualification_profile")
    if not raw:
        return {
            "resolved": False,
            "reason": "not_provided",
            "profile": None,
            "known": False,
        }
    profile = validate_qualification_profile(raw) if validate else dict(raw)
    catalogue = _try_c05_catalogue()
    issues: List[dict] = []
    canonical = None
    if catalogue is not None:
        resolver = getattr(catalogue, "resolve_profile", None)
        loader = getattr(catalogue, "load_catalog", None)
        if callable(resolver):
            try:
                candidate = resolver(profile)
            except Exception as exc:
                issues.append(_issue("QUALIFICATION_CATALOG_ERROR", str(exc)))
            else:
                if isinstance(candidate, Mapping) and candidate.get("resolved") is True:
                    canonical = dict(candidate)
        catalog_row = None
        if callable(loader):
            try:
                catalog_row = (loader() or {}).get(profile.get("id"))
            except Exception as exc:
                issues.append(_issue("QUALIFICATION_CATALOG_ERROR", str(exc)))
        if canonical is not None:
            expected = dict(catalog_row or canonical)
            mismatches = {}
            for field in PROFILE_REQUIRED:
                expected_value = expected.get(field)
                observed = profile.get(field)
                if str(observed) != str(expected_value):
                    mismatches[field] = {"requested": observed, "catalog": expected_value}
            expected_recipient = expected.get("recipient_id")
            if expected_recipient not in (None, "") and str(profile.get("recipient_id")) != str(expected_recipient):
                mismatches["recipient_id"] = {
                    "requested": profile.get("recipient_id"),
                    "catalog": expected_recipient,
                }
            if mismatches:
                issues.append(
                    _issue(
                        "QUALIFICATION_PROFILE_MISMATCH",
                        "qualification_profile fields differ from the installed catalog",
                        profile_id=profile.get("id"),
                        mismatches=mismatches,
                    )
                )
                canonical = None
    if catalogue is None:
        issues.append(
            _issue(
                "QUALIFICATION_CATALOG_UNAVAILABLE",
                "the installed C05 qualification catalog is unavailable",
            )
        )
    return {
        "resolved": canonical is not None,
        "reason": "catalog_match" if canonical is not None else "catalog_rejected",
        "profile": canonical if canonical is not None else profile,
        "known": canonical is not None,
        "catalogue_available": catalogue is not None,
        "issues": issues,
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
    if not callable(assess_qualification) or profile is None:
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
    normative_assessment: Optional[Mapping[str, Any]] = None,
    institution_receipt: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    del previous_fingerprint  # staleness is decided from each event's bound digest by C05.
    spec = dict(request_spec)
    resolved = resolve_qualification_profile(spec)
    profile = resolved.get("profile")
    profile_omitted = resolved.get("reason") == "not_provided"
    if not profile_omitted and (not resolved.get("known") or not profile):
        raise QualificationProfileError(
            "qualification_profile is not resolvable",
            list(resolved.get("issues") or []),
        )

    issue_list = [
        dict(item)
        for item in (issues or snapshot_draft.get("issues") or [])
        if isinstance(item, Mapping)
    ]
    calc_status = _calculation_status(
        winner if isinstance(winner, Mapping) else _as_mapping(winner), issue_list
    )
    search_policy = _as_mapping(spec.get("search_policy"))
    requested_grade = search_policy.get("minimum_fundamentacao_grade")
    if requested_grade is None:
        requested_grade = _as_mapping(spec.get("evaluation_policy")).get(
            "minimum_fundamentacao_grade"
        )

    provenance = _as_mapping(snapshot_draft.get("provenance"))
    material = {
        "schema_version": snapshot_draft.get("schema_version"),
        "input_sha256": snapshot_draft.get("input_sha256"),
        "code_sha": snapshot_draft.get("code_sha"),
        "reference_date": snapshot_draft.get("reference_date"),
        "target": snapshot_draft.get("target"),
        "value": snapshot_draft.get("value"),
        "sample": snapshot_draft.get("sample"),
        "model": snapshot_draft.get("model"),
        "request": {
            "qualification_profile": spec.get("qualification_profile"),
            "search_policy": spec.get("search_policy"),
            "evaluation_policy": spec.get("evaluation_policy"),
            "units": spec.get("units"),
            "target_unit": spec.get("target_unit"),
            "reference_date": spec.get("reference_date"),
            "inspection_date": spec.get("inspection_date"),
            "declared_documentary": spec.get("declared_documentary"),
        },
        "calculation_version": provenance.get("calculation_version"),
        "search_audit": dict(search_audit or {}),
        "cost_result": dict(cost_result or {}),
    }
    context = {
        "normative_assessment": dict(normative_assessment or {}),
        "requested_minimum_grade": requested_grade,
        "targets_grau_iii": requested_grade == 3,
        "profile_evidence": dict(spec.get("profile_evidence") or {}),
        "review_events": [dict(item) for item in (review_events or spec.get("review_events") or [])],
        "signature": dict(spec.get("signature") or {}) or None,
        "output_manifest": dict(spec.get("output_manifest") or {}),
        "claim_evidence": dict(spec.get("claim_evidence") or {}),
        # Only the document service supplies a server-read receipt. RequestSpec
        # declarations (including valid=true) cannot establish an external act.
        "institution_acceptance": dict(institution_receipt or {}) or None,
        "software_version": snapshot_draft.get("code_sha"),
        "result_snapshot_id": snapshot_draft.get("job_id"),
        "result_material": material,
        "report_content_fingerprint": spec.get("report_content_fingerprint"),
        "calculation_failed": calc_status != "fitted",
        "cost_result": dict(cost_result or {}),
    }
    block = _try_assess_qualification(context, profile or {})
    if not isinstance(block, Mapping):
        raise QualificationProfileError(
            "C05 assess_qualification is unavailable",
            [_issue("QUALIFICATION_ASSESSOR_UNAVAILABLE", "C05 assess_qualification is unavailable")],
        )
    # C05 is the sole authority for rule, grade and release decisions. C01
    # returns its block intact and only adds schema/version trace metadata.
    result = dict(block)
    result.setdefault("versions", {})
    result["versions"] = {
        **dict(result.get("versions") or {}),
        "qualification_schema": QUALIFICATION_SCHEMA,
        "result_schema": snapshot_draft.get("schema_version"),
        "calculation_version": provenance.get("calculation_version"),
    }
    return result


def reassess_qualification_context(
    *,
    snapshot: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    output_manifest: Mapping[str, Any],
    report_content_fingerprint: str,
    review_events: Optional[Sequence[Mapping[str, Any]]] = None,
    signature: Optional[Mapping[str, Any]] = None,
    normative_assessment: Optional[Mapping[str, Any]] = None,
    institution_receipt: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the document/review pass against an already calculated snapshot.

    The calculation and normative grade are reused verbatim. Document routes
    supply the manifest and report digest produced from the actual artifacts;
    review/signature records then bind to the stable result/report/byte
    identities. This function returns a replacement MP-QUAL/1 block and does
    not persist or mutate the snapshot.
    """
    if not isinstance(output_manifest, Mapping):
        raise QualificationProfileError(
            "output_manifest must be a mapping",
            [_issue("TYPE_ERROR", "output_manifest must be a mapping")],
        )
    if (
        not isinstance(report_content_fingerprint, str)
        or len(report_content_fingerprint) != 64
        or any(ch not in "0123456789abcdefABCDEF" for ch in report_content_fingerprint)
    ):
        raise QualificationProfileError(
            "report_content_fingerprint must be a SHA-256 hex digest",
            [_issue(
                "TYPE_ERROR",
                "report_content_fingerprint must be a 64-character hex digest",
            )],
        )

    provenance = _as_mapping(snapshot.get("provenance"))
    current = _as_mapping(provenance.get("qualification_context"))
    normative = normative_assessment
    if normative is None:
        normative = _as_mapping(provenance.get("normative_assessment"))
    if not normative:
        raise QualificationProfileError(
            "normative_assessment is unavailable for qualification reassessment",
            [_issue(
                "NORMATIVE_ASSESSMENT_MISSING",
                "the persisted normative assessment is required for the second qualification pass",
            )],
        )

    spec = dict(request_spec)
    spec["output_manifest"] = dict(output_manifest)
    spec["report_content_fingerprint"] = report_content_fingerprint.lower()
    spec["review_events"] = [dict(item) for item in (review_events or [])]
    if signature is not None:
        spec["signature"] = dict(signature)
    else:
        spec.pop("signature", None)

    winner = {"status": "fitted"} if current.get("calculation_status") == "ok" else None
    search_audit = _as_mapping(_as_mapping(snapshot.get("search")).get("audit"))
    cost_result = _as_mapping(provenance.get("cost_result"))
    return compose_qualification_context(
        request_spec=spec,
        snapshot_draft=snapshot,
        winner=winner,
        search_audit=search_audit,
        issues=list(snapshot.get("issues") or []),
        review_events=spec["review_events"],
        normative_assessment=normative,
        cost_result=cost_result or None,
        institution_receipt=institution_receipt,
    )
