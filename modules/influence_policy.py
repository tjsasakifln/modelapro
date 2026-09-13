"""C04 sample and influence policy.

Influence statistics (Cook, studentized residuals, leverage) detect
observations to investigate. They are not authorization to drop a valid
row from the principal analysis.

Default mode is report_only: the principal fit keeps every prepared row
that survived pre-fit rules. A documented human exclusion revises the
identified sample (id, reason, author/origin). An automatic exclusion is
allowed only for an objective input-error rule applied before the fit,
with evidence. An exploratory with/without-observation scenario is a
separate result and never replaces the principal evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


MODE_REPORT_ONLY = "report_only"
MODE_REVIEWED_EXCLUSIONS = "reviewed_exclusions"

SCENARIO_PRINCIPAL = "principal"
SCENARIO_EXPLORATORY = "exploratory"

ORIGIN_HUMAN_REVIEW = "human_review"
ORIGIN_PRE_FIT_INPUT_ERROR = "pre_fit_input_error"
ORIGIN_EXPLORATORY = "exploratory"
ORIGIN_TRANSFORM_DOMAIN = "transform_domain"

ALLOWED_MODES = (MODE_REPORT_ONLY, MODE_REVIEWED_EXCLUSIONS)
ALLOWED_SCENARIOS = (SCENARIO_PRINCIPAL, SCENARIO_EXPLORATORY)
ALLOWED_ORIGINS = (
    ORIGIN_HUMAN_REVIEW,
    ORIGIN_PRE_FIT_INPUT_ERROR,
    ORIGIN_EXPLORATORY,
    ORIGIN_TRANSFORM_DOMAIN,
)

COMPARISON_BLOCK_DIVERGENT_SAMPLE = "divergent_sample_prevents_naive_r2_comparison"
COMPARISON_BLOCK_EXPLORATORY = "exploratory_scenario_is_not_principal_evaluation"


def default_outlier_policy() -> Dict[str, Any]:
    return {
        "mode": MODE_REPORT_ONLY,
        "reviewed_exclusions": [],
        "pre_fit_rules": [],
        "scenario": SCENARIO_PRINCIPAL,
    }


def make_issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    affected_ids: Optional[Sequence[Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": "C04",
        "message": message,
        "affected_ids": [ _as_id(x) for x in (affected_ids or []) ],
        "evidence": dict(evidence or {}),
    }


def _as_id(value: Any) -> Any:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return str(value)


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return {
            k: getattr(obj, k)
            for k in dir(obj)
            if not k.startswith("_") and not callable(getattr(obj, k, None))
        }
    return {}


@dataclass
class ExclusionRecord:
    row_id: Any
    reason: str
    origin: str
    author: Optional[str] = None
    rule: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_id": _as_id(self.row_id),
            "reason": self.reason,
            "origin": self.origin,
            "author": self.author,
            "rule": self.rule,
            "evidence": dict(self.evidence or {}),
        }


@dataclass
class SampleDecision:
    used_row_ids: List[Any]
    excluded_row_ids: List[Any]
    exclusions: List[ExclusionRecord]
    scenario: str
    policy_mode: str
    r2_naive_comparison_blocked: bool
    comparison_block_reasons: List[str]
    issues: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "used_row_ids": list(self.used_row_ids),
            "excluded_row_ids": list(self.excluded_row_ids),
            "exclusions": [e.to_dict() for e in self.exclusions],
            "scenario": self.scenario,
            "policy_mode": self.policy_mode,
            "r2_naive_comparison_blocked": self.r2_naive_comparison_blocked,
            "comparison_block_reasons": list(self.comparison_block_reasons),
            "issues": list(self.issues),
        }


def parse_exclusion_record(raw: Any) -> Optional[ExclusionRecord]:
    data = _as_mapping(raw)
    if not data:
        return None
    row_id = data.get("row_id", data.get("id", data.get("index")))
    if row_id is None:
        return None
    reason = data.get("reason") or data.get("motivo") or ""
    origin = data.get("origin") or data.get("origem") or ORIGIN_HUMAN_REVIEW
    if origin not in ALLOWED_ORIGINS:
        origin = ORIGIN_HUMAN_REVIEW
    author = data.get("author") or data.get("autor")
    rule = data.get("rule") or data.get("regra")
    evidence = data.get("evidence") if isinstance(data.get("evidence"), Mapping) else {}
    if not str(reason).strip():
        reason = "exclusão documentada sem motivo textual"
    return ExclusionRecord(
        row_id=_as_id(row_id),
        reason=str(reason),
        origin=str(origin),
        author=None if author is None else str(author),
        rule=None if rule is None else str(rule),
        evidence=dict(evidence),
    )


def parse_outlier_policy(request_spec: Any) -> Dict[str, Any]:
    spec = _as_mapping(request_spec)
    raw = spec.get("outlier_policy")
    policy = default_outlier_policy()
    if raw is None:
        return policy
    data = _as_mapping(raw)
    mode = data.get("mode") or policy["mode"]
    if mode not in ALLOWED_MODES:
        mode = MODE_REPORT_ONLY
    scenario = data.get("scenario") or policy["scenario"]
    if scenario not in ALLOWED_SCENARIOS:
        scenario = SCENARIO_PRINCIPAL
    policy["mode"] = mode
    policy["scenario"] = scenario
    policy["reviewed_exclusions"] = list(data.get("reviewed_exclusions") or [])
    policy["pre_fit_rules"] = list(data.get("pre_fit_rules") or [])
    return policy


def influence_does_not_authorize_exclusion() -> Dict[str, Any]:
    """Serializable invariant: influence is investigation, not removal."""
    return {
        "influence_authorizes_exclusion": False,
        "default_mode": MODE_REPORT_ONLY,
        "principal_keeps_influential_points": True,
        "exploratory_replaces_principal": False,
    }


def _records_from_list(items: Iterable[Any], default_origin: str) -> List[ExclusionRecord]:
    out: List[ExclusionRecord] = []
    for item in items or []:
        rec = parse_exclusion_record(item)
        if rec is None:
            continue
        if rec.origin == ORIGIN_HUMAN_REVIEW and default_origin != ORIGIN_HUMAN_REVIEW:
            rec = ExclusionRecord(
                row_id=rec.row_id,
                reason=rec.reason,
                origin=default_origin,
                author=rec.author,
                rule=rec.rule,
                evidence=rec.evidence,
            )
        out.append(rec)
    return out


def resolve_sample(
    row_ids: Sequence[Any],
    request_spec: Any = None,
    candidate_invalid: Optional[Sequence[Any]] = None,
) -> SampleDecision:
    """Resolve the effective sample for one candidate.

    Never drops a row because it is influential. Candidate-specific
    invalid rows (transform domain, missing design values) are recorded
    as a comparison-blocking divergence, not as a silent per-candidate
    maximisation of fit.
    """
    policy = parse_outlier_policy(request_spec)
    issues: List[Dict[str, Any]] = []
    comparison_reasons: List[str] = []

    normalized_ids = [_as_id(r) for r in row_ids]
    seen = set()
    unique_ids: List[Any] = []
    duplicates: List[Any] = []
    for rid in normalized_ids:
        if rid in seen:
            duplicates.append(rid)
        else:
            seen.add(rid)
            unique_ids.append(rid)

    if duplicates:
        issues.append(
            make_issue(
                "duplicate_row_ids",
                "Identificadores de linha duplicados na amostra preparada.",
                severity="error",
                affected_ids=sorted(set(duplicates), key=str),
                evidence={"count": len(set(duplicates))},
            )
        )

    reviewed = _records_from_list(policy["reviewed_exclusions"], ORIGIN_HUMAN_REVIEW)
    pre_fit = _records_from_list(policy["pre_fit_rules"], ORIGIN_PRE_FIT_INPUT_ERROR)

    for rec in pre_fit:
        if not rec.rule:
            issues.append(
                make_issue(
                    "pre_fit_rule_missing",
                    "Exclusão automática exige regra anterior ao ajuste e evidência.",
                    severity="error",
                    affected_ids=[rec.row_id],
                    evidence=rec.evidence,
                )
            )
        if not rec.evidence:
            issues.append(
                make_issue(
                    "pre_fit_evidence_missing",
                    "Exclusão automática por erro objetivo de entrada sem evidência.",
                    severity="error",
                    affected_ids=[rec.row_id],
                    evidence={"rule": rec.rule},
                )
            )
        rec.origin = ORIGIN_PRE_FIT_INPUT_ERROR

    for rec in reviewed:
        if policy["scenario"] == SCENARIO_EXPLORATORY:
            rec.origin = ORIGIN_EXPLORATORY
        elif rec.origin not in (ORIGIN_HUMAN_REVIEW, ORIGIN_EXPLORATORY):
            rec.origin = ORIGIN_HUMAN_REVIEW
        if rec.origin == ORIGIN_HUMAN_REVIEW and not rec.author:
            issues.append(
                make_issue(
                    "reviewed_exclusion_author_missing",
                    "Exclusão humana/documentada sem autor/origem identificável.",
                    severity="warning",
                    affected_ids=[rec.row_id],
                    evidence={"reason": rec.reason, "origin": rec.origin},
                )
            )

    candidate_recs: List[ExclusionRecord] = []
    for item in candidate_invalid or []:
        rec = parse_exclusion_record(item)
        if rec is None:
            continue
        rec.origin = rec.origin if rec.origin in ALLOWED_ORIGINS else ORIGIN_TRANSFORM_DOMAIN
        candidate_recs.append(rec)

    allowed_policy_origins = {ORIGIN_PRE_FIT_INPUT_ERROR}
    if policy["mode"] == MODE_REVIEWED_EXCLUSIONS or policy["scenario"] == SCENARIO_EXPLORATORY:
        allowed_policy_origins.add(ORIGIN_HUMAN_REVIEW)
        allowed_policy_origins.add(ORIGIN_EXPLORATORY)

    chosen: Dict[Any, ExclusionRecord] = {}

    def _accept(rec: ExclusionRecord, *, policy_level: bool) -> None:
        if rec.row_id not in seen:
            issues.append(
                make_issue(
                    "exclusion_row_not_in_sample",
                    "Exclusão refere ID ausente da amostra preparada.",
                    severity="warning",
                    affected_ids=[rec.row_id],
                    evidence={"origin": rec.origin, "reason": rec.reason},
                )
            )
            return
        if policy_level and rec.origin not in allowed_policy_origins:
            issues.append(
                make_issue(
                    "exclusion_origin_not_authorized",
                    "Origem de exclusão não autorizada pela política da amostra.",
                    severity="error",
                    affected_ids=[rec.row_id],
                    evidence={"origin": rec.origin, "mode": policy["mode"]},
                )
            )
            return
        chosen[rec.row_id] = rec

    for rec in pre_fit:
        _accept(rec, policy_level=True)
    if policy["mode"] == MODE_REVIEWED_EXCLUSIONS or policy["scenario"] == SCENARIO_EXPLORATORY:
        for rec in reviewed:
            _accept(rec, policy_level=True)
    elif reviewed:
        issues.append(
            make_issue(
                "reviewed_exclusions_ignored_in_report_only",
                "Política report_only ignora exclusões revisadas no ajuste principal; "
                "use outlier_policy.mode=reviewed_exclusions para revisar a amostra.",
                severity="warning",
                affected_ids=[r.row_id for r in reviewed],
                evidence={"mode": policy["mode"]},
            )
        )

    for rec in candidate_recs:
        _accept(rec, policy_level=False)
        comparison_reasons.append(COMPARISON_BLOCK_DIVERGENT_SAMPLE)

    if policy["scenario"] == SCENARIO_EXPLORATORY:
        comparison_reasons.append(COMPARISON_BLOCK_EXPLORATORY)
        issues.append(
            make_issue(
                "exploratory_scenario",
                "Cenário exploratório com/sem observação é resultado separado e "
                "não substitui a avaliação principal.",
                severity="info",
                affected_ids=[e.row_id for e in chosen.values()],
                evidence={"scenario": SCENARIO_EXPLORATORY},
            )
        )

    excluded_ids = [_as_id(rid) for rid in unique_ids if rid in chosen]
    used_ids = [_as_id(rid) for rid in unique_ids if rid not in chosen]
    exclusions = [chosen[rid] for rid in excluded_ids]

    if exclusions and policy["scenario"] == SCENARIO_PRINCIPAL:
        issues.append(
            make_issue(
                "sample_revised",
                "Amostra identificada revisada por exclusão documentada ou regra pré-ajuste.",
                severity="info",
                affected_ids=excluded_ids,
                evidence={
                    "used": len(used_ids),
                    "excluded": len(excluded_ids),
                    "records": [e.to_dict() for e in exclusions],
                },
            )
        )

    comparison_reasons = list(dict.fromkeys(comparison_reasons))
    return SampleDecision(
        used_row_ids=used_ids,
        excluded_row_ids=excluded_ids,
        exclusions=exclusions,
        scenario=policy["scenario"],
        policy_mode=policy["mode"],
        r2_naive_comparison_blocked=bool(comparison_reasons),
        comparison_block_reasons=comparison_reasons,
        issues=issues,
    )
