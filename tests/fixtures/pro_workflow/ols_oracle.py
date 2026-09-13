"""Independent OLS / interval oracle for MP-PRO P04.

Forbidden imports: modules.*, backend.*, frontend.*, and any helper that is
under test. Allowed: numpy, scipy, math, csv, json, pathlib, and (optional
cross-check only) statsmodels.api.

Expected values are never assigned from product output.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

# Two-sided 80% is the MP/1 mean-CI convention this oracle compares against.
DEFAULT_LEVEL = 0.80
# Characteristic-interval probe used by the campaign (NBR wording pending).
FAIXA_LOW = 0.5
FAIXA_HIGH = 2.0
DEFAULT_HOLDOUT_TEST_SIZE = 0.20


class OracleError(ValueError):
    """Oracle could not form a finite reference for the given spec."""


def _as_float_array(values: Sequence[Any]) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise OracleError(f"expected 1-d array, got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise OracleError("non-finite values in oracle input")
    return arr


def design_matrix(
    columns: Mapping[str, Sequence[Any]],
    *,
    intercept: bool = True,
    column_order: Optional[Sequence[str]] = None,
) -> Tuple[np.ndarray, List[str]]:
    """Build X with an optional leading `const` column.

    `columns` maps name -> values. Order is `column_order` or insertion order.
    """
    names = list(column_order) if column_order is not None else list(columns.keys())
    if not names and not intercept:
        raise OracleError("design matrix has no columns")
    n = None
    blocks: List[np.ndarray] = []
    out_names: List[str] = []
    if intercept:
        # n inferred after first data column, or from intercept-only later
        pass
    for name in names:
        col = _as_float_array(columns[name])
        if n is None:
            n = int(col.shape[0])
        elif int(col.shape[0]) != n:
            raise OracleError(f"column {name!r} length {col.shape[0]} != {n}")
        blocks.append(col.reshape(-1, 1))
        out_names.append(str(name))
    if n is None:
        raise OracleError("cannot infer row count")
    if intercept:
        const = np.ones((n, 1), dtype=float)
        X = np.hstack([const] + blocks) if blocks else const
        return X, ["const"] + out_names
    X = np.hstack(blocks)
    return X, out_names


def encode_treatment(
    values: Sequence[Any],
    *,
    training_mask: Optional[Sequence[bool]] = None,
    column: str = "cat",
) -> Dict[str, Any]:
    """Lexicographic treatment coding learned on training rows only.

    Reference = first sorted training level. Unknown levels are unsupported.
    """
    n = len(values)
    if training_mask is None:
        mask = [True] * n
    else:
        mask = [bool(x) for x in training_mask]
        if len(mask) != n:
            raise OracleError("training_mask length mismatch")
    train_levels = sorted(
        {str(v) for v, keep in zip(values, mask) if keep and v is not None and str(v).strip() != ""}
    )
    if not train_levels:
        raise OracleError(f"no training levels for {column}")
    reference = train_levels[0]
    dummies = [lv for lv in train_levels if lv != reference]
    dummy_names = [f"{column}={lv}" for lv in dummies]
    matrix: Dict[str, List[float]] = {name: [0.0] * n for name in dummy_names}
    supported = [True] * n
    for i, raw in enumerate(values):
        token = None if raw is None else str(raw).strip()
        if not token:
            supported[i] = False
            continue
        if token not in train_levels:
            supported[i] = False
            continue
        if token == reference:
            continue
        matrix[f"{column}={token}"][i] = 1.0
    return {
        "reference": reference,
        "levels": train_levels,
        "dummy_names": dummy_names,
        "columns": matrix,
        "supported": supported,
        "convention": "lexicographic_first_reference",
    }


def fit_ols(
    y: Sequence[Any],
    columns: Mapping[str, Sequence[Any]],
    *,
    intercept: bool = True,
    column_order: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """QR-OLS. Returns coefficients, sigma2, xtx_inv, residuals, names."""
    y_arr = _as_float_array(y)
    X, names = design_matrix(columns, intercept=intercept, column_order=column_order)
    if X.shape[0] != y_arr.shape[0]:
        raise OracleError("y and X row counts differ")
    n, p = X.shape
    if n <= p:
        raise OracleError(f"need n > p, got n={n} p={p}")
    q, r = np.linalg.qr(X, mode="reduced")
    # Rank check: zero diagonal in R
    diag = np.abs(np.diag(r))
    if np.any(diag < 1e-12):
        raise OracleError("design matrix is rank-deficient for the oracle")
    beta = np.linalg.solve(r, q.T @ y_arr)
    fitted = X @ beta
    resid = y_arr - fitted
    df = int(n - p)
    sse = float(resid @ resid)
    sigma2 = sse / df
    r_inv = np.linalg.inv(r)
    xtx_inv = r_inv @ r_inv.T
    return {
        "coefficients": {name: float(val) for name, val in zip(names, beta)},
        "beta": beta,
        "names": names,
        "sigma2": float(sigma2),
        "sigma": float(math.sqrt(sigma2)),
        "xtx_inv": xtx_inv,
        "X": X,
        "y": y_arr,
        "fitted": fitted,
        "residuals": resid,
        "n": int(n),
        "p": int(p),
        "df": df,
        "sse": sse,
        "method": "qr",
        "variance": "unbiased_n_minus_p",
    }


def t_critical(df: int, level: float = DEFAULT_LEVEL) -> float:
    if not 0.0 < level < 1.0:
        raise OracleError(f"level must be in (0,1), got {level}")
    if df < 1:
        raise OracleError("df < 1")
    return float(stats.t.ppf(0.5 + 0.5 * level, df))


def predict_intervals(
    fit: Mapping[str, Any],
    x0: Mapping[str, float],
    *,
    level: float = DEFAULT_LEVEL,
) -> Dict[str, Any]:
    """Mean CI (se_mean) and prediction interval (se_pred) at x0."""
    names: List[str] = list(fit["names"])
    row = np.array([1.0 if name == "const" else float(x0.get(name, 0.0)) for name in names], dtype=float)
    if names and names[0] == "const":
        row[0] = 1.0
        for i, name in enumerate(names[1:], start=1):
            if name not in x0:
                raise OracleError(f"subject missing design column {name!r}")
            row[i] = float(x0[name])
    else:
        for i, name in enumerate(names):
            if name not in x0:
                raise OracleError(f"subject missing design column {name!r}")
            row[i] = float(x0[name])
    beta = np.asarray(fit["beta"], dtype=float)
    xtx_inv = np.asarray(fit["xtx_inv"], dtype=float)
    sigma2 = float(fit["sigma2"])
    df = int(fit["df"])
    yhat = float(row @ beta)
    leverage = float(row @ xtx_inv @ row)
    if leverage < 0:
        raise OracleError("negative leverage")
    se_mean = math.sqrt(sigma2 * leverage)
    se_pred = math.sqrt(sigma2 * (1.0 + leverage))
    tcrit = t_critical(df, level)
    mean_ci = {
        "lower": yhat - tcrit * se_mean,
        "upper": yhat + tcrit * se_mean,
        "level": level,
        "kind": "mean",
    }
    pred_int = {
        "lower": yhat - tcrit * se_pred,
        "upper": yhat + tcrit * se_pred,
        "level": level,
        "kind": "observation",
    }
    return {
        "point": yhat,
        "mean_ci": mean_ci,
        "prediction_interval": pred_int,
        "se_mean": se_mean,
        "se_pred": se_pred,
        "t_critical": tcrit,
        "leverage": leverage,
        "level": level,
        "df": df,
        "convention": "two_sided_student_t",
    }


def statsmodels_crosscheck(
    y: Sequence[Any],
    columns: Mapping[str, Sequence[Any]],
    x0: Mapping[str, float],
    *,
    intercept: bool = True,
    column_order: Optional[Sequence[str]] = None,
    level: float = DEFAULT_LEVEL,
) -> Dict[str, Any]:
    """Optional library cross-check. Imports statsmodels, never product code."""
    import pandas as pd
    import statsmodels.api as sm

    y_arr = _as_float_array(y)
    X, names = design_matrix(columns, intercept=intercept, column_order=column_order)
    frame = pd.DataFrame(X, columns=names)
    model = sm.OLS(y_arr, frame).fit(method="qr", use_t=True)
    row = {name: (1.0 if name == "const" else float(x0[name])) for name in names}
    subj = pd.DataFrame([row], columns=names)
    alpha = 1.0 - float(level)
    summary = model.get_prediction(subj).summary_frame(alpha=alpha)
    return {
        "point": float(summary["mean"].iloc[0]),
        "mean_ci": {
            "lower": float(summary["mean_ci_lower"].iloc[0]),
            "upper": float(summary["mean_ci_upper"].iloc[0]),
        },
        "prediction_interval": {
            "lower": float(summary["obs_ci_lower"].iloc[0]),
            "upper": float(summary["obs_ci_upper"].iloc[0]),
        },
        "params": {name: float(model.params[name]) for name in names},
    }


def holdout_reserved_ids(
    row_ids: Sequence[Any],
    *,
    seed: int,
    test_size: float = DEFAULT_HOLDOUT_TEST_SIZE,
) -> List[Any]:
    """Independent n_splits=1 holdout: RandomState(seed).shuffle, first n_test."""
    ids = list(row_ids)
    n = len(ids)
    if n < 2:
        raise OracleError("need at least 2 rows for holdout")
    rng = np.random.RandomState(int(seed))
    order = list(ids)
    rng.shuffle(order)
    n_test = int(round(n * float(test_size)))
    n_test = min(max(n_test, 1), n - 1)
    return list(order[:n_test])


def cook_distance(fit: Mapping[str, Any]) -> np.ndarray:
    """Independent Cook's D from the fitted QR-OLS object."""
    X = np.asarray(fit["X"], dtype=float)
    resid = np.asarray(fit["residuals"], dtype=float)
    xtx_inv = np.asarray(fit["xtx_inv"], dtype=float)
    sigma2 = float(fit["sigma2"])
    p = int(fit["p"])
    # h_ii = x_i (X'X)^{-1} x_i'
    h = np.sum((X @ xtx_inv) * X, axis=1)
    with np.errstate(divide="raise", invalid="raise"):
        d = (resid ** 2 / (p * sigma2)) * (h / (1.0 - h) ** 2)
    return np.asarray(d, dtype=float)


