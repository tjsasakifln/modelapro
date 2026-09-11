"""Presentation helpers for the P03 reviewable technical minuta.

Pure mappings used by `build_report_view` / `render_report`. No model fitting
and no second classifier.
"""

from .formula import compose_model_equation
from .search_coverage import interpret_search
from .series import assess_chart_series
from .verifier import verify_report_consistency

__all__ = [
    "assess_chart_series",
    "compose_model_equation",
    "interpret_search",
    "verify_report_consistency",
]
