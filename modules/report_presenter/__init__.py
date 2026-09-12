"""Presentation helpers for the P03 reviewable technical minuta.

Pure mappings used by `build_report_view` / `render_report`. No model fitting
and no second classifier.
"""

from .formula import compose_model_equation
from .qualification import (
    assess_document_state,
    report_content_fingerprint,
    signable_snapshot_sha256,
)
from .search_coverage import interpret_search
from .series import assess_chart_series
from .verifier import verify_report_consistency

__all__ = [
    "assess_chart_series",
    "assess_document_state",
    "compose_model_equation",
    "interpret_search",
    "report_content_fingerprint",
    "signable_snapshot_sha256",
    "verify_report_consistency",
]
