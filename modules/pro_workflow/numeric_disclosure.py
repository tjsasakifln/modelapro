"""Finite, auditable numeric disclosures for a fitted MP/1 candidate.

This module reads the frozen fit and its effective sample.  It does not refit,
change the selected candidate, exclude observations, or classify a normative
grade.  Every public value is JSON-safe; unavailable calculations remain
explicitly unavailable instead of becoming zero, infinity, or a pass.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


NORMAL_INTERVALS: Tuple[Tuple[float, float], ...] = (
    (1.0, 68.0),
    (1.64, 90.0),
    (1.96, 95.0),
)
ELASTICITY_RELATIVE_STEP = 1e-4


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _mapping(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        return dict(value) if isinstance(value, Mapping) else {}
    if is_dataclass(obj):
        value = asdict(obj)
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, (bool, np.bool_)) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _finite(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Series, pd.Index)):
        return [_json_safe(item) for item in list(value)]
    mapped = _mapping(value)
    return _json_safe(mapped) if mapped else str(value)


def _numeric_array(value: Any) -> Optional[np.ndarray]:
    if value is None:
        return None
    try:
        array = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(array).all():
        return None
    return array


def _numeric_matrix(value: Any) -> Optional[np.ndarray]:
    if value is None:
        return None
    try:
        matrix = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return None
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        return None
    return matrix


def _pearson(x: Optional[np.ndarray], y: Optional[np.ndarray]) -> Optional[float]:
    if x is None or y is None or len(x) != len(y) or len(x) < 2:
        return None
    x_centered = x - float(np.mean(x))
    y_centered = y - float(np.mean(y))
    denominator = math.sqrt(float(x_centered @ x_centered) * float(y_centered @ y_centered))
    if denominator == 0.0 or not math.isfinite(denominator):
        return None
    value = float(x_centered @ y_centered) / denominator
    if not math.isfinite(value) or value < -1.0 or value > 1.0:
        return None
    return value


def _model_series(winner_fit: Any) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    model = _get(winner_fit, "model_object")
    residuals = _numeric_array(_get(model, "resid"))
    fitted = _numeric_array(_get(model, "fittedvalues"))
    observed = _numeric_array(_get(model, "model"))
    if model is not None:
        observed = _numeric_array(_get(_get(model, "model"), "endog"))
    if observed is None:
        observed = _numeric_array(_get(winner_fit, "y_design"))
    if residuals is None and observed is not None and fitted is not None and len(observed) == len(fitted):
        residuals = observed - fitted
    return observed, fitted, residuals


def _durbin_watson(residuals: Optional[np.ndarray]) -> Optional[float]:
    if residuals is None or len(residuals) < 2:
        return None
    denominator = float(residuals @ residuals)
    if denominator == 0.0 or not math.isfinite(denominator):
        return None
    differences = np.diff(residuals)
    value = float(differences @ differences) / denominator
    return value if math.isfinite(value) else None


def _numerically_exact_fit(
    winner_fit: Any,
    observed: Optional[np.ndarray],
    residuals: Optional[np.ndarray],
) -> bool:
    """Recognize residuals within the floating-point dot-product error bound.

    This is not a fitted tolerance.  ``gamma_p = p*eps/(1-p*eps)`` is the
    standard forward-error bound for a length-p floating-point dot product.
    """
    model = _get(winner_fit, "model_object")
    exog = _numeric_matrix(_get(_get(model, "model"), "exog"))
    params = _numeric_array(_get(model, "params"))
    if (
        observed is None
        or residuals is None
        or exog is None
        or params is None
        or len(observed) != len(residuals)
        or exog.shape != (len(observed), len(params))
    ):
        return False
    eps = np.finfo(float).eps
    p = int(exog.shape[1])
    if p <= 0 or p * eps >= 1.0:
        return False
    gamma_p = p * eps / (1.0 - p * eps)
    predicted_magnitude = np.abs(exog) @ np.abs(params)
    bound = gamma_p * predicted_magnitude + eps * np.abs(observed)
    return bool(np.all(np.abs(residuals) <= bound))


def _pvalues(winner_fit: Any) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    records = _get(winner_fit, "coefficient_records") or []
    if isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
        for record in records:
            if isinstance(record, Mapping) and record.get("name") is not None:
                out[str(record["name"])] = _finite(record.get("pvalue"))
    if out:
        return out
    diagnostics = _mapping(_get(winner_fit, "diagnostics"))
    raw = diagnostics.get("pvalues")
    if isinstance(raw, Mapping):
        return {str(key): _finite(value) for key, value in raw.items()}
    model = _get(winner_fit, "model_object")
    raw_model = _get(model, "pvalues")
    if raw_model is not None:
        names = list(getattr(raw_model, "index", range(len(raw_model))))
        return {
            str(name): _finite(
                raw_model.iloc[i] if hasattr(raw_model, "iloc") else raw_model[i]
            )
            for i, name in enumerate(names)
        }
    return out


def _vif(winner_fit: Any) -> Dict[str, Optional[float]]:
    design = _get(winner_fit, "X_design")
    if design is None:
        return {}
    try:
        frame = pd.DataFrame(design).copy()
        values = frame.to_numpy(dtype=float)
    except (TypeError, ValueError):
        return {}
    if values.ndim != 2 or values.shape[0] < 2 or not np.isfinite(values).all():
        return {str(column): None for column in frame.columns}
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
    except ImportError:
        return {str(column): None for column in frame.columns}
    out: Dict[str, Optional[float]] = {}
    for position, column in enumerate(frame.columns):
        try:
            with np.errstate(divide="ignore", invalid="ignore"):
                value = variance_inflation_factor(values, position)
        except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
            value = None
        out[str(column)] = _finite(value)
    return out


def _standardized_residuals(
    winner_fit: Any,
    residuals: Optional[np.ndarray],
    *,
    numerically_exact_fit: bool = False,
) -> Dict[str, Any]:
    used_ids = [str(value) for value in list(_get(winner_fit, "used_row_ids") or [])]
    diagnostics = _mapping(_get(winner_fit, "diagnostics"))
    df_resid = _finite(diagnostics.get("df_resid"))
    result: Dict[str, Any] = {
        "definition": (
            "raw residual / residual standard error sqrt(SSE/df_resid); "
            "not internally or externally studentized"
        ),
        "is_studentized": False,
        "scale": "design_target",
        "used_row_ids": used_ids,
        "values": [],
        "n": 0,
        "sigma": None,
        "available": False,
        "reason": None,
    }
    if residuals is None or not used_ids or len(residuals) != len(used_ids):
        result["reason"] = "residuals_unavailable_or_not_aligned_to_used_row_ids"
        return result
    if df_resid is None or df_resid <= 0.0:
        result["reason"] = "non_positive_or_missing_df_resid"
        return result
    sse = float(residuals @ residuals)
    sigma = math.sqrt(sse / df_resid) if sse >= 0.0 else float("nan")
    if numerically_exact_fit:
        result["sigma"] = sigma if math.isfinite(sigma) else None
        result["reason"] = "numerically_exact_fit_residual_scale_not_informative"
        return result
    if not math.isfinite(sigma) or sigma == 0.0:
        result["reason"] = "zero_or_non_finite_residual_standard_error"
        return result
    values = residuals / sigma
    if not np.isfinite(values).all():
        result["reason"] = "non_finite_standardized_residual"
        return result
    result.update(
        {
            "values": [float(value) for value in values],
            "n": int(len(values)),
            "sigma": sigma,
            "available": True,
        }
    )
    return result


def _normal_frequency_comparison(standardized: Mapping[str, Any]) -> Dict[str, Any]:
    values = _numeric_array(standardized.get("values"))
    available = bool(standardized.get("available")) and values is not None and len(values) > 0
    n = int(len(values)) if available else 0
    intervals: List[Dict[str, Any]] = []
    for z, nominal_percent in NORMAL_INTERVALS:
        exact_probability = math.erf(z / math.sqrt(2.0))
        observed_count = int(np.count_nonzero(np.abs(values) <= z)) if available else 0
        intervals.append(
            {
                "z": z,
                "nominal_probability": exact_probability,
                "nominal_percent": nominal_percent,
                "observed_count": observed_count,
                "observed_probability": observed_count / n if available else None,
            }
        )
    return {
        "definition": "P(-z <= Z <= z) compared with the effective-sample frequency",
        "intervals": intervals,
        "n": n,
        "available": available,
        "reason": None if available else standardized.get("reason") or "standardized_residuals_unavailable",
    }


def _correlation_values(frame: pd.DataFrame) -> List[List[Optional[float]]]:
    arrays = [frame[column].to_numpy(dtype=float) for column in frame.columns]
    return [[_pearson(left, right) for right in arrays] for left in arrays]


def _matrix_block(frame: pd.DataFrame, *, scale: str) -> Dict[str, Any]:
    variables = [str(column) for column in frame.columns]
    values = _correlation_values(frame) if variables and len(frame) >= 2 else []
    missing_cells = [
        {"row": variables[i], "column": variables[j]}
        for i in range(len(values))
        for j in range(len(values))
        if values[i][j] is None
    ]
    complete = len(variables) >= 2 and bool(values) and not missing_cells
    return {
        "sample": "effective_model_sample",
        "scale": scale,
        "variables": variables,
        "values": values,
        "n": int(len(frame)),
        "available": complete,
        "status": "complete" if complete else "partial" if values else "unavailable",
        "missing_cells": missing_cells,
        "reason": (
            None
            if complete
            else "matrix_contains_undefined_correlations"
            if missing_cells
            else "fewer_than_two_numeric_variables_or_insufficient_rows"
        ),
    }


def _original_target(prepared: Any, used_ids: Sequence[Any]) -> Optional[np.ndarray]:
    y = _numeric_array(_get(prepared, "y"))
    prepared_ids = list(_get(prepared, "row_ids") or [])
    if y is None or len(y) != len(prepared_ids):
        return None
    positions = {str(row_id): position for position, row_id in enumerate(prepared_ids)}
    if (len(positions) != len(prepared_ids)
            or len(set(map(str, used_ids))) != len(used_ids)
            or any(str(row_id) not in positions for row_id in used_ids)):
        return None
    out = np.asarray([y[positions[str(row_id)]] for row_id in used_ids], dtype=float)
    return out if np.isfinite(out).all() else None


def _base_kinds(winner_fit: Any) -> Dict[str, str]:
    state = _mapping(_get(winner_fit, "encoder_state"))
    kinds: Dict[str, str] = {}
    for item in state.get("base_variables") or []:
        if isinstance(item, Mapping) and item.get("original_name") is not None:
            kinds[str(item["original_name"])] = str(item.get("kind") or "")
    return kinds


def _correlation_matrix(winner_fit: Any, prepared: Any) -> Dict[str, Any]:
    used_ids = list(_get(winner_fit, "used_row_ids") or [])
    target = _original_target(prepared, used_ids)
    target_name = str(getattr(_get(prepared, "y"), "name", None) or "target")
    base = _get(winner_fit, "base_frame")
    base_frame = pd.DataFrame(base).copy() if base is not None else pd.DataFrame()
    base_frame.index = base_frame.index.map(str)
    ordered_ids = list(map(str, used_ids))
    rows_match = bool(
        ordered_ids and len(set(ordered_ids)) == len(ordered_ids)
        and base_frame.index.is_unique
        and set(base_frame.index) == set(ordered_ids)
        and target is not None
    )
    if rows_match:
        base_frame = base_frame.loc[ordered_ids].reset_index(drop=True)
    spec = _mapping(_get(winner_fit, "candidate_spec"))
    base_variables = list(spec.get("base_variables") or spec.get("features") or [])
    kinds = _base_kinds(winner_fit)
    excluded: List[Dict[str, str]] = []
    original = pd.DataFrame()
    if rows_match:
        original[target_name] = target
        for variable in base_variables:
            name = str(variable)
            kind = kinds.get(name)
            if kind and kind != "numeric":
                excluded.append({"variable": name, "reason": f"non_numeric_{kind}"})
                continue
            if name not in base_frame.columns:
                excluded.append({"variable": name, "reason": "missing_from_effective_base_frame"})
                continue
            numeric = pd.to_numeric(base_frame[name], errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(numeric).all():
                excluded.append({"variable": name, "reason": "non_finite_or_non_numeric_original_values"})
                continue
            original[name] = numeric
    block = _matrix_block(original, scale="original")
    block["used_row_ids"] = ordered_ids
    if not rows_match:
        block["reason"] = "effective_sample_row_identity_mismatch"
    block["excluded_variables"] = excluded
    missing_numeric = [
        item
        for item in excluded
        if not str(item.get("reason") or "").startswith("non_numeric_")
    ]
    block["missing_variables"] = missing_numeric
    if missing_numeric:
        block["available"] = False
        block["status"] = "partial" if block.get("values") else "unavailable"
        block["reason"] = "numeric_variables_missing_from_original_scale_matrix"

    design = _get(winner_fit, "X_design")
    y_design = _numeric_array(_get(winner_fit, "y_design"))
    diagnostics = _mapping(_get(winner_fit, "diagnostics"))
    if design is not None and y_design is not None:
        design_frame = pd.DataFrame(design).reset_index(drop=True)
        intercept_column = diagnostics.get("intercept_column")
        if intercept_column in design_frame.columns:
            design_frame = design_frame.drop(columns=[intercept_column])
        if len(design_frame) == len(y_design):
            target_design_name = target_name
            design_frame.insert(0, target_design_name, y_design)
            x_transforms = spec.get("x_transformations") or {}
            y_transform = spec.get("y_transformation")
            materially_different = bool(
                x_transforms
                or y_transform not in (None, "", "identity", "linear", "none")
                or [str(column) for column in design_frame.columns[1:]]
                != [str(column) for column in original.columns[1:]]
            )
            if materially_different:
                design_block = _matrix_block(design_frame, scale="design")
                design_block["target_transformation"] = y_transform or "identity"
                design_block["predictor_transformations"] = _json_safe(x_transforms)
                block["design"] = design_block
    return block


def _prediction_point(predict_original: Callable[[Any], Any], raw: Mapping[str, Any]) -> Optional[float]:
    try:
        result = predict_original(dict(raw))
    except Exception:
        return None
    if isinstance(result, Mapping):
        return _finite(result.get("point"))
    return _finite(result)


def _elasticities(
    winner_fit: Any,
    subject_raw: Optional[Mapping[str, Any]],
    predict_original: Optional[Callable[[Any], Any]],
) -> Dict[str, Any]:
    raw = dict(subject_raw or {})
    result: Dict[str, Any] = {
        "method": "central_finite_difference_predict_original",
        "point": "subject",
        "relative_step": ELASTICITY_RELATIVE_STEP,
        "derivative_error": (
            "truncation abs(D(h/2)-D(h))/3 plus floating-point subtraction/division roundoff bound"
        ),
        "items": [],
        "warnings": [],
        "available": False,
        "status": "unavailable",
        "coverage": {
            "expected_quantitative_variables": [],
            "computed_variables": [],
            "missing_variables": [],
            "complete": False,
        },
        "not_applicable_variables": [],
    }
    spec = _mapping(_get(winner_fit, "candidate_spec"))
    variables = list(spec.get("base_variables") or spec.get("features") or [])
    kinds = _base_kinds(winner_fit)
    expected: List[str] = []
    for variable in variables:
        name = str(variable)
        kind = kinds.get(name)
        if kind and kind != "numeric":
            result["not_applicable_variables"].append(
                {
                    "variable": name,
                    "reason": f"{kind}_requires_discrete_effect_not_elasticity",
                }
            )
            result["warnings"].append(f"categorical_variable:{name}:discrete_effect_not_elasticity")
        else:
            expected.append(name)
    result["coverage"]["expected_quantitative_variables"] = list(expected)
    if not expected:
        result["status"] = "not_applicable"
        result["warnings"].append("no_quantitative_variables_for_elasticity")
        return result
    if not callable(predict_original):
        result["warnings"].append("predict_original_unavailable")
        result["coverage"]["missing_variables"] = list(expected)
        return result
    base_prediction = _prediction_point(predict_original, raw)
    if base_prediction is None:
        result["warnings"].append("base_prediction_non_finite")
        result["coverage"]["missing_variables"] = list(expected)
        return result
    if base_prediction == 0.0:
        result["warnings"].append("zero_base_prediction:elasticity_not_defined")
        result["coverage"]["missing_variables"] = list(expected)
        return result

    for name in expected:
        value = _finite(raw.get(name))
        if value is None:
            result["warnings"].append(f"non_finite_or_missing_base_value:{name}")
            continue
        if value == 0.0:
            result["warnings"].append(f"zero_base_value:{name}:relative_elasticity_not_defined")
            continue
        h = abs(value) * ELASTICITY_RELATIVE_STEP
        half_h = h / 2.0
        if (
            not math.isfinite(h)
            or h <= 0.0
            or half_h <= 0.0
            or value + h == value
            or value - h == value
            or value + half_h == value
            or value - half_h == value
        ):
            result["warnings"].append(f"finite_difference_step_not_representable:{name}")
            continue

        def central(step: float) -> Optional[Tuple[float, float]]:
            lower = dict(raw)
            upper = dict(raw)
            lower[name] = value - step
            upper[name] = value + step
            y_lower = _prediction_point(predict_original, lower)
            y_upper = _prediction_point(predict_original, upper)
            if y_lower is None or y_upper is None:
                return None
            difference = y_upper - y_lower
            numerator_roundoff = np.finfo(float).eps * (abs(y_upper) + abs(y_lower))
            if abs(difference) <= numerator_roundoff:
                return None
            derivative = difference / (2.0 * step)
            roundoff_error = (
                numerator_roundoff / (2.0 * step)
                + np.finfo(float).eps * abs(derivative)
            )
            if not (math.isfinite(derivative) and math.isfinite(roundoff_error)):
                return None
            return derivative, roundoff_error

        estimate_h = central(h)
        estimate_half = central(half_h)
        if estimate_h is None or estimate_half is None:
            result["warnings"].append(f"finite_difference_resolution_insufficient:{name}")
            continue
        derivative_h, roundoff_h = estimate_h
        derivative_half, roundoff_half = estimate_half
        truncation_error = abs(derivative_half - derivative_h) / 3.0
        roundoff_error = roundoff_half + (roundoff_half + roundoff_h) / 3.0
        derivative_error = truncation_error + roundoff_error
        elasticity = derivative_half * value / base_prediction
        if not (math.isfinite(elasticity) and math.isfinite(derivative_error)):
            result["warnings"].append(f"non_finite_elasticity:{name}")
            continue
        result["items"].append(
            {
                "variable": name,
                "elasticity": elasticity,
                "base_value": value,
                "base_prediction": base_prediction,
                "step": half_h,
                "derivative": derivative_half,
                "derivative_error": derivative_error,
                "derivative_truncation_error": truncation_error,
                "derivative_roundoff_error": roundoff_error,
            }
        )
    computed = [str(item["variable"]) for item in result["items"]]
    missing = [name for name in expected if name not in set(computed)]
    complete = bool(expected) and not missing
    result["coverage"].update(
        {
            "computed_variables": computed,
            "missing_variables": missing,
            "complete": complete,
        }
    )
    result["available"] = complete
    result["status"] = "complete" if complete else "partial" if computed else "unavailable"
    return result


def _outlier_count(winner_fit: Any, *, numerically_exact_fit: bool = False) -> Dict[str, Any]:
    diagnostics = _mapping(_get(winner_fit, "diagnostics"))
    influence = _mapping(diagnostics.get("influence"))
    studentized = _mapping(influence.get("studentized_residuals"))
    thresholds = _mapping(influence.get("thresholds"))
    cutoff = _finite(thresholds.get("studentized_abs"))
    detected_ids = [
        str(row_id)
        for row_id, value in studentized.items()
        if cutoff is not None and _finite(value) is not None and abs(float(value)) > cutoff
    ]
    influential_ids = [str(row_id) for row_id in list(influence.get("influential_row_ids") or [])]
    excluded_ids = [str(row_id) for row_id in list(_get(winner_fit, "excluded_row_ids") or [])]
    used_ids = [str(row_id) for row_id in list(_get(winner_fit, "used_row_ids") or [])]
    finite_studentized_ids = {
        str(row_id)
        for row_id, value in studentized.items()
        if _finite(value) is not None
    }
    missing_studentized_ids = sorted(set(used_ids) - finite_studentized_ids)
    expected = set(used_ids)
    maps = {
        name: _mapping(influence.get(name))
        for name in ("studentized_residuals", "cooks_distance", "leverage")
    }
    map_coverage = {}
    for name, values in maps.items():
        finite_ids = {str(key) for key, value in values.items() if _finite(value) is not None}
        keys = {str(key) for key in values}
        map_coverage[name] = {
            "missing_row_ids": sorted(expected - finite_ids),
            "unexpected_row_ids": sorted(keys - expected),
            "complete": bool(expected) and finite_ids == keys == expected and len(keys) == len(values),
        }
    threshold_names = ("studentized_abs", "cooks_4_over_n", "cooks_absolute", "leverage_2p_over_n")
    checked_thresholds = {name: _finite(thresholds.get(name)) for name in threshold_names}
    thresholds_valid = all(value is not None and value > 0 for value in checked_thresholds.values())
    maps_complete = all(item["complete"] for item in map_coverage.values())
    maps = {name: {str(key): value for key, value in values.items()} for name, values in maps.items()}
    derived_union = set()
    if maps_complete and thresholds_valid:
        for row_id in expected:
            if (abs(float(maps["studentized_residuals"][row_id])) > cutoff
                    or float(maps["cooks_distance"][row_id]) > checked_thresholds["cooks_4_over_n"]
                    or float(maps["cooks_distance"][row_id]) > checked_thresholds["cooks_absolute"]
                    or float(maps["leverage"][row_id]) > checked_thresholds["leverage_2p_over_n"]):
                derived_union.add(row_id)
    union_valid = bool(
        maps_complete and thresholds_valid
        and isinstance(influence.get("influential_row_ids"), (list, tuple))
        and len(set(influential_ids)) == len(influential_ids)
        and set(influential_ids) <= expected
        and set(influential_ids) == derived_union
    )
    complete = bool(
        maps_complete and thresholds_valid and union_valid
        and len(expected) == len(used_ids) and not expected.intersection(excluded_ids)
    )
    available = bool(
        complete and not numerically_exact_fit
    )
    return {
        "detected": len(set(detected_ids)) if available else None,
        "excluded": len(set(excluded_ids)),
        "influential": len(set(influential_ids)) if available else None,
        "definition": {
            "detected": (
                f"used observations with abs(internally studentized residual) > {cutoff}"
                if cutoff is not None
                else "not computable: internally studentized residual cutoff unavailable"
            ),
            "excluded": (
                "observations absent from the effective fit under declared/pre-fit sample policy; "
                "they are not inferred to be outliers"
            ),
            "influential": (
                "used observations flagged by the fit influence union (Cook distance, "
                "internally studentized residual, or leverage)"
            ),
        },
        "detected_row_ids": sorted(set(detected_ids)) if available else [],
        "excluded_row_ids": sorted(set(excluded_ids)),
        "influential_row_ids": sorted(set(influential_ids)) if available else [],
        "influence_authorizes_exclusion": False,
        "available": available,
        "coverage": {
            "expected_used_rows": len(set(used_ids)),
            "finite_studentized_rows": len(finite_studentized_ids & set(used_ids)),
            "missing_row_ids": missing_studentized_ids,
            "maps": map_coverage,
            "thresholds_valid": thresholds_valid,
            "influence_union_valid": union_valid,
            "complete": complete,
        },
        "reason": (
            None
            if available
            else "numerically_exact_fit_influence_not_informative"
            if numerically_exact_fit
            else "influence_maps_thresholds_or_union_not_verified"
        ),
    }


def build_numeric_disclosure(
    winner_fit: Any,
    prepared_dataset: Any,
    *,
    subject_raw: Optional[Mapping[str, Any]] = None,
    predict_original: Optional[Callable[[Any], Any]] = None,
) -> Dict[str, Any]:
    """Build snapshot-ready fields from the selected, already-fitted model."""
    diagnostics = _mapping(_get(winner_fit, "diagnostics"))
    observed, fitted, residuals = _model_series(winner_fit)
    r_value = _pearson(observed, fitted)
    vif = _vif(winner_fit)
    exact_fit = _numerically_exact_fit(winner_fit, observed, residuals)
    metrics = {
        "r": r_value,
        "r2": _finite(diagnostics.get("r2")),
        "r2_adjusted": _finite(diagnostics.get("r2_adjusted")),
        "f_statistic": _finite(diagnostics.get("f_statistic")),
        "f_pvalue": _finite(diagnostics.get("f_pvalue")),
        "durbin_watson": None if exact_fit else _durbin_watson(residuals),
    }
    has_intercept = diagnostics.get("has_intercept") is True
    r2 = metrics["r2"]
    if (
        has_intercept
        and r_value is not None
        and r2 is not None
        and 0.0 <= r2 <= 1.0
    ):
        metrics["r2_relation"] = {
            "relation": "r^2 = R^2 for OLS with intercept on the same centered design-target sample",
            "r_squared": r_value * r_value,
            "r2": r2,
            "difference": r_value * r_value - r2,
        }
    standardized = _standardized_residuals(
        winner_fit,
        residuals,
        numerically_exact_fit=exact_fit,
    )
    disclosure_diagnostics = {
        "standardized_residuals": standardized,
        "normal_frequency_comparison": _normal_frequency_comparison(standardized),
        "correlation_matrix": _correlation_matrix(winner_fit, prepared_dataset),
        "elasticities": _elasticities(winner_fit, subject_raw, predict_original),
        "outlier_count": _outlier_count(
            winner_fit,
            numerically_exact_fit=exact_fit,
        ),
    }
    candidate_spec = _mapping(_get(winner_fit, "candidate_spec"))
    target_state = _json_safe(copy.deepcopy(_get(winner_fit, "target_transform_state")))
    model = {
        "metrics": metrics,
        "metric_definitions": {
            "r": {
                "definition": "signed Pearson correlation between observed and fitted values",
                "scale": "design_target",
                "calculation": "direct correlation; never sqrt(R2)",
                "available": r_value is not None,
                "reason": (
                    None
                    if r_value is not None
                    else "observed_or_fitted_series_unavailable_constant_or_numerically_invalid"
                ),
            },
            "r2": {
                "definition": (
                    "centered coefficient of determination"
                    if has_intercept
                    else "uncentered coefficient of determination"
                ),
                "scale": "design_target",
                "has_intercept": has_intercept,
                "relation_to_r": (
                    "see metrics.r2_relation"
                    if "r2_relation" in metrics
                    else "no r^2=R^2 identity asserted"
                ),
            },
            "durbin_watson": {
                "definition": "sum((e[t]-e[t-1])^2) / sum(e[t]^2)",
                "order": "effective_sample_order",
                "scale": "design_target_residual",
                "available": metrics["durbin_watson"] is not None,
                "reason": (
                    "numerically_exact_fit_residual_order_statistic_not_informative"
                    if exact_fit
                    else None
                    if metrics["durbin_watson"] is not None
                    else "residuals_unavailable_or_zero_sse"
                ),
            },
        },
        "pvalues": _pvalues(winner_fit),
        "vif": vif,
        "target_transform_state": target_state,
        "candidate_spec": _json_safe(candidate_spec),
    }
    normative_statistical = {
        "r": metrics["r"],
        "r2": metrics["r2"],
        "r2_adjusted": metrics["r2_adjusted"],
        "f_statistic": metrics["f_statistic"],
        "f_pvalue": metrics["f_pvalue"],
        "durbin_watson": metrics["durbin_watson"],
        "vif": vif,
    }
    return {
        "model": _json_safe(model),
        "diagnostics": _json_safe(disclosure_diagnostics),
        "normative_statistical": _json_safe(normative_statistical),
    }
