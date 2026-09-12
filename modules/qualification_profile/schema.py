"""MP-QUAL/1 vocabulary: rule results, case states and qualification profiles.

Additive to MP/1 (RequestSpec/ResultSnapshot) and MP-PRO/1 (workflow_context).
Nothing here renames or replaces those schemas: the qualification block is
emitted under ``provenance.qualification_context``.

Separation of decisions this module must never blur:
  1. qualification of the SOFTWARE and its version
  2. conformity of the specific AVALIAÇÃO
  3. review/signature of the PROFESSIONAL
  4. acceptance by the DESTINATÁRIO (institution)
Tests, a digital signature, an authorship record or the use of a library do
not transfer approval between them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

SCHEMA_VERSION = "MP-QUAL/1"

# --- RuleResult.status -------------------------------------------------------
RULE_PASSED = "passed"
RULE_FAILED = "failed"
RULE_PENDING_MANUAL = "pending_manual"
RULE_NOT_APPLICABLE = "not_applicable"
RULE_UNSUPPORTED = "unsupported"
RULE_UNVERIFIED = "unverified"
RULE_ERROR = "error"

RULE_STATUSES = (
    RULE_PASSED,
    RULE_FAILED,
    RULE_PENDING_MANUAL,
    RULE_NOT_APPLICABLE,
    RULE_UNSUPPORTED,
    RULE_UNVERIFIED,
    RULE_ERROR,
)

#: Statuses that do NOT satisfy a requirement. ``unverified`` is explicitly
#: here: an unverified rule is never a pass.
NON_SATISFYING_STATUSES = (
    RULE_FAILED,
    RULE_PENDING_MANUAL,
    RULE_UNSUPPORTED,
    RULE_UNVERIFIED,
    RULE_ERROR,
)

# --- applicability -----------------------------------------------------------
APPLICABLE = "applicable"
NOT_APPLICABLE_BY_PROFILE = "not_applicable_by_profile"
NOT_APPLICABLE_BY_SOURCE = "not_applicable_by_source"

# --- calculation_status ------------------------------------------------------
CALC_OK = "ok"
CALC_DEGENERATE = "degenerate"
CALC_FAILED = "failed"
CALC_ABSENT = "absent"

# --- grade_requirement_status (preserved from MP/1) --------------------------
GRADE_NOT_REQUESTED = "not_requested"
GRADE_MET = "met"
GRADE_NOT_MET = "not_met"
GRADE_PENDING = "pending"
GRADE_ERROR = "error"

# --- case_release_status -----------------------------------------------------
#: A strictly ordered pipeline. Submission to an institution and its
#: acceptance are NOT states here: they are records of real events.
CASE_ANALYSIS_ONLY = "analysis_only"
CASE_REVIEW_REQUIRED = "review_required"
CASE_READY_FOR_SIGNOFF = "ready_for_professional_signoff"
CASE_SIGNED_INTEGRITY_VERIFIED = "signed_integrity_verified"

CASE_FLOW = (
    CASE_ANALYSIS_ONLY,
    CASE_REVIEW_REQUIRED,
    CASE_READY_FOR_SIGNOFF,
    CASE_SIGNED_INTEGRITY_VERIFIED,
)

# --- the act an institutional source establishes -----------------------------
#: Recording which act a source establishes is what stops an obtained document
#: from being read as a software homologation it does not grant.
ACT_CREDENCIAMENTO_PROFISSIONAL = "credenciamento_profissional"
ACT_CONTRATACAO_DE_EMPRESA = "contratacao_de_empresa"
ACT_VERIFICACAO_DE_LAUDO = "verificacao_de_laudo"
ACT_FORMATO_DE_INTERCAMBIO = "formato_de_intercambio"
ACT_HOMOLOGACAO_DE_SOFTWARE = "homologacao_de_software"
ACT_REGRA_CONTRATUAL_OU_REGULATORIA = "regra_contratual_ou_regulatoria"
ACT_NENHUM = "nenhum_ato_identificado"

INSTITUTIONAL_ACTS = (
    ACT_CREDENCIAMENTO_PROFISSIONAL,
    ACT_CONTRATACAO_DE_EMPRESA,
    ACT_VERIFICACAO_DE_LAUDO,
    ACT_FORMATO_DE_INTERCAMBIO,
    ACT_HOMOLOGACAO_DE_SOFTWARE,
    ACT_REGRA_CONTRATUAL_OU_REGULATORIA,
    ACT_NENHUM,
)

# --- profile verification state ---------------------------------------------
PROFILE_VERIFIED = "verified"
PROFILE_DISCOVERY = "discovery"
PROFILE_PENDING = "pending"
PROFILE_BLOCKED_EXTERNAL = "blocked_external_evidence"
PROFILE_UNKNOWN = "unknown"

PROFILE_STATES = (
    PROFILE_VERIFIED,
    PROFILE_DISCOVERY,
    PROFILE_PENDING,
    PROFILE_BLOCKED_EXTERNAL,
    PROFILE_UNKNOWN,
)

REQUIRED_PROFILE_FIELDS = (
    "id",
    "version",
    "source_set_sha256",
    "purpose",
    "value_basis",
    "method",
    "asset_scope",
)


def make_rule_result(
    *,
    rule_id: str,
    source_id: str,
    edition_or_version: str,
    clause: str,
    status: str,
    applicability: str = APPLICABLE,
    observed: Any = None,
    criterion_ref: Optional[str] = None,
    evidence_refs: Optional[List[Any]] = None,
    explanation: str = "",
    not_applicable_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a RuleResult, refusing the shapes the contract forbids.

    - unknown status -> ValueError (no silent coercion to a pass)
    - not_applicable without a reason tied to the profile/source -> ValueError
    """
    if status not in RULE_STATUSES:
        raise ValueError(f"status de regra desconhecido: {status!r}")
    if status == RULE_NOT_APPLICABLE:
        if applicability not in (NOT_APPLICABLE_BY_PROFILE, NOT_APPLICABLE_BY_SOURCE):
            raise ValueError(
                f"regra {rule_id!r}: not_applicable exige applicability vinculada "
                "ao perfil ou à fonte"
            )
        if not not_applicable_reason:
            raise ValueError(
                f"regra {rule_id!r}: not_applicable exige motivo explícito"
            )
    return {
        "rule_id": rule_id,
        "source_id": source_id,
        "edition_or_version": edition_or_version,
        "clause": clause,
        "applicability": applicability,
        "status": status,
        "observed": observed,
        "criterion_ref": criterion_ref,
        "evidence_refs": list(evidence_refs or []),
        "explanation": explanation,
        "not_applicable_reason": not_applicable_reason,
    }


def satisfies(rule_result: Mapping[str, Any]) -> bool:
    """True only for passed and for a properly justified not_applicable."""
    status = rule_result.get("status")
    if status == RULE_PASSED:
        return True
    if status == RULE_NOT_APPLICABLE:
        return bool(rule_result.get("not_applicable_reason"))
    return False
