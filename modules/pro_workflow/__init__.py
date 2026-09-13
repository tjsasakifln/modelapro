"""P01 producers: reusable residual state, grade aliases, and report contexts."""

from .grade_policy import (
    CANONICAL_GRADE_KEY,
    GRADE_ALIAS_CONFLICT,
    canonical_minimum_grade,
    classify_grade_requirement_status,
    normalize_grade_aliases,
)
from .report_context import (
    aligned_fit_series,
    formula_from_coefficients,
)
from .residual_state import (
    CALCULATION_VERSION,
    RESIDUAL_STATE_SCHEMA,
    XTX_INV_KIND_COVARIANCE,
    XTX_INV_KIND_NORMALIZED,
    apply_mean_prediction_intervals,
    complete_residual_state_for_persist,
    declared_residual_status,
    extract_residual_state,
    json_safe_residual_state,
    residual_state_is_complete,
    subject_x_from_design,
)
from .workflow_context import build_workflow_context

__all__ = [
    "CALCULATION_VERSION",
    "CANONICAL_GRADE_KEY",
    "GRADE_ALIAS_CONFLICT",
    "RESIDUAL_STATE_SCHEMA",
    "XTX_INV_KIND_COVARIANCE",
    "XTX_INV_KIND_NORMALIZED",
    "aligned_fit_series",
    "apply_mean_prediction_intervals",
    "build_workflow_context",
    "canonical_minimum_grade",
    "classify_grade_requirement_status",
    "extract_residual_state",
    "formula_from_coefficients",
    "json_safe_residual_state",
    "normalize_grade_aliases",
    "residual_state_is_complete",
]
