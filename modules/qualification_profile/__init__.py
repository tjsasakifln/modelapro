"""Qualification profiles and the MP-QUAL/1 contract (MP-COM-20260912/C05).

Public surface consumed by other fronts:

    from modules.qualification_profile import assess_qualification
    block = assess_qualification(context, profile)   # -> MP-QUAL/1 dict

C05 owns the catalog and the rules. C01 validates/resolves the profile and
composes the context (it is the producer of provenance.qualification_context).
C02 chooses among known profiles and writes no rules. C03 presents the
qualified result and never recalculates a grade.
"""

from .assessment import assess_qualification, result_fingerprint
from .catalog import (
    ProfileError,
    known_profile_ids,
    load_catalog,
    resolve_profile,
    source_set_sha256,
)
from .output_conformance import (
    BASELINE_STATES,
    NON_CONFORMING_BASELINE,
    OUTPUT_KINDS,
    OutputRequirementError,
    assess_output_conformance,
    product_conformance_baseline,
)
from .claims import (
    CLAIM_CALCULATION_VERIFIED,
    CLAIM_IMPLEMENTS_REQUIREMENTS,
    CLAIM_INSTITUTION_ACCEPTED,
    CLAIM_KINDS,
    CLAIM_PROFILE_COMPATIBLE,
    CLAIMS_REGISTRY_VERSION,
    ClaimNotPermitted,
    assert_claim,
    evaluate_claim,
    reuse_acceptance_check,
)
from .schema import (
    CASE_ANALYSIS_ONLY,
    CASE_FLOW,
    CASE_READY_FOR_SIGNOFF,
    CASE_REVIEW_REQUIRED,
    CASE_SIGNED_INTEGRITY_VERIFIED,
    INSTITUTIONAL_ACTS,
    NON_SATISFYING_STATUSES,
    PROFILE_STATES,
    RULE_STATUSES,
    SCHEMA_VERSION,
    make_rule_result,
    satisfies,
)

__all__ = [
    "SCHEMA_VERSION",
    "assess_output_conformance",
    "product_conformance_baseline",
    "OutputRequirementError",
    "OUTPUT_KINDS",
    "BASELINE_STATES",
    "NON_CONFORMING_BASELINE",
    "assess_qualification",
    "result_fingerprint",
    "load_catalog",
    "known_profile_ids",
    "resolve_profile",
    "source_set_sha256",
    "ProfileError",
    "make_rule_result",
    "satisfies",
    "RULE_STATUSES",
    "NON_SATISFYING_STATUSES",
    "PROFILE_STATES",
    "INSTITUTIONAL_ACTS",
    "CASE_FLOW",
    "CASE_ANALYSIS_ONLY",
    "CASE_REVIEW_REQUIRED",
    "CASE_READY_FOR_SIGNOFF",
    "CASE_SIGNED_INTEGRITY_VERIFIED",
    "evaluate_claim",
    "assert_claim",
    "reuse_acceptance_check",
    "ClaimNotPermitted",
    "CLAIM_KINDS",
    "CLAIM_CALCULATION_VERIFIED",
    "CLAIM_IMPLEMENTS_REQUIREMENTS",
    "CLAIM_PROFILE_COMPATIBLE",
    "CLAIM_INSTITUTION_ACCEPTED",
    "CLAIMS_REGISTRY_VERSION",
]
