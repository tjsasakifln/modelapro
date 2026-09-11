"""Versioned OLS residual/design state for freeze, restore, batch, and dossier.

JSON only. Never pickle, never a function, never a model_object. The fit's
QR solution is preferred; an unstable inverse is not forced when the live
adjustment used another factorization.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RESIDUAL_STATE_SCHEMA = "MP-PRO/1"
CALCULATION_VERSION = "MP-PRO/1-ols-qr"

# (X'X)^{-1} as stored by statsmodels OLS Results.normalized_cov_params.
XTX_INV_KIND_NORMALIZED = "normalized_cov_params"
# sigma^2 * (X'X)^{-1} = Results.cov_params().
XTX_INV_KIND_COVARIANCE = "cov_params"

# statsmodels RegressionResults.scale = SSR / df_resid = residual variance.
SCALE_CONVENTION_STATSMODELS = "statsmodels.scale"

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"
STATUS_MALFORMED = "malformed"

LIMITATION_INCOMPLETE = "residual_state_incomplete"
LIMITATION_MALFORMED = "residual_state_malformed"
LIMITATION_NO_INTERVALS = "statistical_intervals_unavailable"
LIMITATION_NO_PINV = "unstable_inverse_not_forced"

MEAN_CI_LEVEL = 0.80


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    getter = getattr(obj, "get", None)
    if callable(getter):
        return {}
    data = getattr(obj, "__dict__", None)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if not str(k).startswith("_")}
    return {}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _matrix_to_lists(matrix: Any) -> Optional[List[List[float]]]:
    if matrix is None:
        return None
    try:
        import numpy as np

        arr = np.asarray(matrix, dtype=float)
    except Exception:
        if not isinstance(matrix, (list, tuple)):
            return None
        rows: List[List[float]] = []
        for row in matrix:
            if not isinstance(row, (list, tuple)):
                return None
            converted = [_finite(v) for v in row]
            if any(v is None for v in converted):
                return None
            rows.append([float(v) for v in converted])
        if not rows or any(len(r) != len(rows) for r in rows):
            return None
        return rows
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1] or arr.size == 0:
        return None
    if not bool(__import__("numpy").isfinite(arr).all()):
        return None
    return [[float(v) for v in row] for row in arr.tolist()]


def _vector_to_list(values: Any) -> Optional[List[float]]:
    if values is None:
        return None
    try:
        import numpy as np

        arr = np.asarray(values, dtype=float).reshape(-1)
    except Exception:
        if not isinstance(values, (list, tuple)):
            return None
        converted = [_finite(v) for v in values]
        if any(v is None for v in converted):
            return None
        return [float(v) for v in converted]
    if arr.size == 0 or not bool(__import__("numpy").isfinite(arr).all()):
        return None
    return [float(v) for v in arr.tolist()]


def _t_critical(df: float, level: float = MEAN_CI_LEVEL) -> Optional[float]:
    if df is None or df <= 0:
        return None
    try:
        from scipy import stats

        q = 1.0 - (1.0 - float(level)) / 2.0
        value = float(stats.t.ppf(q, df))
    except Exception:
        if abs(float(level) - 0.80) < 1e-9:
            value = 1.2815515655446004
        else:
            return None
    return value if math.isfinite(value) else None


def _empty_state(*, status: str, limitations: Sequence[str], **extra: Any) -> Dict[str, Any]:
    payload = {
        "schema_version": RESIDUAL_STATE_SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "status": status,
        "feature_order": [],
        "has_intercept": None,
        "intercept_column": None,
        "n": None,
        "k": None,
        "df_resid": None,
        "n_design_columns": None,
        "residual_scale": None,
        "residual_std": None,
        "scale_convention": SCALE_CONVENTION_STATSMODELS,
        "xtx_inv": None,
        "xtx_inv_kind": XTX_INV_KIND_NORMALIZED,
        "solver": "qr",
        "coefficients": {},
        "used_row_ids": [],
        "limitations": [str(x) for x in limitations],
        "interval_method": "ols_mean_and_prediction",
        "interval_scale": "transformed",
        "t_crit_80": None,
        "mean_ci_level": MEAN_CI_LEVEL,
        "subject_x": None,
    }
    payload.update(extra)
    return payload


def residual_state_is_complete(state: Any) -> bool:
    block = _as_mapping(state)
    if block.get("status") != STATUS_COMPLETE:
        return False
    order = list(block.get("feature_order") or [])
    xtx = block.get("xtx_inv")
    std = _finite(block.get("residual_std"))
    df = _finite(block.get("df_resid"))
    if not order or std is None or std < 0 or df is None or df <= 0:
        return False
    if not isinstance(xtx, list) or len(xtx) != len(order):
        return False
    if any(not isinstance(row, list) or len(row) != len(order) for row in xtx):
        return False
    kind = block.get("xtx_inv_kind")
    return kind in {XTX_INV_KIND_NORMALIZED, XTX_INV_KIND_COVARIANCE, None}


def json_safe_residual_state(state: Any) -> Dict[str, Any]:
    """Drop anything that is not RFC-8259 JSON. Never keep model_object."""
    block = _as_mapping(state)
    block.pop("model_object", None)
    block.pop("pickle", None)
    out = _empty_state(
        status=str(block.get("status") or STATUS_INCOMPLETE),
        limitations=list(block.get("limitations") or []),
    )
    for key in out:
        if key in block:
            out[key] = block[key]
    out["feature_order"] = [str(x) for x in list(out.get("feature_order") or [])]
    coeffs = _as_mapping(out.get("coefficients"))
    safe_coeffs: Dict[str, float] = {}
    for name, value in coeffs.items():
        number = _finite(value)
        if number is not None:
            safe_coeffs[str(name)] = number
    out["coefficients"] = safe_coeffs
    out["used_row_ids"] = [str(x) for x in list(out.get("used_row_ids") or [])]
    xtx = _matrix_to_lists(out.get("xtx_inv"))
    out["xtx_inv"] = xtx
    if out.get("subject_x") is not None:
        out["subject_x"] = _vector_to_list(out.get("subject_x"))
    for numeric_key in (
        "n",
        "k",
        "df_resid",
        "n_design_columns",
        "residual_scale",
        "residual_std",
        "t_crit_80",
        "mean_ci_level",
    ):
        if out.get(numeric_key) is not None:
            number = _finite(out.get(numeric_key))
            out[numeric_key] = int(number) if numeric_key in {"n", "k", "n_design_columns"} and number is not None else number
    if out.get("has_intercept") is not None:
        out["has_intercept"] = bool(out.get("has_intercept"))
    out["schema_version"] = RESIDUAL_STATE_SCHEMA
    out["calculation_version"] = str(block.get("calculation_version") or CALCULATION_VERSION)
    if not residual_state_is_complete(out) and out.get("status") == STATUS_COMPLETE:
        out["status"] = STATUS_INCOMPLETE
        limitations = list(out.get("limitations") or [])
        if LIMITATION_INCOMPLETE not in limitations:
            limitations.append(LIMITATION_INCOMPLETE)
        out["limitations"] = limitations
    return out


def _design_from_fit(winner_fit: Any) -> Tuple[Optional[Any], Optional[Any], List[str]]:
    x_design = _get(winner_fit, "X_design")
    y_design = _get(winner_fit, "y_design")
    diagnostics = _as_mapping(_get(winner_fit, "diagnostics"))
    model_state = _as_mapping(_get(winner_fit, "model_state"))
    coefficients = _as_mapping(_get(winner_fit, "coefficients")) or _as_mapping(
        model_state.get("coefficients")
    )
    order = list(
        model_state.get("feature_order")
        or diagnostics.get("design_columns")
        or coefficients.keys()
    )
    order = [str(x) for x in order]
    return x_design, y_design, order


def _from_statsmodels(model: Any, order: Sequence[str]) -> Optional[Dict[str, Any]]:
    if model is None:
        return None
    ncp = getattr(model, "normalized_cov_params", None)
    scale = _finite(getattr(model, "scale", None))
    df_resid = _finite(getattr(model, "df_resid", None))
    xtx = _matrix_to_lists(ncp)
    if xtx is None or scale is None or scale < 0 or df_resid is None:
        return None
    if order and len(xtx) != len(order):
        params = getattr(model, "params", None)
        names = None
        if params is not None and hasattr(params, "index"):
            names = [str(x) for x in list(params.index)]
        if names and len(names) == len(xtx):
            order = names
        else:
            return None
    residual_std = math.sqrt(scale) if scale >= 0 else None
    if residual_std is None or not math.isfinite(residual_std):
        return None
    params = getattr(model, "params", None)
    coefficients: Dict[str, float] = {}
    if params is not None and hasattr(params, "items"):
        for name, value in params.items():
            number = _finite(value)
            if number is not None:
                coefficients[str(name)] = number
    nobs = _finite(getattr(model, "nobs", None))
    return {
        "xtx_inv": xtx,
        "xtx_inv_kind": XTX_INV_KIND_NORMALIZED,
        "residual_scale": scale,
        "residual_std": residual_std,
        "df_resid": df_resid,
        "n": int(nobs) if nobs is not None else None,
        "n_design_columns": len(xtx),
        "coefficients": coefficients,
        "feature_order": list(order) if order else [str(i) for i in range(len(xtx))],
        "solver": "qr",
        "source": "statsmodels.normalized_cov_params",
    }


def _from_design_qr(x_design: Any, y_design: Any, order: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Reconstruct (X'X)^{-1} via the same QR path the live OLS fit uses.

    Rank deficiency is reported; pseudoinverse is not used.
    """
    try:
        import numpy as np
    except Exception:
        return None
    try:
        if hasattr(x_design, "to_numpy"):
            if order and hasattr(x_design, "columns"):
                cols = [c for c in order if c in list(x_design.columns)]
                if len(cols) == len(order):
                    x_design = x_design.loc[:, cols]
            X = np.asarray(x_design.to_numpy(), dtype=float)
            if not order and hasattr(x_design, "columns"):
                order = [str(c) for c in x_design.columns]
        else:
            X = np.asarray(x_design, dtype=float)
        y = np.asarray(y_design, dtype=float).reshape(-1)
    except Exception:
        return None
    if X.ndim != 2 or X.shape[0] == 0 or X.shape[1] == 0:
        return None
    if y.shape[0] != X.shape[0]:
        return None
    if not np.isfinite(X).all() or not np.isfinite(y).all():
        return None
    n, p = int(X.shape[0]), int(X.shape[1])
    if n <= p:
        return None
    try:
        _q, r = np.linalg.qr(X, mode="reduced")
    except np.linalg.LinAlgError:
        return None
    diag = np.abs(np.diag(r))
    if diag.size == 0:
        return None
    tol = 1e-12 * float(diag.max()) if float(diag.max()) > 0 else 1e-12
    if int(np.sum(diag > tol)) < p:
        return None
    try:
        xtx_inv = np.linalg.inv(r.T @ r)
    except np.linalg.LinAlgError:
        return None
    if not np.isfinite(xtx_inv).all():
        return None
    beta, residuals, rank, _s = np.linalg.lstsq(X, y, rcond=None)
    if int(rank) < p:
        return None
    resid = y - X @ beta
    df_resid = float(n - p)
    ssr = float(np.dot(resid, resid))
    scale = ssr / df_resid if df_resid > 0 else None
    if scale is None or scale < 0 or not math.isfinite(scale):
        return None
    residual_std = math.sqrt(scale)
    names = list(order) if order and len(order) == p else [f"x{i}" for i in range(p)]
    coefficients = {names[i]: float(beta[i]) for i in range(p) if math.isfinite(float(beta[i]))}
    return {
        "xtx_inv": [[float(v) for v in row] for row in xtx_inv.tolist()],
        "xtx_inv_kind": XTX_INV_KIND_NORMALIZED,
        "residual_scale": scale,
        "residual_std": residual_std,
        "df_resid": df_resid,
        "n": n,
        "n_design_columns": p,
        "coefficients": coefficients,
        "feature_order": names,
        "solver": "qr",
        "source": "design_qr",
    }


