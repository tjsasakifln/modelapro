"""Declared search objective must be the ranking metric actually used."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

OBJECTIVE_ALIASES = {
    "aic": "aic",
    "bic": "bic",
    "rmse": "original_rmse",
    "original_rmse": "original_rmse",
    "original_scale_error": "original_rmse",
}

OBJECTIVE_NAMES = {
    "aic": "aic",
    "bic": "bic",
    "original_rmse": "original_scale_error",
}


def declared_objective(search_policy: Mapping[str, Any]) -> Tuple[str, str]:
    """Return (canonical_metric_key, public_name)."""
    raw = search_policy.get("objective") if isinstance(search_policy, Mapping) else None
    if raw is None or raw == "":
        return "original_rmse", "original_scale_error"
    key = OBJECTIVE_ALIASES.get(str(raw).strip().lower())
    if key is None:
        # Unknown name is not silently rewritten to RMSE.
        return str(raw).strip().lower(), str(raw).strip()
    return key, OBJECTIVE_NAMES[key]


def objective_metric_key(search_policy: Mapping[str, Any]) -> str:
    return declared_objective(search_policy)[0]


def ranking_primary_score(metrics: Mapping[str, Any], metric_key: str) -> float:
    """Higher is better. Missing required metric is worst."""
    value = metrics.get(metric_key) if isinstance(metrics, Mapping) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    if metric_key in {"aic", "bic", "original_rmse"}:
        return -number
    return number


def objective_descriptor(
    search_policy: Mapping[str, Any], evaluation_policy: Mapping[str, Any]
) -> Dict[str, Any]:
    metric, name = declared_objective(search_policy)
    required = list(search_policy.get("required_criteria") or [metric])
    if metric not in required:
        required = [metric] + [c for c in required if c != metric]
    if evaluation_policy.get("require_precision") and "precision_amplitude_pct" not in required:
        required.append("precision_amplitude_pct")
    return {
        "name": name,
        "metric": metric,
        "scale": "original" if metric == "original_rmse" else "transformed_ok",
        "required_criteria": required,
        "optional_criteria": ["precision_amplitude_pct", "stability", "complexity"],
        "tie_break": "candidate_id_lexicographic_asc",
        "does_not_use": [
            "r2_across_transformed_vs_original_scales",
            "automatic_sample_row_removal",
        ],
        "budget_is_not_global_optimum": True,
    }
