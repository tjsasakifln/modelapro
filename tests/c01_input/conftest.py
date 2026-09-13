"""Fixtures for C01 ingest tests. All examples are synthetic."""

from __future__ import annotations

from typing import Any, Dict, Optional


def make_request_spec(
    target_col: str = "preco",
    *,
    candidate_cols=None,
    roles: Optional[Dict[str, str]] = None,
    locale: str = "auto",
    delimiter=None,
    encoding=None,
    **extra: Any,
) -> Dict[str, Any]:
    spec = {
        "schema_version": "MP/1",
        "target_col": target_col,
        "candidate_cols": candidate_cols,
        "roles": roles or {},
        "units": {},
        "import_options": {
            "locale": locale,
            "delimiter": delimiter,
            "encoding": encoding,
        },
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {},
        "evaluation_policy": {},
        "reference_date": None,
        "inspection_date": None,
        "target_unit": "",
        "applicant": "synthetic-c01",
        "purpose": "c01-acceptance",
    }
    spec.update(extra)
    return spec