def declared_residual_status(state: Any) -> Optional[str]:
    block = _as_mapping(state)
    status = block.get("status")
    if status in {STATUS_COMPLETE, STATUS_INCOMPLETE, STATUS_MALFORMED}:
        return str(status)
    return None


def extract_residual_state(winner_fit: Any) -> Dict[str, Any]:
    """Pull JSON-safe residual/design state from a live CandidateFit or mapping.

    A declared MP-PRO/1 block with status incomplete/malformed is never
    rebuilt from stored xtx_inv. Live reconstruction uses model_object or
    the QR of X_design, not an untyped inverse already on disk.
    """
    existing = _get(winner_fit, "residual_state")
    if existing is None:
        existing = _as_mapping(_get(winner_fit, "model_state")).get("residual_state")
    if isinstance(existing, Mapping) and existing.get("schema_version") == RESIDUAL_STATE_SCHEMA:
        status = declared_residual_status(existing)
        safe = json_safe_residual_state(existing)
        if status in {STATUS_INCOMPLETE, STATUS_MALFORMED}:
            limitations = list(safe.get("limitations") or [])
            if status == STATUS_MALFORMED and LIMITATION_MALFORMED not in limitations:
                limitations.append(LIMITATION_MALFORMED)
            if LIMITATION_NO_INTERVALS not in limitations:
                limitations.append(LIMITATION_NO_INTERVALS)
            if status == STATUS_INCOMPLETE and LIMITATION_INCOMPLETE not in limitations:
                limitations.append(LIMITATION_INCOMPLETE)
            safe["status"] = status
            safe["limitations"] = limitations
            return safe
        if residual_state_is_complete(safe):
            return safe
        # Declared schema but not complete: do not promote stored xtx_inv.
        limitations = list(safe.get("limitations") or [])
        if LIMITATION_INCOMPLETE not in limitations:
            limitations.append(LIMITATION_INCOMPLETE)
        if LIMITATION_NO_INTERVALS not in limitations:
            limitations.append(LIMITATION_NO_INTERVALS)
        safe["status"] = STATUS_INCOMPLETE
        safe["limitations"] = limitations
        return safe

    diagnostics = _as_mapping(_get(winner_fit, "diagnostics"))
    model_state = _as_mapping(_get(winner_fit, "model_state"))
    coefficients = _as_mapping(_get(winner_fit, "coefficients")) or _as_mapping(
        model_state.get("coefficients")
    )
    x_design, y_design, order = _design_from_fit(winner_fit)
    if not order:
        order = [str(k) for k in coefficients.keys()]

    model = _get(winner_fit, "model_object")
    extracted = _from_statsmodels(model, order)
    source_limitations: List[str] = []
    if extracted is None:
        extracted = _from_design_qr(x_design, y_design, order)
        if extracted is None:
            # Stored xtx_inv without a complete residual_state is not (X'X)^{-1}.
            limitations = [LIMITATION_INCOMPLETE, LIMITATION_NO_INTERVALS, LIMITATION_NO_PINV]
            return json_safe_residual_state(
                _empty_state(
                    status=STATUS_INCOMPLETE,
                    limitations=limitations,
                    feature_order=order,
                    coefficients={str(k): v for k, v in coefficients.items() if _finite(v) is not None},
                    used_row_ids=[str(x) for x in list(_get(winner_fit, "used_row_ids") or [])],
                    n=_finite(diagnostics.get("n") or model_state.get("n") or _get(winner_fit, "n")),
                    k=_finite(diagnostics.get("k") or model_state.get("k") or _get(winner_fit, "k")),
                    has_intercept=diagnostics.get("has_intercept"),
                    intercept_column=diagnostics.get("intercept_column"),
                )
            )

    n = extracted.get("n")
    if n is None:
        n = _finite(diagnostics.get("n") or model_state.get("n") or _get(winner_fit, "n"))
    k = _finite(diagnostics.get("k") or model_state.get("k") or _get(winner_fit, "k"))
    n_cols = extracted.get("n_design_columns")
    has_intercept = diagnostics.get("has_intercept")
    intercept_col = diagnostics.get("intercept_column")
    feature_order = list(extracted.get("feature_order") or order)
    if has_intercept is None:
        has_intercept = "const" in feature_order or intercept_col in feature_order
    if k is None and n_cols is not None:
        k = max(0, int(n_cols) - (1 if has_intercept else 0))
    coeffs = dict(extracted.get("coefficients") or {})
    if not coeffs:
        coeffs = {str(k_): float(v) for k_, v in coefficients.items() if _finite(v) is not None}
    df_resid = extracted.get("df_resid")
    t_crit = _t_critical(float(df_resid), MEAN_CI_LEVEL) if df_resid is not None else None
    used = [str(x) for x in list(_get(winner_fit, "used_row_ids") or [])]
    y_state = _get(winner_fit, "target_transform_state") or model_state.get("target_transform_state")
    y_name = None
    if isinstance(y_state, Mapping):
        y_name = y_state.get("name")
    elif isinstance(y_state, str):
        y_name = y_state
    spec = _as_mapping(_get(winner_fit, "candidate_spec"))
    if y_name is None:
        raw_y = spec.get("y_transformation")
        y_name = raw_y.get("name") if isinstance(raw_y, Mapping) else raw_y
    identity = str(y_name or "identity").lower() in {"", "identity", "linear", "none"}
    payload = _empty_state(
        status=STATUS_COMPLETE,
        limitations=source_limitations,
        feature_order=feature_order,
        has_intercept=bool(has_intercept),
        intercept_column=intercept_col if intercept_col else ("const" if "const" in feature_order else None),
        n=int(n) if n is not None else None,
        k=int(k) if k is not None else None,
        df_resid=_finite(df_resid),
        n_design_columns=int(n_cols) if n_cols is not None else len(feature_order),
        residual_scale=_finite(extracted.get("residual_scale")),
        residual_std=_finite(extracted.get("residual_std")),
        scale_convention=SCALE_CONVENTION_STATSMODELS,
        xtx_inv=extracted.get("xtx_inv"),
        xtx_inv_kind=extracted.get("xtx_inv_kind") or XTX_INV_KIND_NORMALIZED,
        solver=str(extracted.get("solver") or "qr"),
        coefficients=coeffs,
        used_row_ids=used,
        t_crit_80=t_crit,
        source=extracted.get("source"),
        interval_scale="original" if identity else "transformed",
    )
    return json_safe_residual_state(payload)