def faixa_ampliada(value: float, sample_min: float, sample_max: float) -> str:
    """in_sample | extended | outside_extended. Probe, not a verified NBR quote."""
    if sample_min <= value <= sample_max:
        return "in_sample"
    ext_min = FAIXA_LOW * sample_min
    ext_max = FAIXA_HIGH * sample_max
    if ext_min <= value <= ext_max:
        return "extended"
    return "outside_extended"


def efeito_monetario(predicted: float, sample_y_min: float, sample_y_max: float) -> str:
    if sample_y_min <= predicted <= sample_y_max:
        return "price_in_sample"
    return "price_outside_sample"


def close(a: Any, b: Any, *, abs_tol: float = 1e-6, rel_tol: float = 1e-6) -> bool:
    try:
        fa = float(a)
        fb = float(b)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return False
    return abs(fa - fb) <= max(abs_tol, rel_tol * max(abs(fa), abs(fb)))


def interval_close(
    observed: Optional[Mapping[str, Any]],
    expected: Mapping[str, Any],
    *,
    abs_tol: float = 1e-4,
    rel_tol: float = 1e-6,
) -> bool:
    if not isinstance(observed, Mapping):
        return False
    return close(observed.get("lower"), expected["lower"], abs_tol=abs_tol, rel_tol=rel_tol) and close(
        observed.get("upper"), expected["upper"], abs_tol=abs_tol, rel_tol=rel_tol
    )


def parse_number(text: str, locale: str) -> float:
    """Locale-aware parse. Independent of modules.utils.safe_float_conversion."""
    import re

    if locale not in {"pt-BR", "en-US"}:
        raise OracleError(f"locale must be pt-BR or en-US, got {locale!r}")
    raw = str(text).strip()
    raw = re.sub(r"R\$\s*", "", raw).strip()
    if locale == "pt-BR":
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif raw.count(".") == 1:
            raw = raw.replace(".", "")
        return float(raw)
    return float(raw.replace(",", ""))


def count_observed_target(rows: Iterable[Mapping[str, Any]], target_col: str) -> int:
    n = 0
    for row in rows:
        val = row.get(target_col)
        if val is None:
            continue
        if isinstance(val, float) and math.isnan(val):
            continue
        text = str(val).strip()
        if text == "" or text.lower() in {"nan", "none", "null"}:
            continue
        n += 1
    return n
