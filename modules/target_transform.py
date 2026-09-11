"""Responsible target (Y) transformation: identity and log only.

Public API (MP/1 C06):
    fit_target_transform(y_train, name, options=None) -> state mapping
    transform_target(y, state)
    inverse_target_prediction(prediction, state, residual_context=None)

State and any correction parameters are learned from the training sample
passed to ``fit_target_transform``. Inverse returns original-unit values
with an explicit estimand. ``exp(E[log Y|X])``, ``E[Y|X]`` under a
lognormal assumption, and Duan smearing are distinct methods and are not
treated as interchangeable. Intervals without a validated interpretation
of the monetary mean are never labeled ``mean_ci80``.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

SUPPORTED_NAMES = ("identity", "log")
INVERSE_INVOCATION = "modules.target_transform.inverse_target_prediction"
SCHEMA_VERSION = "MP/1"

ESTIMAND_CONDITIONAL_MEAN = "E[Y|X]"
ESTIMAND_EXP_E_LOG = "exp(E[log Y|X])"

_ALLOWED_OPTION_KEYS = frozenset({"estimand"})
_ALLOWED_CORRECTIONS = frozenset({"lognormal", "smearing"})

ArrayLike = Union[np.ndarray, pd.Series, Sequence[float]]


class TargetTransformError(ValueError):
    """Invalid target-transform name, domain, or inverse request."""


def fit_target_transform(y_train, name, options=None) -> Dict[str, Any]:
    """Fit a persistable target-transform state on the training sample only."""
    if not isinstance(name, str):
        raise TypeError("target transform name must be a str")
    if name not in SUPPORTED_NAMES:
        raise ValueError(
            f"unsupported target transform {name!r}; supported: {SUPPORTED_NAMES}"
        )
    if options is None:
        options = {}
    if not isinstance(options, Mapping):
        raise TypeError("options must be a mapping or None")
    unknown = set(options) - _ALLOWED_OPTION_KEYS
    if unknown:
        raise ValueError(f"unknown target-transform options: {sorted(unknown)}")

    y = _as_1d_float(y_train, what="y_train")
    if y.size == 0:
        raise ValueError("y_train must contain at least one finite value")
    if not np.isfinite(y).all():
        raise ValueError("y_train must be finite")

    options = {k: options[k] for k in options}
    if name == "identity":
        estimand = options.get("estimand", ESTIMAND_CONDITIONAL_MEAN)
        if estimand != ESTIMAND_CONDITIONAL_MEAN:
            raise ValueError("identity estimand must be 'E[Y|X]'")
        domain = {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": True,
            "includes_negative": True,
            "description": "finite real values",
        }
        inverse_method = "identity"
        default_estimand = ESTIMAND_CONDITIONAL_MEAN
        interval_validated = True
    else:
        if np.any(y < 0):
            raise TargetTransformError("log target transform rejects negative y_train")
        if np.any(y == 0):
            raise TargetTransformError("log target transform rejects zero y_train")
        estimand = options.get("estimand", ESTIMAND_EXP_E_LOG)
        if estimand not in {ESTIMAND_EXP_E_LOG, "median", ESTIMAND_CONDITIONAL_MEAN}:
            raise ValueError(f"unsupported log estimand {estimand!r}")
        domain = {
            "requires_finite": True,
            "requires_positive": True,
            "includes_zero": False,
            "includes_negative": False,
            "description": "strictly positive finite values",
        }
        inverse_method = "exponential"
        default_estimand = (
            ESTIMAND_EXP_E_LOG if estimand != "median" else "median(Y|X)"
        )
        if estimand == ESTIMAND_CONDITIONAL_MEAN:
            # Mean on the original scale is not the default inverse; it is
            # only produced later when residual_context supplies TRAIN
            # residuals and an explicit correction method.
            default_estimand = ESTIMAND_EXP_E_LOG
        interval_validated = False

    log_y = np.log(y) if name == "log" else None
    parameters = {
        "y_min": float(np.min(y)),
        "y_max": float(np.max(y)),
    }
    if log_y is not None:
        parameters["log_y_mean"] = float(np.mean(log_y))
        parameters["log_y_var"] = float(np.var(log_y, ddof=0))
        parameters["log_moments_are_marginal_not_residual"] = True

    return {
        "schema_version": SCHEMA_VERSION,
        "component": "C06",
        "name": name,
        "n_train": int(y.size),
        "domain": domain,
        "inverse": {
            "invocation": INVERSE_INVOCATION,
            "default_method": inverse_method,
            "default_estimand": default_estimand,
        },
        "parameters": parameters,
        "options": copy.deepcopy(options),
        "comparison_scale": "original",
        "normative_interval_validated": interval_validated,
    }


def transform_target(y, state):
    """Apply a fitted target transform. Does not mutate ``state``."""
    state = _validate_state(state)
    values, index, kind = _unpack_y(y)
    name = state["name"]
    if name == "identity":
        out = values
    elif name == "log":
        if np.any(values < 0):
            raise TargetTransformError("log transform rejects negative values")
        if np.any(values == 0):
            raise TargetTransformError("log transform rejects zero")
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.log(values)
        if not np.isfinite(out).all():
            raise TargetTransformError("log transform produced non-finite values")
    else:
        raise ValueError(f"unsupported target transform {name!r}")
    return _repack_y(out, index, kind)


def inverse_target_prediction(prediction, state, residual_context=None) -> Dict[str, Any]:
    """Return original-unit values plus estimand, method, assumptions, limitations.

    ``residual_context`` is never written into ``state``. Corrections that
    estimate a mean from residuals are applied only when
    ``residual_context['origin'] == 'train'``. Holdout residuals cannot
    populate or drive that correction.
    """
    state = _validate_state(state)
    point_raw, interval, _extra = _extract_prediction(prediction)
    values, index, kind = _unpack_y(point_raw)
    issues = []
    name = state["name"]

    if name == "identity":
        out = np.array(values, dtype=float, copy=True)
        estimand = ESTIMAND_CONDITIONAL_MEAN
        method = "identity"
        assumptions = [
            "OLS (or the caller) modeled Y on the original scale.",
        ]
        limitations = [
            "Identity does not change units; comparison stays on the original Y scale.",
        ]
        mean_ci80 = _finite_interval(interval) if interval is not None else None
        interval_interpretation = "mean_ci80" if mean_ci80 is not None else None
        normative = {
            "status": "not_provided_by_c06",
            "reason": (
                "Identity is numerically equivalent to the untransformed legacy Y; "
                "normative classification remains C03's responsibility."
            ),
        }
        precisao_status = "not_computed"
        retransformed_interval = None
    elif name == "log":
        correction, correction_issue = _resolve_correction(residual_context)
        if correction_issue is not None:
            issues.append(correction_issue)
        with np.errstate(over="ignore"):
            exp_pred = np.exp(values)
        if correction == "lognormal":
            sigma2 = _train_residual_variance(residual_context)
            with np.errstate(over="ignore"):
                out = np.exp(values + 0.5 * sigma2)
            estimand = ESTIMAND_CONDITIONAL_MEAN
            method = "lognormal_mean"
            assumptions = [
                "Y|X is lognormal (additive homoscedastic errors on the log scale).",
                "Log-residual variance was estimated from training residuals only.",
            ]
            limitations = [
                "This is E[Y|X] under the lognormal assumption, not exp(E[log Y|X]) "
                "and not the conditional median.",
                "The variance used is a training residual variance, not a holdout estimate.",
            ]
        elif correction == "smearing":
            factor = _train_smearing_factor(residual_context)
            with np.errstate(over="ignore"):
                out = exp_pred * factor
            estimand = ESTIMAND_CONDITIONAL_MEAN
            method = "smearing"
            assumptions = [
                "Duan smearing: E[exp(e)|X] estimated as the mean of exp(train residuals).",
                "Does not require lognormality, but does require i.i.d. log-scale errors.",
            ]
            limitations = [
                "Smearing is not interchangeable with exp(E[log Y|X]) or with the "
                "parametric lognormal mean correction.",
                "The smearing factor was estimated from training residuals only.",
            ]
        else:
            out = exp_pred
            default_estimand = state["inverse"]["default_estimand"]
            if default_estimand == "median(Y|X)":
                estimand = "median(Y|X)"
                assumptions = [
                    "Log-scale errors are symmetric, so exp(E[log Y|X]) equals median(Y|X).",
                ]
            else:
                estimand = ESTIMAND_EXP_E_LOG
                assumptions = [
                    "The model was fit to log Y; the inverse is the exponential of the "
                    "log-scale conditional mean.",
                ]
            method = "exponential"
            limitations = [
                "exp(E[log Y|X]) is not E[Y|X]. Under symmetric log-errors it is the "
                "conditional median, which is smaller than the lognormal mean "
                "exp(μ + σ²/2) when σ>0.",
                "Median, lognormal mean, and residual smearing are not interchangeable.",
            ]
        if not np.isfinite(out).all():
            raise TargetTransformError("inverse produced non-finite values (overflow)")

        mean_ci80 = None
        retransformed_interval = None
        interval_interpretation = None
        if interval is not None:
            lo, hi = interval.get("lower"), interval.get("upper")
            try:
                lo_f, hi_f = float(lo), float(hi)
            except (TypeError, ValueError):
                lo_f = hi_f = float("nan")
            if np.isfinite(lo_f) and np.isfinite(hi_f):
                with np.errstate(over="ignore"):
                    retransformed_interval = {
                        "lower": float(np.exp(lo_f)),
                        "upper": float(np.exp(hi_f)),
                        "scale": "original",
                        "interprets": ESTIMAND_EXP_E_LOG,
                        "not": "mean_ci80",
                    }
                if not (
                    np.isfinite(retransformed_interval["lower"])
                    and np.isfinite(retransformed_interval["upper"])
                ):
                    retransformed_interval = None
                    issues.append(_issue(
                        "interval_overflow",
                        "warning",
                        "Exponentiated interval endpoints were non-finite; interval omitted.",
                    ))
                else:
                    interval_interpretation = ESTIMAND_EXP_E_LOG
                    limitations = list(limitations) + [
                        "Exponentiating both endpoints of a log-scale mean interval "
                        "does not yield a confidence interval for the monetary mean E[Y|X] "
                        "and is not published as mean_ci80 / IC80 of the mean.",
                    ]
                    issues.append(_issue(
                        "interval_not_mean_ci80",
                        "info",
                        "Retransformed interval interprets exp(E[log Y|X]), not IC80 of the mean.",
                    ))
            else:
                issues.append(_issue(
                    "interval_nonfinite",
                    "warning",
                    "Log-scale interval was not finite; no interval published.",
                ))
        normative = {
            "status": "unavailable",
            "reason": (
                "Log-Y retransformation interval methods are experimental; "
                "normative precision classification is not available from C06."
            ),
        }
        precisao_status = "not_computed"
        limitations = list(limitations) + [
            "Normative precision grade is not assigned from this retransformation.",
        ]
    else:
        raise ValueError(f"unsupported target transform {name!r}")

    if not np.isfinite(out).all():
        raise TargetTransformError("inverse produced non-finite values")

    point_out = _point_payload(out, kind, index)
    value_point = _scalar_or_none(out)
    value = {
        "point": value_point if np.ndim(out) == 0 or out.size == 1 else None,
        "mean_ci80": mean_ci80,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }
    if out.size == 1 and value["point"] is None:
        value["point"] = float(out.reshape(-1)[0])

    result = {
        "schema_version": SCHEMA_VERSION,
        "point": point_out,
        "estimand": estimand,
        "method": method,
        "assumptions": list(assumptions),
        "limitations": list(limitations),
        "unit": "original",
        "comparison_scale": "original",
        "value": value,
        "interval_interpretation": interval_interpretation,
        "retransformed_interval": retransformed_interval,
        "normative_classification": normative,
        "precisao": {
            "status": precisao_status,
            "grade": None,
            "amplitude_pct": None,
        },
        "issues": issues,
        "state_name": name,
        "inverse_invocation": INVERSE_INVOCATION,
    }
    return result


def _validate_state(state: Mapping) -> Mapping:
    if not isinstance(state, Mapping):
        raise TypeError("target transform state must be a mapping")
    name = state.get("name")
    if name not in SUPPORTED_NAMES:
        raise ValueError(f"unsupported target transform {name!r}")
    inverse = state.get("inverse") or {}
    if not isinstance(inverse, Mapping) or "invocation" not in inverse:
        raise ValueError("target transform state must record inverse invocation")
    if "domain" not in state:
        raise ValueError("target transform state must record domain")
    return state


def _as_1d_float(y, what: str) -> np.ndarray:
    if y is None or isinstance(y, (str, bytes)):
        raise TypeError(f"{what} must be a numeric array or Series")
    try:
        arr = np.asarray(y, dtype=float)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{what} must be numeric") from exc
    if arr.ndim > 1:
        arr = np.asarray(arr, dtype=float).reshape(-1)
    return np.asarray(arr, dtype=float).reshape(-1)


def _unpack_y(y):
    if isinstance(y, pd.Series):
        values = _as_1d_float(y, what="y")
        return values, y.index, "series"
    if np.isscalar(y) or (isinstance(y, np.ndarray) and y.ndim == 0):
        return np.asarray([float(y)], dtype=float), None, "scalar"
    values = _as_1d_float(y, what="y")
    return values, None, "array"


def _repack_y(out: np.ndarray, index, kind: str):
    if kind == "series":
        return pd.Series(out, index=index)
    if kind == "scalar":
        return float(out.reshape(-1)[0])
    return np.asarray(out, dtype=float)


def _point_payload(out: np.ndarray, kind: str, index):
    if kind == "scalar" or out.size == 1:
        return float(out.reshape(-1)[0])
    return [float(v) for v in out.reshape(-1)]


def _scalar_or_none(out: np.ndarray):
    if out.size == 1:
        return float(out.reshape(-1)[0])
    return None


def _extract_prediction(prediction):
    if isinstance(prediction, Mapping):
        if "point" not in prediction:
            raise ValueError("prediction mapping must include 'point'")
        interval = prediction.get("mean_ci80")
        if interval is not None and not isinstance(interval, Mapping):
            raise TypeError("mean_ci80 must be a mapping with lower and upper")
        return prediction["point"], interval, prediction
    return prediction, None, None


def _finite_interval(interval: Mapping) -> Optional[Dict[str, float]]:
    try:
        lo = float(interval["lower"])
        hi = float(interval["upper"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return None
    return {"lower": lo, "upper": hi}


def _resolve_correction(residual_context):
    if residual_context is None:
        return None, None
    if not isinstance(residual_context, Mapping):
        raise TypeError("residual_context must be a mapping or None")
    correction = residual_context.get("correction")
    if not correction:
        return None, None
    if correction not in _ALLOWED_CORRECTIONS:
        raise ValueError(f"unsupported residual correction {correction!r}")
    origin = residual_context.get("origin")
    if origin != "train":
        return None, _issue(
            "holdout_correction_ignored",
            "warning",
            "Mean correction was not applied because residual_context.origin is not 'train'.",
            evidence={"origin": origin, "correction": correction},
        )
    return correction, None


def _train_residual_variance(residual_context: Mapping) -> float:
    if residual_context.get("residual_variance") is not None:
        sigma2 = float(residual_context["residual_variance"])
        if not np.isfinite(sigma2) or sigma2 < 0:
            raise TargetTransformError("residual_variance must be a finite non-negative number")
        return sigma2
    resid = _residuals_from_context(residual_context)
    return float(np.mean(resid ** 2))


def _train_smearing_factor(residual_context: Mapping) -> float:
    resid = _residuals_from_context(residual_context)
    with np.errstate(over="ignore"):
        factor = float(np.mean(np.exp(resid)))
    if not np.isfinite(factor):
        raise TargetTransformError("smearing factor overflowed")
    return factor


def _residuals_from_context(residual_context: Mapping) -> np.ndarray:
    if "residuals" not in residual_context:
        raise ValueError("residual_context with a correction requires 'residuals' from train")
    resid = _as_1d_float(residual_context["residuals"], what="residuals")
    if resid.size == 0 or not np.isfinite(resid).all():
        raise TargetTransformError("train residuals must be finite and non-empty")
    return resid


def _issue(code: str, severity: str, message: str, evidence=None) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": "C06",
        "message": message,
        "affected_ids": [],
        "evidence": evidence or {},
    }