def subject_x_from_design(subject_design: Any, feature_order: Sequence[str]) -> Optional[List[float]]:
    """Row of the design in residual feature_order. Missing entries → None (not 0)."""
    if not feature_order:
        return None
    x_obj = _get(subject_design, "X")
    x_map: Dict[str, Any] = {}
    if isinstance(x_obj, Mapping):
        x_map = dict(x_obj)
    elif hasattr(x_obj, "iloc"):
        try:
            x_map = dict(x_obj.iloc[0])
        except Exception:
            x_map = {}
    raw = _get(subject_design, "raw_values") or _get(subject_design, "raw") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    vec: List[float] = []
    for name in feature_order:
        if name == "const":
            value = _finite(x_map.get(name))
            vec.append(1.0 if value is None else value)
            continue
        value = _finite(x_map.get(name))
        if value is None:
            value = _finite(raw.get(name))
        if value is None:
            return None
        vec.append(value)
    return vec


def apply_mean_prediction_intervals(
    x_row: Mapping[str, float],
    residual_state: Any,
    *,
    point_transformed: float,
) -> Dict[str, Any]:
    """Mean CI80 and prediction interval on the modeled scale.

    Uses stored (X'X)^{-1} and residual_std. Does not invert a matrix and
    does not invent a percent band when state is incomplete or malformed.
    """
    state = json_safe_residual_state(residual_state)
    limitations = list(state.get("limitations") or [])
    empty = {
        "mean_ci80": None,
        "prediction_interval": None,
        "se_mean": None,
        "se_pred": None,
        "limitations": limitations,
        "supported": False,
    }
    if not residual_state_is_complete(state):
        if LIMITATION_NO_INTERVALS not in limitations:
            limitations.append(LIMITATION_NO_INTERVALS)
        if state.get("status") == STATUS_MALFORMED:
            if LIMITATION_MALFORMED not in limitations:
                limitations.append(LIMITATION_MALFORMED)
        else:
            if LIMITATION_INCOMPLETE not in limitations:
                limitations.append(LIMITATION_INCOMPLETE)
        empty["limitations"] = limitations
        return empty

    order = [str(x) for x in state["feature_order"]]
    x_vec: List[float] = []
    for name in order:
        if name == "const" or name == state.get("intercept_column"):
            value = _finite(x_row.get(name))
            x_vec.append(1.0 if value is None else value)
            continue
        value = _finite(x_row.get(name))
        if value is None:
            limitations.append(LIMITATION_MALFORMED)
            limitations.append(LIMITATION_NO_INTERVALS)
            empty["limitations"] = limitations
            return empty
        x_vec.append(value)

    xtx = state["xtx_inv"]
    try:
        tmp = [sum(float(xtx[i][j]) * x_vec[j] for j in range(len(x_vec))) for i in range(len(x_vec))]
        quad = sum(x_vec[i] * tmp[i] for i in range(len(x_vec)))
    except (TypeError, ValueError, IndexError):
        limitations.extend([LIMITATION_MALFORMED, LIMITATION_NO_INTERVALS])
        empty["limitations"] = limitations
        return empty
    if not math.isfinite(quad) or quad < -1e-12:
        limitations.extend([LIMITATION_MALFORMED, LIMITATION_NO_INTERVALS])
        empty["limitations"] = limitations
        return empty
    quad = max(0.0, float(quad))

    kind = state.get("xtx_inv_kind") or XTX_INV_KIND_NORMALIZED
    residual_std = float(state["residual_std"])
    if kind == XTX_INV_KIND_COVARIANCE:
        # x' (sigma^2 (X'X)^{-1}) x = se_mean^2; do not multiply sigma again.
        se_mean = math.sqrt(quad) if quad >= 0 else None
        se_pred = math.sqrt(max(0.0, residual_std * residual_std + quad)) if se_mean is not None else None
    elif kind == XTX_INV_KIND_NORMALIZED:
        se_mean = residual_std * math.sqrt(quad)
        se_pred = residual_std * math.sqrt(max(0.0, 1.0 + quad))
    else:
        limitations.extend([LIMITATION_MALFORMED, LIMITATION_NO_INTERVALS])
        empty["limitations"] = limitations
        return empty

    df = float(state["df_resid"])
    t_crit = _finite(state.get("t_crit_80")) or _t_critical(df, MEAN_CI_LEVEL)
    if se_mean is None or t_crit is None or not math.isfinite(se_mean) or not math.isfinite(t_crit):
        limitations.append(LIMITATION_NO_INTERVALS)
        empty["limitations"] = limitations
        return empty

    point = float(point_transformed)
    mean_ci = {
        "lower": point - t_crit * se_mean,
        "upper": point + t_crit * se_mean,
        "level": MEAN_CI_LEVEL,
        "kind": "mean",
    }
    pred = {
        "lower": point - t_crit * se_pred,
        "upper": point + t_crit * se_pred,
        "level": MEAN_CI_LEVEL,
        "kind": "observation",
    }
    return {
        "mean_ci80": mean_ci,
        "prediction_interval": pred,
        "se_mean": se_mean,
        "se_pred": se_pred,
        "limitations": limitations,
        "supported": True,
        "xtx_inv_kind": kind,
        "scale_convention": state.get("scale_convention"),
    }
