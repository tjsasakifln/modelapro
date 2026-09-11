"""Aligned fit series and a derivable model formula for report_context / model.formula."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def formula_from_coefficients(
    coefficients: Mapping[str, Any],
    feature_order: Optional[Sequence[str]] = None,
    *,
    target_name: str = "y",
    intercept_column: Optional[str] = "const",
) -> Optional[str]:
    """Display formula from stored coefficients. Not a substitute for integral coefficients."""
    if not isinstance(coefficients, Mapping) or not coefficients:
        return None
    order = [str(x) for x in (feature_order or list(coefficients.keys()))]
    if not order:
        order = [str(k) for k in coefficients.keys()]
    intercept_names = {intercept_column or "const", "const", "Intercept"}
    intercept_term = None
    terms: List[str] = []
    for name in order:
        value = _finite(coefficients.get(name))
        if value is None:
            continue
        if name in intercept_names:
            intercept_term = format(value, ".17g")
            continue
        sign = "+" if value >= 0 else "-"
        terms.append(f"{sign} {format(abs(value), '.17g')}*{name}")
    if intercept_term is None and not terms:
        return None
    body = intercept_term if intercept_term is not None else "0"
    if terms:
        body = body + " " + " ".join(terms)
    return f"{target_name} = {body}"


def aligned_fit_series(
    winner_fit: Any,
    *,
    used_row_ids: Sequence[str],
    target_unit: Optional[str] = None,
    y_transform_name: Optional[str] = None,
) -> Dict[str, Any]:
    """fitted/residual/observed series aligned to used_row_ids only.

    Residuals stay on the modeled scale. Log residuals are never labeled as
    monetary prices. Missing design yields an unavailable series, not invented
    values.
    """
    used = [str(x) for x in list(used_row_ids or [])]
    identity = y_transform_name in {None, "", "identity", "linear", "none"}
    scale = "original" if identity else "transformed"
    unit = target_unit if identity else f"transformed({y_transform_name or 'y'})"
    unavailable = {
        "fitted_values": None,
        "residuals": None,
        "observed_values": None,
        "series_row_ids": list(used),
        "series_scale": scale,
        "series_unit": unit,
        "available": False,
        "reason": "fit_design_unavailable",
    }

    x_design = getattr(winner_fit, "X_design", None)
    if x_design is None and isinstance(winner_fit, Mapping):
        x_design = winner_fit.get("X_design")
    y_design = getattr(winner_fit, "y_design", None)
    if y_design is None and isinstance(winner_fit, Mapping):
        y_design = winner_fit.get("y_design")
    model = getattr(winner_fit, "model_object", None)
    if model is None and isinstance(winner_fit, Mapping):
        model = winner_fit.get("model_object")

    fitted = None
    observed = None
    if model is not None:
        fitted = getattr(model, "fittedvalues", None)
        observed = getattr(model, "model", None)
        if observed is not None:
            observed = getattr(observed, "endog", None)
    if observed is None:
        observed = y_design
    if fitted is None and x_design is not None:
        coefficients = None
        if isinstance(winner_fit, Mapping):
            coefficients = winner_fit.get("coefficients")
        else:
            coefficients = getattr(winner_fit, "coefficients", None)
        if isinstance(coefficients, Mapping) and hasattr(x_design, "columns"):
            try:
                import numpy as np

                order = [str(c) for c in x_design.columns]
                beta = np.array([float(coefficients.get(name, 0.0)) for name in order], dtype=float)
                X = np.asarray(x_design.to_numpy(), dtype=float)
                if X.shape[1] == beta.shape[0] and np.isfinite(X).all() and np.isfinite(beta).all():
                    fitted = X @ beta
            except Exception:
                fitted = None

    if fitted is None or observed is None:
        return unavailable

    try:
        import numpy as np

        fit_arr = np.asarray(fitted, dtype=float).reshape(-1)
        obs_arr = np.asarray(observed, dtype=float).reshape(-1)
    except Exception:
        return unavailable
    if fit_arr.size != obs_arr.size or fit_arr.size == 0:
        return unavailable
    if used and fit_arr.size != len(used):
        # Do not silently align to a different sample; series must be used_row_ids.
        return {
            **unavailable,
            "reason": "series_length_mismatch_used_row_ids",
        }
    if not bool(__import__("numpy").isfinite(fit_arr).all()) or not bool(
        __import__("numpy").isfinite(obs_arr).all()
    ):
        return {**unavailable, "reason": "non_finite_series"}
    resid = obs_arr - fit_arr
    return {
        "fitted_values": [float(v) for v in fit_arr.tolist()],
        "residuals": [float(v) for v in resid.tolist()],
        "observed_values": [float(v) for v in obs_arr.tolist()],
        "series_row_ids": list(used) if used else [str(i) for i in range(fit_arr.size)],
        "series_scale": scale,
        "series_unit": unit or ("original" if identity else scale),
        "available": True,
        "reason": None,
    }
