"""C04 fitting: candidate OLS, evaluation of a subject, justified exclusions.

Public MP/1 entry points: ``fit_candidate`` and ``evaluate_fitted``.
``ModelBuilder.build_model`` / ``add_precision_and_extrapolation`` remain as
legacy adapters. Influence is reported, never a silent sample rewrite.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson

from .config_manager import config
from .influence_policy import (
    COMPARISON_BLOCK_DIVERGENT_SAMPLE,
    ORIGIN_PRE_FIT_INPUT_ERROR,
    ORIGIN_TRANSFORM_DOMAIN,
    ExclusionRecord,
    influence_does_not_authorize_exclusion,
    make_issue,
    parse_outlier_policy,
    resolve_sample,
)
from .logging_manager import logger
from .nbr14653_validation import NBRValidator
from .results import ModelMetrics, ModelResult
from .transformations import Transformer

SCHEMA_VERSION = "MP/1"
ORIGIN = "C04"
STATUS_FITTED = "fitted"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"
Y_IDENTITY_NAMES = {None, "", "identity", "linear", "none", "None"}
# C06 publishes identity|log. "ln" is the X-transformer name; map it for the target.
C06_Y_NAME_ALIASES = {
    "identity": "identity",
    "linear": "identity",
    "none": "identity",
    "log": "log",
    "ln": "log",
    "logarithm": "log",
}
MEAN_CI_LEVEL = 0.80

_C06_CACHE = None
_C03_CACHE = None
_C02_CACHE = None


def _reset_dependency_caches() -> None:
    """Test helper: drop lazy C02/C03/C06 lookups."""
    global _C06_CACHE, _C03_CACHE, _C02_CACHE
    _C06_CACHE = None
    _C03_CACHE = None
    _C02_CACHE = None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj[key] if key in obj else default
    return getattr(obj, key, default)


def _as_mapping(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return dict(obj.to_dict())
        except TypeError:
            pass
    data = {}
    for key in getattr(obj, "__dataclass_fields__", {}) or []:
        data[key] = getattr(obj, key)
    return data or {}


def _as_id(value: Any) -> Any:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return str(value)


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _progress(callback: Optional[Callable], stage: str, fraction: Optional[float]) -> None:
    if callback is None:
        return
    try:
        payload = {"stage": stage, "progress": None if fraction is None else float(fraction)}
        if payload["progress"] is not None:
            payload["progress"] = max(0.0, min(1.0, payload["progress"]))
        callback(payload)
    except Exception:
        logger.exception("progress_callback failed at stage %s", stage)


def _cancelled(cancel_requested: Optional[Callable]) -> bool:
    if cancel_requested is None:
        return False
    try:
        return bool(cancel_requested())
    except Exception:
        logger.exception("cancel_requested failed")
        return False


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_identity_y(name: Any) -> bool:
    if name is None:
        return True
    return str(name).strip().lower() in {n for n in Y_IDENTITY_NAMES if isinstance(n, str)} or name in Y_IDENTITY_NAMES


def _c06_y_name(name: Any) -> Optional[str]:
    if _is_identity_y(name):
        return "identity"
    key = str(name).strip().lower()
    return C06_Y_NAME_ALIASES.get(key, key)


def _load_c06() -> Optional[Dict[str, Callable]]:
    global _C06_CACHE
    if _C06_CACHE is not None:
        return None if _C06_CACHE is False else _C06_CACHE
    try:
        from . import target_transform as tt
    except ImportError:
        try:
            import modules.target_transform as tt  # type: ignore
        except ImportError:
            _C06_CACHE = False
            return None
    fit = getattr(tt, "fit_target_transform", None)
    transform = getattr(tt, "transform_target", None)
    inverse = getattr(tt, "inverse_target_prediction", None)
    if callable(fit) and callable(transform) and callable(inverse):
        _C06_CACHE = {"fit": fit, "transform": transform, "inverse": inverse}
        return _C06_CACHE
    _C06_CACHE = False
    return None


def _load_assess_normative() -> Optional[Callable]:
    global _C03_CACHE
    if _C03_CACHE is not None:
        return None if _C03_CACHE is False else _C03_CACHE
    try:
        from . import nbr14653_validation as nbr
    except ImportError:
        try:
            import modules.nbr14653_validation as nbr  # type: ignore
        except ImportError:
            _C03_CACHE = False
            return None
    fn = getattr(nbr, "assess_normative", None)
    if callable(fn):
        _C03_CACHE = fn
        return fn
    _C03_CACHE = False
    return None


def _load_transform_subject() -> Optional[Callable]:
    global _C02_CACHE
    if _C02_CACHE is not None:
        return None if _C02_CACHE is False else _C02_CACHE
    try:
        from . import preprocessing as prep
    except ImportError:
        try:
            import modules.preprocessing as prep  # type: ignore
        except ImportError:
            _C02_CACHE = False
            return None
    fn = getattr(prep, "transform_subject", None)
    if callable(fn):
        _C02_CACHE = fn
        return fn
    _C02_CACHE = False
    return None


def _transform_name(value: Any) -> Optional[str]:
    """C05 may emit {name: ...}; MP/1 y_transformation is a name string."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("name") or value.get("transformation")
        if value is None:
            return None
    text = str(value).strip()
    return text or None


class _DataclassMapping(MappingABC):
    def __getitem__(self, key: str) -> Any:
        fields = getattr(self, "__dataclass_fields__", {})
        if key not in fields:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self):
        return iter(getattr(self, "__dataclass_fields__", {}))

    def __len__(self) -> int:
        return len(getattr(self, "__dataclass_fields__", {}))


@dataclass
class CandidateSpec(_DataclassMapping):
    candidate_id: str
    features: List[str]
    base_variables: List[str]
    feature_groups: Dict[str, List[str]]
    x_transformations: Dict[str, str]
    y_transformation: Optional[str]
    intercept: bool = True

    @classmethod
    def from_obj(cls, obj: Any) -> "CandidateSpec":
        if isinstance(obj, cls):
            return obj
        data = _as_mapping(obj)
        features = [str(x) for x in (data.get("features") or [])]
        base = data.get("base_variables")
        x_raw = data.get("x_transformations") or {}
        x_transformations = {}
        for key, value in x_raw.items():
            name = _transform_name(value)
            if name is not None:
                x_transformations[str(key)] = name
        return cls(
            candidate_id=str(data.get("candidate_id") or "candidate"),
            features=features,
            base_variables=[str(x) for x in (base if base is not None else features)],
            feature_groups={
                str(k): [str(c) for c in v]
                for k, v in (data.get("feature_groups") or {}).items()
            },
            x_transformations=x_transformations,
            y_transformation=_transform_name(data.get("y_transformation")),
            intercept=bool(data.get("intercept", True)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "features": list(self.features),
            "base_variables": list(self.base_variables),
            "feature_groups": {k: list(v) for k, v in self.feature_groups.items()},
            "x_transformations": dict(self.x_transformations),
            "y_transformation": self.y_transformation,
            "intercept": bool(self.intercept),
        }


@dataclass
class CandidateFit(_DataclassMapping):
    candidate_id: str
    status: str
    candidate_spec: CandidateSpec
    model_object: Any
    coefficients: Dict[str, float]
    feature_schema: Dict[str, Any]
    encoder_state: Dict[str, Any]
    used_row_ids: List[Any]
    excluded_row_ids: List[Any]
    base_frame: Any
    diagnostics: Dict[str, Any]
    target_transform_state: Any
    model_sha256: str
    issues: List[Dict[str, Any]]
    coefficient_records: List[Dict[str, Any]] = field(default_factory=list)
    sample_policy: Dict[str, Any] = field(default_factory=dict)
    X_design: Any = field(default=None, repr=False)
    y_design: Any = field(default=None, repr=False)

    def to_serializable(self) -> Dict[str, Any]:
        """JSON-safe metadata. Omits model_object / frames."""
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "candidate_spec": self.candidate_spec.to_dict(),
            "coefficients": dict(self.coefficients),
            "coefficient_records": list(self.coefficient_records),
            "feature_schema": copy.deepcopy(self.feature_schema),
            "encoder_state": copy.deepcopy(self.encoder_state),
            "used_row_ids": list(self.used_row_ids),
            "excluded_row_ids": list(self.excluded_row_ids),
            "diagnostics": copy.deepcopy(self.diagnostics),
            "target_transform_state": copy.deepcopy(self.target_transform_state),
            "model_sha256": self.model_sha256,
            "issues": copy.deepcopy(self.issues),
            "sample_policy": copy.deepcopy(self.sample_policy),
        }


def _empty_value() -> Dict[str, Any]:
    return {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }


def _pending_normative(issues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "edition": None,
        "rule_sources": [],
        "verification_status": "pending",
        "fundamentacao": {"grade": None, "points": None, "items": []},
        "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
        "documentary": {},
        "issues": list(issues or []),
    }


@dataclass
class CandidateAssessment(_DataclassMapping):
    candidate_id: str
    subject_id: str
    subject_raw: Dict[str, Any]
    value: Dict[str, Any]
    normative: Dict[str, Any]
    statistical: Dict[str, Any]
    model_eligibility: Dict[str, Any]
    used_row_ids: List[Any]
    issues: List[Dict[str, Any]]
    excluded_row_ids: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "subject_id": self.subject_id,
            "subject_raw": dict(self.subject_raw or {}),
            "value": copy.deepcopy(self.value),
            "normative": copy.deepcopy(self.normative),
            "statistical": copy.deepcopy(self.statistical),
            "model_eligibility": copy.deepcopy(self.model_eligibility),
            "used_row_ids": list(self.used_row_ids),
            "excluded_row_ids": list(self.excluded_row_ids),
            "issues": copy.deepcopy(self.issues),
        }


def _default_feature_schema(features: Sequence[str], target_name: str) -> Dict[str, Any]:
    columns = {}
    for name in features:
        columns[str(name)] = {
            "original_name": str(name),
            "role": "predictor",
            "kind": "numeric",
            "unit": None,
            "group_id": None,
            "categories": None,
            "reference_category": None,
        }
    return {
        "version": 1,
        "columns": columns,
        "groups": {},
        "target": {"column": target_name, "unit": None},
    }


def _align_prepared(prepared: Any) -> Tuple[pd.DataFrame, pd.Series, List[Any], List[Any], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    X_raw = _get(prepared, "X")
    y_raw = _get(prepared, "y")
    if X_raw is None or y_raw is None:
        raise ValueError("PreparedDataset requires X and y")
    X = pd.DataFrame(X_raw).copy()
    y = pd.Series(y_raw).copy()
    if len(X) != len(y):
        raise ValueError(f"X/y length mismatch: {len(X)} vs {len(y)}")
    original_index = list(X.index)
    duplicated_index = [ _as_id(i) for i, flag in zip(original_index, pd.Index(original_index).duplicated(keep=False)) if flag ]
    if duplicated_index:
        issues.append(
            make_issue(
                "duplicate_index_labels",
                "O índice do DataFrame de treino contém rótulos duplicados; a identidade estável é row_id.",
                severity="warning",
                affected_ids=sorted(set(duplicated_index), key=str),
                evidence={"duplicate_label_count": len(set(duplicated_index))},
            )
        )
    row_ids = _get(prepared, "row_ids")
    if row_ids is None:
        row_ids = [ _as_id(i) for i in original_index ]
    else:
        row_ids = [ _as_id(i) for i in list(row_ids) ]
    if len(row_ids) != len(X):
        raise ValueError(f"row_ids length mismatch: {len(row_ids)} vs {len(X)}")
    X = X.reset_index(drop=True)
    y = pd.Series(np.asarray(y), index=X.index, name=getattr(y, "name", None) or "y")
    return X, y, row_ids, original_index, issues


def _constant_columns(frame: pd.DataFrame) -> List[str]:
    found: List[str] = []
    for col in frame.columns:
        values = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            continue
        if np.allclose(finite, finite[0], equal_nan=False):
            found.append(str(col))
    return found


def _apply_named_transform(series: pd.Series, name: str) -> Tuple[pd.Series, List[int]]:
    if _is_identity_y(name):
        numeric = pd.to_numeric(series, errors="coerce")
        invalid = [int(i) for i, value in enumerate(numeric.to_numpy(dtype=float)) if not np.isfinite(value)]
        return numeric.astype(float), invalid
    out = np.full(len(series), np.nan, dtype=float)
    invalid: List[int] = []
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    for i, value in enumerate(values):
        probe = pd.Series([value], dtype=float)
        transformed, ok = Transformer.apply_transformation(probe, name)
        if (not ok) or (not np.isfinite(float(transformed.iloc[0]))):
            invalid.append(i)
        else:
            out[i] = float(transformed.iloc[0])
    return pd.Series(out, index=series.index), invalid


def _design_rank(arr: np.ndarray) -> Tuple[int, Optional[str]]:
    try:
        if arr.ndim != 2:
            return 0, "invalid_shape"
        if arr.size == 0:
            return 0, None
        if not np.isfinite(arr).all():
            return 0, "non_finite_design"
        return int(np.linalg.matrix_rank(np.asarray(arr, dtype=float))), None
    except np.linalg.LinAlgError as exc:
        return 0, f"rank_numerical_failure:{exc}"


def _dummy_group_issues(
    design: pd.DataFrame,
    feature_groups: Mapping[str, Sequence[str]],
    intercept: bool,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for group_id, columns in (feature_groups or {}).items():
        present = [c for c in columns if c in design.columns]
        if len(present) < 2:
            continue
        sub = np.asarray(design[present].to_numpy(dtype=float))
        if not np.isfinite(sub).all():
            continue
        rank = int(np.linalg.matrix_rank(sub))
        row_sums = sub.sum(axis=1)
        sums_constant = bool(np.allclose(row_sums, row_sums[0]))
        if rank < len(present) or (intercept and sums_constant):
            issues.append(
                make_issue(
                    "collinear_dummy_group",
                    "Grupo de indicadores colinear (armadilha de dummies ou categorias linearmente dependentes).",
                    severity="error",
                    evidence={
                        "group_id": group_id,
                        "columns": present,
                        "rank": rank,
                        "n_columns": len(present),
                        "row_sum_constant": sums_constant,
                        "intercept": intercept,
                    },
                )
            )
    return issues


def _influence_diagnostics(model: Any, used_row_ids: Sequence[Any], n: int, p: int) -> Dict[str, Any]:
    empty = {
        "cooks_distance": {},
        "studentized_residuals": {},
        "leverage": {},
        "influential_row_ids": [],
        "high_leverage_row_ids": [],
        "thresholds": {},
        "influence_authorizes_exclusion": False,
    }
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            influence = model.get_influence()
            cooks = np.asarray(influence.cooks_distance[0], dtype=float)
            resid = np.asarray(influence.resid_studentized_internal, dtype=float)
            hat = np.asarray(influence.hat_matrix_diag, dtype=float)
    except Exception as exc:
        empty["error"] = str(exc)
        return empty
    cooks_cut_4n = 4.0 / max(n, 1)
    cooks_cut_abs = float(getattr(config, "MAX_COOK_DISTANCE", 1.0))
    resid_cut = 2.5
    leverage_cut = 2.0 * max(p, 1) / max(n, 1)
    influential: List[Any] = []
    high_leverage: List[Any] = []
    cooks_map: Dict[str, float] = {}
    resid_map: Dict[str, float] = {}
    hat_map: Dict[str, float] = {}
    for i, row_id in enumerate(used_row_ids):
        cook_i = _finite(cooks[i]) if i < len(cooks) else None
        resid_i = _finite(resid[i]) if i < len(resid) else None
        hat_i = _finite(hat[i]) if i < len(hat) else None
        key = str(row_id)
        if cook_i is not None:
            cooks_map[key] = cook_i
        if resid_i is not None:
            resid_map[key] = resid_i
        if hat_i is not None:
            hat_map[key] = hat_i
        flagged = False
        if cook_i is not None and (cook_i > cooks_cut_4n or cook_i > cooks_cut_abs):
            flagged = True
        if resid_i is not None and abs(resid_i) > resid_cut:
            flagged = True
        if hat_i is not None and hat_i > leverage_cut:
            high_leverage.append(_as_id(row_id))
            flagged = True
        if flagged:
            influential.append(_as_id(row_id))
    return {
        "cooks_distance": cooks_map,
        "studentized_residuals": resid_map,
        "leverage": hat_map,
        "influential_row_ids": influential,
        "high_leverage_row_ids": high_leverage,
        "thresholds": {
            "cooks_4_over_n": cooks_cut_4n,
            "cooks_absolute": cooks_cut_abs,
            "studentized_abs": resid_cut,
            "leverage_2p_over_n": leverage_cut,
        },
        "influence_authorizes_exclusion": False,
        **influence_does_not_authorize_exclusion(),
    }


def _coefficient_records(model: Any) -> Tuple[Dict[str, float], List[Dict[str, Any]], bool]:
    params = model.params
    bse = model.bse
    pvalues = model.pvalues
    tvalues = model.tvalues
    coefs: Dict[str, float] = {}
    records: List[Dict[str, Any]] = []
    all_finite = True
    for name in params.index:
        value = _finite(params[name])
        if value is None:
            all_finite = False
            continue
        coefs[str(name)] = value
        records.append(
            {
                "name": str(name),
                "value": value,
                "std_error": _finite(bse[name]),
                "tvalue": _finite(tvalues[name]),
                "pvalue": _finite(pvalues[name]),
            }
        )
    return coefs, records, all_finite


def _cancelled_fit(spec: CandidateSpec, prepared: Any, issues: List[Dict[str, Any]]) -> CandidateFit:
    issues = list(issues) + [
        make_issue("cancelled", "Ajuste cancelado em ponto seguro.", severity="error")
    ]
    schema = copy.deepcopy(_get(prepared, "feature_schema") or {})
    encoder = copy.deepcopy(_get(prepared, "encoder_state") or {})
    return CandidateFit(
        candidate_id=spec.candidate_id,
        status=STATUS_ERROR,
        candidate_spec=spec,
        model_object=None,
        coefficients={},
        feature_schema=schema,
        encoder_state=encoder,
        used_row_ids=[],
        excluded_row_ids=[],
        base_frame=None,
        diagnostics={"cancelled": True},
        target_transform_state=None,
        model_sha256=_sha256_payload({"status": STATUS_ERROR, "reason": "cancelled", "spec": spec.to_dict()}),
        issues=issues,
    )


def _fit_shell(
    spec: CandidateSpec,
    *,
    status: str,
    issues: List[Dict[str, Any]],
    prepared: Any,
    used_row_ids: Optional[Sequence[Any]] = None,
    excluded_row_ids: Optional[Sequence[Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
    encoder_state: Optional[Dict[str, Any]] = None,
    feature_schema: Optional[Dict[str, Any]] = None,
    target_transform_state: Any = None,
    sample_policy: Optional[Dict[str, Any]] = None,
    base_frame: Any = None,
) -> CandidateFit:
    schema = copy.deepcopy(feature_schema if feature_schema is not None else (_get(prepared, "feature_schema") or {}))
    encoder = copy.deepcopy(encoder_state if encoder_state is not None else (_get(prepared, "encoder_state") or {}))
    diag = dict(diagnostics or {})
    payload = {
        "status": status,
        "spec": spec.to_dict(),
        "used_row_ids": list(used_row_ids or []),
        "excluded_row_ids": list(excluded_row_ids or []),
        "diagnostics": {k: diag[k] for k in ("n", "k", "rank", "parameters_free", "singular", "rank_deficient") if k in diag},
        "issues": [i.get("code") for i in issues],
    }
    return CandidateFit(
        candidate_id=spec.candidate_id,
        status=status,
        candidate_spec=spec,
        model_object=None,
        coefficients={},
        feature_schema=schema,
        encoder_state=encoder,
        used_row_ids=list(used_row_ids or []),
        excluded_row_ids=list(excluded_row_ids or []),
        base_frame=base_frame,
        diagnostics=diag,
        target_transform_state=copy.deepcopy(target_transform_state),
        model_sha256=_sha256_payload(payload),
        issues=list(issues),
        sample_policy=dict(sample_policy or {}),
    )


def _slice_base_frame(prepared: Any, X: pd.DataFrame, used_positions: Sequence[int], used_row_ids: Sequence[Any]) -> pd.DataFrame:
    base = _get(prepared, "base_frame")
    if base is None:
        frame = X.iloc[list(used_positions)].copy()
    else:
        frame = pd.DataFrame(base).copy()
        if len(frame) == len(X):
            frame = frame.reset_index(drop=True).iloc[list(used_positions)].copy()
        else:
            frame = frame.copy()
    frame = frame.reset_index(drop=True)
    frame.index = list(used_row_ids)
    return frame


def fit_candidate(
    prepared_dataset: Any,
    candidate_spec: Any,
    request_spec: Any = None,
    progress_callback: Optional[Callable] = None,
    cancel_requested: Optional[Callable] = None,
) -> CandidateFit:
    """Fit one OLS candidate on a prepared sample. Does not evaluate a subject."""
    spec = CandidateSpec.from_obj(candidate_spec)
    issues: List[Dict[str, Any]] = []
    _progress(progress_callback, "fit_candidate:start", 0.0)
    if _cancelled(cancel_requested):
        return _cancelled_fit(spec, prepared_dataset, issues)

    try:
        X_all, y_all, row_ids, original_index, align_issues = _align_prepared(prepared_dataset)
    except Exception as exc:
        issues.append(
            make_issue(
                "invalid_prepared_dataset",
                f"PreparedDataset inválido: {exc}",
                severity="error",
                evidence={"type": type(exc).__name__},
            )
        )
        return _fit_shell(spec, status=STATUS_ERROR, issues=issues, prepared=prepared_dataset)

    issues.extend(align_issues)
    if len(set(row_ids)) != len(row_ids):
        return _fit_shell(
            spec,
            status=STATUS_REJECTED,
            issues=issues + [
                make_issue(
                    "duplicate_row_ids",
                    "row_id duplicado impede identidade estável da amostra.",
                    severity="error",
                    affected_ids=sorted({r for r in row_ids if row_ids.count(r) > 1}, key=str),
                )
            ],
            prepared=prepared_dataset,
            diagnostics={"duplicate_index_labels": [ _as_id(i) for i in original_index ]},
        )

    missing_features = [name for name in spec.features if name not in X_all.columns]
    if missing_features:
        issues.append(
            make_issue(
                "missing_features",
                "Variáveis do candidato ausentes no PreparedDataset.X.",
                severity="error",
                evidence={"missing": missing_features},
            )
        )
        return _fit_shell(spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset)

    if not spec.features:
        issues.append(
            make_issue(
                "empty_features",
                "CandidateSpec.features vazio: nenhuma variável autorizada (nunca 'todas').",
                severity="error",
            )
        )
        return _fit_shell(spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset)

    X_sel = X_all.loc[:, spec.features].copy()
    candidate_invalid: List[ExclusionRecord] = []

    for base_name, trans_name in (spec.x_transformations or {}).items():
        if base_name not in X_sel.columns:
            continue
        transformed, invalid_pos = _apply_named_transform(X_sel[base_name], trans_name)
        X_sel[base_name] = transformed
        for pos in invalid_pos:
            candidate_invalid.append(
                ExclusionRecord(
                    row_id=row_ids[pos],
                    reason=f"domínio inválido para transformação X '{trans_name}' em '{base_name}'",
                    origin=ORIGIN_TRANSFORM_DOMAIN,
                    rule=f"x_transform:{trans_name}",
                    evidence={"column": base_name, "transformation": trans_name, "position": pos},
                )
            )

    for col in spec.features:
        values = pd.to_numeric(X_sel[col], errors="coerce").to_numpy(dtype=float)
        for pos, value in enumerate(values):
            if not np.isfinite(value):
                candidate_invalid.append(
                    ExclusionRecord(
                        row_id=row_ids[pos],
                        reason=f"valor não finito em '{col}' após preparação",
                        origin=ORIGIN_TRANSFORM_DOMAIN,
                        rule="non_finite_feature",
                        evidence={"column": col, "position": pos},
                    )
                )

    y_numeric = pd.to_numeric(y_all, errors="coerce")
    for pos, value in enumerate(y_numeric.to_numpy(dtype=float)):
        if not np.isfinite(value):
            candidate_invalid.append(
                ExclusionRecord(
                    row_id=row_ids[pos],
                    reason="alvo não finito; alvo ausente nunca é imputado",
                    origin=ORIGIN_PRE_FIT_INPUT_ERROR,
                    rule="non_finite_target",
                    evidence={"position": pos},
                )
            )

    decision = resolve_sample(row_ids, request_spec, candidate_invalid=[r.to_dict() for r in candidate_invalid])
    issues.extend(decision.issues)
    used_ids = list(decision.used_row_ids)
    excluded_ids = list(decision.excluded_row_ids)
    id_to_pos = {rid: i for i, rid in enumerate(row_ids)}
    used_pos = [id_to_pos[rid] for rid in used_ids if rid in id_to_pos]

    _progress(progress_callback, "fit_candidate:sample", 0.2)
    if _cancelled(cancel_requested):
        return _cancelled_fit(spec, prepared_dataset, issues)

    encoder_state = copy.deepcopy(_get(prepared_dataset, "encoder_state") or {})
    feature_schema = copy.deepcopy(_get(prepared_dataset, "feature_schema") or {})
    if not feature_schema:
        feature_schema = _default_feature_schema(spec.features, str(y_all.name or "y"))

    y_name = spec.y_transformation
    y_name_c06 = _c06_y_name(y_name)
    target_state = None
    y_work = y_numeric.copy()
    if not _is_identity_y(y_name):
        c06 = _load_c06()
        if c06 is None:
            issues.append(
                make_issue(
                    "c06_not_available",
                    "Transformação do alvo exige C06 (fit_target_transform); par não publicado.",
                    severity="error",
                    evidence={"y_transformation": y_name, "c06_name": y_name_c06, "unmet_dependency": "C06"},
                )
            )
            return _fit_shell(
                spec,
                status=STATUS_ERROR,
                issues=issues,
                prepared=prepared_dataset,
                used_row_ids=used_ids,
                excluded_row_ids=excluded_ids,
                encoder_state=encoder_state,
                feature_schema=feature_schema,
                sample_policy=decision.to_dict(),
            )
        try:
            y_train = y_work.iloc[used_pos]
            target_state = c06["fit"](y_train, y_name_c06, None)
            y_transformed = c06["transform"](y_work, target_state)
            y_work = pd.Series(np.asarray(y_transformed, dtype=float), index=y_work.index)
        except Exception as exc:
            issues.append(
                make_issue(
                    "c06_transform_failed",
                    f"C06 falhou ao transformar o alvo: {exc}",
                    severity="error",
                    evidence={"type": type(exc).__name__, "y_transformation": y_name},
                )
            )
            return _fit_shell(
                spec,
                status=STATUS_ERROR,
                issues=issues,
                prepared=prepared_dataset,
                used_row_ids=used_ids,
                excluded_row_ids=excluded_ids,
                encoder_state=encoder_state,
                feature_schema=feature_schema,
                sample_policy=decision.to_dict(),
            )
        extra_invalid = [
            used_ids[j]
            for j, value in enumerate(y_work.iloc[used_pos].to_numpy(dtype=float))
            if not np.isfinite(value)
        ]
        if extra_invalid:
            drop = set(extra_invalid)
            used_ids = [rid for rid in used_ids if rid not in drop]
            excluded_ids = excluded_ids + [rid for rid in extra_invalid if rid not in excluded_ids]
            used_pos = [id_to_pos[rid] for rid in used_ids]
            decision.r2_naive_comparison_blocked = True
            if COMPARISON_BLOCK_DIVERGENT_SAMPLE not in decision.comparison_block_reasons:
                decision.comparison_block_reasons.append(COMPARISON_BLOCK_DIVERGENT_SAMPLE)
            issues.append(
                make_issue(
                    "y_transform_non_finite",
                    "Transformação do alvo produziu valores não finitos em linhas usadas.",
                    severity="warning",
                    affected_ids=extra_invalid,
                )
            )

    n = len(used_pos)
    X_used = X_sel.iloc[used_pos].copy().reset_index(drop=True)
    y_used = pd.Series(y_work.iloc[used_pos].to_numpy(dtype=float), name=str(y_all.name or "y"))

    diagnostics: Dict[str, Any] = {
        "n_prepared": int(len(row_ids)),
        "n": int(n),
        "duplicate_index_labels": sorted({ _as_id(i) for i, flag in zip(original_index, pd.Index(original_index).duplicated(keep=False)) if flag }, key=str),
        "duplicate_index_count": int(pd.Index(original_index).duplicated().sum()),
        "constant_columns_in_features": _constant_columns(X_used),
        "intercept_requested": bool(spec.intercept),
        "intercept_added": False,
        "constant_already_present": False,
        "constant_counted_twice": False,
        "rank_deficient": False,
        "singular": False,
        "significance_invalid": False,
        "pinv_used": False,
        "fit_method": "qr",
        "hypotheses": {
            "linearity": "assumed",
            "exogeneity": "assumed",
            "spherical_errors": "assumed",
            "full_rank": "checked",
            "normality_for_inference": "diagnostic_only",
        },
        "transformations": {
            "x": dict(spec.x_transformations),
            "y": y_name if not _is_identity_y(y_name) else "identity",
        },
        "influence": {"influence_authorizes_exclusion": False, "influential_row_ids": []},
        "r2_naive_comparison_blocked": bool(decision.r2_naive_comparison_blocked),
        "comparison_block_reasons": list(decision.comparison_block_reasons),
        "scenario": decision.scenario,
        "policy_mode": decision.policy_mode,
        "exclusions": [e.to_dict() for e in decision.exclusions],
        "numerical_failure": False,
        "not_enquadramento": True,
    }

    if n == 0:
        issues.append(
            make_issue(
                "insufficient_n",
                "n=0 após preparação/exclusões documentadas.",
                severity="error",
                evidence={"n": 0, "n_prepared": len(row_ids)},
            )
        )
        diagnostics["rank"] = 0
        diagnostics["k"] = 0
        diagnostics["parameters_free"] = 0
        return _fit_shell(
            spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
        )

    constants_before = _constant_columns(X_used)
    intercept_col = None
    has_intercept = False
    if spec.intercept:
        if constants_before:
            diagnostics["constant_already_present"] = True
            intercept_col = constants_before[0]
            has_intercept = True
            issues.append(
                make_issue(
                    "constant_already_present",
                    "Coluna constante já presente; intercepto extra não foi adicionado (constante não contada duas vezes).",
                    severity="warning",
                    evidence={"constant_columns": constants_before},
                )
            )
            X_design = X_used.copy()
        else:
            X_design = sm.add_constant(X_used, has_constant="add", prepend=True)
            intercept_col = "const" if "const" in X_design.columns else str(X_design.columns[0])
            diagnostics["intercept_added"] = True
            has_intercept = True
    else:
        X_design = X_used.copy()
        has_intercept = False
        issues.append(
            make_issue(
                "no_intercept",
                "CandidateSpec.intercept=False: intercepto não adicionado.",
                severity="info",
                evidence={"constant_columns": constants_before},
            )
        )
        if constants_before:
            issues.append(
                make_issue(
                    "constant_present_without_intercept",
                    "Há coluna constante no desenho com intercept=False.",
                    severity="warning",
                    evidence={"constant_columns": constants_before},
                )
            )

    if spec.intercept and len(_constant_columns(X_design)) > 1:
        diagnostics["constant_counted_twice"] = True
        issues.append(
            make_issue(
                "duplicate_constant_columns",
                "Mais de uma coluna constante no desenho; k/intercepto ambíguos.",
                severity="error",
                evidence={"constant_columns": _constant_columns(X_design)},
            )
        )

    issues.extend(_dummy_group_issues(X_design, spec.feature_groups, has_intercept or spec.intercept))

    arr = np.asarray(X_design.to_numpy(dtype=float))
    n_cols = int(arr.shape[1]) if arr.ndim == 2 else 0
    rank, rank_error = _design_rank(arr)
    k_regressors = n_cols - (1 if has_intercept else 0)
    if k_regressors < 0:
        k_regressors = 0
    diagnostics.update(
        {
            "n": int(n),
            "k": int(k_regressors),
            "n_design_columns": int(n_cols),
            "rank": int(rank),
            "parameters_free": int(rank),
            "has_intercept": bool(has_intercept),
            "intercept_column": intercept_col,
            "design_columns": [str(c) for c in X_design.columns],
        }
    )

    if rank_error == "non_finite_design":
        issues.append(
            make_issue(
                "non_finite_design",
                "Matriz de desenho contém valores não finitos após preparação.",
                severity="error",
                evidence={"n": n, "n_columns": n_cols},
            )
        )
        diagnostics["numerical_failure"] = True
        return _fit_shell(
            spec, status=STATUS_ERROR, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
        )
    if rank_error and rank_error.startswith("rank_numerical_failure"):
        issues.append(
            make_issue(
                "numerical_failure",
                "Falha numérica ao calcular o posto da matriz de desenho (distinta de não enquadramento).",
                severity="error",
                evidence={"detail": rank_error},
            )
        )
        diagnostics["numerical_failure"] = True
        return _fit_shell(
            spec, status=STATUS_ERROR, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
        )

    if n <= n_cols or n <= rank:
        issues.append(
            make_issue(
                "insufficient_n",
                "n insuficiente após preparação para estimar o modelo (n <= número de colunas/posto).",
                severity="error",
                evidence={"n": n, "n_columns": n_cols, "rank": rank, "k": k_regressors},
            )
        )
        diagnostics["significance_invalid"] = True
        return _fit_shell(
            spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
            base_frame=_slice_base_frame(prepared_dataset, X_all, used_pos, used_ids),
        )

    if rank < n_cols:
        diagnostics["rank_deficient"] = True
        diagnostics["singular"] = True
        diagnostics["pinv_used"] = False
        issues.append(
            make_issue(
                "rank_deficient",
                "Matriz de desenho com deficiência de posto / singular. Pseudoinversa não é usada para esconder o posto.",
                severity="error",
                evidence={"n": n, "n_columns": n_cols, "rank": rank, "parameters_free": rank},
            )
        )
        return _fit_shell(
            spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
            base_frame=_slice_base_frame(prepared_dataset, X_all, used_pos, used_ids),
        )

    _progress(progress_callback, "fit_candidate:design", 0.4)
    if _cancelled(cancel_requested):
        return _cancelled_fit(spec, prepared_dataset, issues)

    try:
        ols = sm.OLS(y_used, X_design, hasconst=has_intercept)
        model = ols.fit(method="qr", use_t=True)
    except Exception as exc:
        issues.append(
            make_issue(
                "numerical_failure",
                f"Falha numérica no OLS (QR), distinta de não enquadramento normativo: {exc}",
                severity="error",
                evidence={"type": type(exc).__name__},
            )
        )
        diagnostics["numerical_failure"] = True
        return _fit_shell(
            spec, status=STATUS_ERROR, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
        )

    coefs, records, coefs_finite = _coefficient_records(model)
    if not coefs_finite or not coefs:
        issues.append(
            make_issue(
                "numerical_failure",
                "Coeficientes não finitos após o ajuste.",
                severity="error",
            )
        )
        diagnostics["numerical_failure"] = True
        return _fit_shell(
            spec, status=STATUS_ERROR, issues=issues, prepared=prepared_dataset,
            used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
            encoder_state=encoder_state, feature_schema=feature_schema,
            target_transform_state=target_state, sample_policy=decision.to_dict(),
        )

    df_resid = _finite(getattr(model, "df_resid", None))
    f_pvalue = _finite(getattr(model, "f_pvalue", None))
    if df_resid is None or df_resid <= 0 or f_pvalue is None:
        diagnostics["significance_invalid"] = True
        issues.append(
            make_issue(
                "significance_invalid",
                "Inferência (p-valores / teste F) inválida para este desenho.",
                severity="warning",
                evidence={"df_resid": df_resid, "f_pvalue": f_pvalue},
            )
        )

    p_design = n_cols
    influence = _influence_diagnostics(model, used_ids, n, p_design)
    diagnostics["influence"] = influence
    if influence.get("influential_row_ids"):
        issues.append(
            make_issue(
                "influence_reported",
                "Observações influentes relatadas para investigação; mantidas na análise principal.",
                severity="info",
                affected_ids=influence.get("influential_row_ids") or [],
                evidence={
                    "thresholds": influence.get("thresholds"),
                    "high_leverage_row_ids": influence.get("high_leverage_row_ids"),
                },
            )
        )

    try:
        diagnostics["r2"] = _finite(model.rsquared)
        diagnostics["r2_adjusted"] = _finite(model.rsquared_adj)
        diagnostics["f_pvalue"] = f_pvalue
        diagnostics["f_statistic"] = _finite(getattr(model, "fvalue", None))
        diagnostics["df_resid"] = df_resid
        diagnostics["df_model"] = _finite(getattr(model, "df_model", None))
        diagnostics["condition_number"] = _finite(getattr(model, "condition_number", None))
        diagnostics["aic"] = _finite(getattr(model, "aic", None))
        diagnostics["bic"] = _finite(getattr(model, "bic", None))
    except Exception:
        pass

    cond = diagnostics.get("condition_number")
    if cond is not None:
        try:
            cond_f = float(cond)
        except (TypeError, ValueError):
            cond_f = None
        if cond_f is None or not np.isfinite(cond_f) or abs(cond_f) > 1e12:
            issues.append(
                make_issue(
                    "ill_conditioned",
                    "Matriz de desenho numericamente mal-condicionada; o ajuste não é aceito como fitted.",
                    severity="error",
                    evidence={"condition_number": cond},
                )
            )
            diagnostics["ill_conditioned"] = True
            return _fit_shell(
                spec, status=STATUS_REJECTED, issues=issues, prepared=prepared_dataset,
                used_row_ids=used_ids, excluded_row_ids=excluded_ids, diagnostics=diagnostics,
                encoder_state=encoder_state, feature_schema=feature_schema,
                target_transform_state=target_state, sample_policy=decision.to_dict(),
                base_frame=_slice_base_frame(prepared_dataset, X_all, used_pos, used_ids),
            )

    base_frame = _slice_base_frame(prepared_dataset, X_all, used_pos, used_ids)
    sha = _sha256_payload(
        {
            "spec": spec.to_dict(),
            "used_row_ids": used_ids,
            "excluded_row_ids": excluded_ids,
            "coefficients": {k: format(v, ".17g") for k, v in coefs.items()},
            "rank": rank,
            "n": n,
            "k": k_regressors,
            "parameters_free": rank,
        }
    )
    _progress(progress_callback, "fit_candidate:done", 1.0)
    return CandidateFit(
        candidate_id=spec.candidate_id,
        status=STATUS_FITTED,
        candidate_spec=spec,
        model_object=model,
        coefficients=coefs,
        feature_schema=feature_schema,
        encoder_state=encoder_state,
        used_row_ids=list(used_ids),
        excluded_row_ids=list(excluded_ids),
        base_frame=base_frame,
        diagnostics=diagnostics,
        target_transform_state=copy.deepcopy(target_state),
        model_sha256=sha,
        issues=issues,
        coefficient_records=records,
        sample_policy=decision.to_dict(),
        X_design=X_design,
        y_design=y_used,
    )


def _interval_dict(lower: Optional[float], upper: Optional[float], **extra: Any) -> Optional[Dict[str, Any]]:
    if lower is None or upper is None:
        return None
    payload = {"lower": lower, "upper": upper}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _scalar_point(raw: Any) -> Optional[float]:
    value = _finite(raw)
    if value is not None:
        return value
    if isinstance(raw, Mapping):
        for key in ("point", "value", "mean"):
            if key in raw:
                found = _scalar_point(raw[key])
                if found is not None:
                    return found
        return None
    try:
        arr = np.asarray(raw, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if arr.size == 1:
        return _finite(arr[0])
    return None


def _normalize_inverse(result: Any) -> Dict[str, Any]:
    out = {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "estimand": None,
        "limitations": [],
        "interval_method_validated": None,
        "precisao_status": None,
    }
    if result is None:
        out["limitations"] = ["inverse_returned_none"]
        return out
    if isinstance(result, Mapping):
        value_block = result.get("value") if isinstance(result.get("value"), Mapping) else {}
        out["point"] = _scalar_point(value_block.get("point"))
        if out["point"] is None:
            out["point"] = _scalar_point(result.get("point"))
        mean_ci = value_block.get("mean_ci80")
        if mean_ci is None:
            mean_ci = result.get("mean_ci80")
        # C06 may return a retransformed interval that is explicitly not mean_ci80.
        interprets = None
        retrans = result.get("retransformed_interval")
        if isinstance(retrans, Mapping):
            interprets = retrans.get("interprets") or retrans.get("not")
        if isinstance(mean_ci, Mapping):
            out["mean_ci80"] = _interval_dict(_finite(mean_ci.get("lower")), _finite(mean_ci.get("upper")))
        pi = value_block.get("prediction_interval")
        if pi is None:
            pi = result.get("prediction_interval")
        if isinstance(pi, Mapping):
            out["prediction_interval"] = _interval_dict(
                _finite(pi.get("lower")), _finite(pi.get("upper")), level=pi.get("level"), kind=pi.get("kind")
            )
        out["estimand"] = result.get("estimand") or value_block.get("estimand")
        out["limitations"] = list(result.get("limitations") or [])
        precisao = result.get("precisao") if isinstance(result.get("precisao"), Mapping) else {}
        out["precisao_status"] = precisao.get("status")
        if "interval_method_validated" in result:
            out["interval_method_validated"] = bool(result.get("interval_method_validated"))
        else:
            interp = result.get("interval_interpretation")
            if interp == "mean_ci80" and out["mean_ci80"] is not None:
                out["interval_method_validated"] = True
            elif interprets == "mean_ci80":
                out["interval_method_validated"] = out["mean_ci80"] is not None
            elif precisao.get("status") == "not_computed":
                out["interval_method_validated"] = False
            elif out["mean_ci80"] is None:
                out["interval_method_validated"] = False
        return out
    if isinstance(result, (tuple, list)) and result:
        out["point"] = _scalar_point(result[0])
        if len(result) > 1 and isinstance(result[1], Mapping):
            meta = result[1]
            out["estimand"] = meta.get("estimand")
            out["limitations"] = list(meta.get("limitations") or [])
            out["interval_method_validated"] = meta.get("interval_method_validated")
            if isinstance(meta.get("mean_ci80"), Mapping):
                mc = meta["mean_ci80"]
                out["mean_ci80"] = _interval_dict(_finite(mc.get("lower")), _finite(mc.get("upper")))
        return out
    out["point"] = _scalar_point(result)
    return out


def _build_subject_row(
    candidate_fit: CandidateFit,
    subject_design: Any,
) -> Tuple[Optional[pd.DataFrame], List[Dict[str, Any]], bool, Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    raw = _get(subject_design, "raw_values")
    if raw is None:
        raw = _get(subject_design, "subject_raw") or {}
    raw = dict(raw or {})
    supported = _get(subject_design, "supported", True)
    X_subj = _get(subject_design, "X")
    spec = candidate_fit.candidate_spec
    if X_subj is None:
        row = {}
        missing = []
        for name in spec.features:
            if name in raw:
                row[name] = raw[name]
            else:
                missing.append(name)
        if missing:
            issues.append(
                make_issue(
                    "subject_features_missing",
                    "Avaliando sem valores para todas as features do candidato.",
                    severity="error",
                    evidence={"missing": missing},
                )
            )
            return None, issues, False, raw
        X_subj = pd.DataFrame([row])
    X_subj = pd.DataFrame(X_subj).copy()
    if X_subj.shape[0] < 1:
        return None, issues + [make_issue("empty_subject", "SubjectDesign.X vazio.", severity="error")], False, raw

    for base_name, trans_name in (spec.x_transformations or {}).items():
        if base_name in X_subj.columns and not _is_identity_y(trans_name):
            series, invalid = _apply_named_transform(X_subj[base_name], trans_name)
            if invalid:
                issues.append(
                    make_issue(
                        "subject_transform_invalid",
                        f"Transformação '{trans_name}' inválida no avaliando para '{base_name}'.",
                        severity="error",
                        evidence={"column": base_name, "transformation": trans_name},
                    )
                )
                return None, issues, False, raw
            X_subj[base_name] = series

    design_columns = (candidate_fit.diagnostics or {}).get("design_columns")
    if not design_columns and candidate_fit.model_object is not None:
        design_columns = list(candidate_fit.model_object.model.exog_names)
    if not design_columns:
        design_columns = (["const"] if spec.intercept else []) + list(spec.features)

    intercept_col = (candidate_fit.diagnostics or {}).get("intercept_column")
    has_intercept = bool((candidate_fit.diagnostics or {}).get("has_intercept"))
    row_values: Dict[str, float] = {}
    for col in design_columns:
        if has_intercept and (col == intercept_col or col == "const"):
            if col in X_subj.columns:
                val = _finite(X_subj[col].iloc[0])
                row_values[col] = 1.0 if val is None else val
            else:
                row_values[col] = 1.0
            continue
        if col not in X_subj.columns:
            issues.append(
                make_issue(
                    "subject_column_missing",
                    f"Coluna de desenho '{col}' ausente no avaliando.",
                    severity="error",
                )
            )
            return None, issues, False, raw
        val = _finite(X_subj[col].iloc[0])
        if val is None:
            issues.append(
                make_issue(
                    "subject_non_finite",
                    f"Valor não finito no avaliando para '{col}'.",
                    severity="error",
                )
            )
            return None, issues, False, raw
        row_values[col] = val
    frame = pd.DataFrame([row_values], columns=list(design_columns))
    return frame, issues, bool(supported), raw


def _predict_on_design(model: Any, X_row: pd.DataFrame, level: float) -> Dict[str, Any]:
    prediction = model.get_prediction(X_row)
    alpha = 1.0 - float(level)
    summary = prediction.summary_frame(alpha=alpha)
    mean = _finite(summary["mean"].iloc[0])
    mean_lo = _finite(summary["mean_ci_lower"].iloc[0]) if "mean_ci_lower" in summary.columns else None
    mean_hi = _finite(summary["mean_ci_upper"].iloc[0]) if "mean_ci_upper" in summary.columns else None
    obs_lo = _finite(summary["obs_ci_lower"].iloc[0]) if "obs_ci_lower" in summary.columns else None
    obs_hi = _finite(summary["obs_ci_upper"].iloc[0]) if "obs_ci_upper" in summary.columns else None
    return {
        "point": mean,
        "mean_ci80": _interval_dict(mean_lo, mean_hi, level=level, kind="mean"),
        "prediction_interval": _interval_dict(obs_lo, obs_hi, level=level, kind="observation"),
        "computed_mean_ci": mean_lo is not None and mean_hi is not None,
        "computed_prediction_interval": obs_lo is not None and obs_hi is not None,
    }


def _axes_from_effective_sample(candidate_fit: CandidateFit, subject_raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Item-4 axes from the fitted effective sample, not the raw prepared frame."""
    axes: List[Dict[str, Any]] = []
    frame = candidate_fit.base_frame
    if frame is None:
        return axes
    try:
        base = pd.DataFrame(frame)
    except Exception:
        return axes
    raw = dict(subject_raw or {})
    names = list(candidate_fit.candidate_spec.base_variables or candidate_fit.candidate_spec.features)
    seen = set()
    for name in names:
        if name in seen or name not in base.columns:
            continue
        seen.add(name)
        series = pd.to_numeric(base[name], errors="coerce")
        finite = series[np.isfinite(series.to_numpy(dtype=float))]
        if finite.empty:
            continue
        axes.append(
            {
                "variable": name,
                "name": name,
                "kind": "quantitative",
                "avaliando_value": raw.get(name),
                "sample_min": float(finite.min()),
                "sample_max": float(finite.max()),
                "n": int(finite.shape[0]),
            }
        )
    return axes


def _make_predict_original(candidate_fit: CandidateFit, request_spec: Any) -> Callable:
    def predict_original(subject_raw: Any) -> Dict[str, Any]:
        raw = dict(subject_raw or {})
        transform_subject = _load_transform_subject()
        encoder = candidate_fit.encoder_state or {}
        c02_ready = isinstance(encoder, Mapping) and bool(encoder.get("base_variables"))
        design = None
        if transform_subject is not None and c02_ready:
            try:
                design = transform_subject(raw, candidate_fit.feature_schema, encoder)
            except Exception as exc:
                design = {
                    "X": None,
                    "raw_values": raw,
                    "supported": True,
                    "issues": [make_issue("c02_transform_subject_failed", str(exc), severity="warning")],
                }
        if design is None:
            design = {"X": None, "raw_values": raw, "supported": True, "issues": []}
        X_row, issues, supported, _ = _build_subject_row(candidate_fit, design if _get(design, "raw_values") is not None else {"X": _get(design, "X"), "raw_values": raw, "supported": True})
        if X_row is None or candidate_fit.model_object is None or not supported:
            return {"point": None, "issues": issues, "supported": False}
        try:
            pred = _predict_on_design(candidate_fit.model_object, X_row, MEAN_CI_LEVEL)
        except Exception as exc:
            return {"point": None, "issues": [make_issue("prediction_failed", str(exc), severity="error")]}
        value = _apply_inverse(pred, candidate_fit)
        return {"point": value["point"], "mean_ci80": value["mean_ci80"], "prediction_interval": value["prediction_interval"], "issues": issues, "supported": True}

    return predict_original


def _apply_inverse(pred: Mapping[str, Any], candidate_fit: CandidateFit) -> Dict[str, Any]:
    value = _empty_value()
    limitations: List[str] = []
    state = candidate_fit.target_transform_state
    y_name = candidate_fit.candidate_spec.y_transformation
    if state is None or _is_identity_y(y_name):
        value["point"] = pred.get("point")
        value["mean_ci80"] = pred.get("mean_ci80") if pred.get("computed_mean_ci") else None
        value["prediction_interval"] = pred.get("prediction_interval") if pred.get("computed_prediction_interval") else None
        value["_estimand"] = "conditional_mean"
        value["_limitations"] = []
        value["_interval_method_validated"] = True
        return value
    c06 = _load_c06()
    if c06 is None:
        limitations.append("c06_inverse_not_available")
        value["point"] = None
        value["_estimand"] = "conditional_mean_transformed_unit"
        value["_limitations"] = limitations
        value["_interval_method_validated"] = False
        return value
    payload = {
        "point": pred.get("point"),
        "mean_ci80": pred.get("mean_ci80"),
        "prediction_interval": pred.get("prediction_interval"),
    }
    residual_context = {
        "df_resid": (candidate_fit.diagnostics or {}).get("df_resid"),
        "used_row_ids": list(candidate_fit.used_row_ids),
    }
    try:
        inverted = c06["inverse"](payload, state, residual_context)
    except TypeError:
        inverted = c06["inverse"](payload, state)
    except Exception as exc:
        value["point"] = None
        value["_limitations"] = [f"inverse_failed:{exc}"]
        value["_interval_method_validated"] = False
        return value
    norm = _normalize_inverse(inverted)
    validated = norm["interval_method_validated"]
    if validated is None:
        validated = not bool(norm["limitations"]) and norm["mean_ci80"] is not None
    value["point"] = norm["point"]
    if validated:
        value["mean_ci80"] = norm["mean_ci80"]
        value["prediction_interval"] = norm["prediction_interval"]
    else:
        value["mean_ci80"] = None
        value["prediction_interval"] = None
        if not norm["limitations"]:
            limitations.append("interval_inverse_not_validated")
    value["_estimand"] = norm["estimand"] or "conditional_mean_original_unit"
    value["_limitations"] = list(norm["limitations"]) + limitations
    value["_interval_method_validated"] = bool(validated)
    return value


def _call_assess_normative(context: Dict[str, Any]) -> Dict[str, Any]:
    fn = _load_assess_normative()
    if fn is None:
        return _pending_normative(
            [
                make_issue(
                    "c03_not_available",
                    "assess_normative (C03) não publicado; o builder não interpreta Tabela 1/2/5.",
                    severity="warning",
                    evidence={"unmet_dependency": "C03"},
                )
            ]
        )
    result = fn(context)
    if isinstance(result, Mapping):
        return dict(result)
    if hasattr(result, "__dict__"):
        data = {k: getattr(result, k) for k in ("edition", "rule_sources", "verification_status", "fundamentacao", "precisao", "documentary", "issues") if hasattr(result, k)}
        if data:
            return data
    return _pending_normative(
        [make_issue("c03_unrecognized_return", "assess_normative retornou formato não reconhecido.", severity="warning")]
    )


def evaluate_fitted(
    candidate_fit: Any,
    subject_design: Any,
    request_spec: Any = None,
    progress_callback: Optional[Callable] = None,
    cancel_requested: Optional[Callable] = None,
) -> CandidateAssessment:
    """Evaluate one subject with a frozen fit. Does not refit or drop rows."""
    if not isinstance(candidate_fit, CandidateFit):
        raise TypeError("evaluate_fitted exige CandidateFit de fit_candidate")

    encoder_before = copy.deepcopy(candidate_fit.encoder_state)
    coefs_before = dict(candidate_fit.coefficients)
    used_before = list(candidate_fit.used_row_ids)
    excluded_before = list(candidate_fit.excluded_row_ids)

    issues: List[Dict[str, Any]] = []
    subject_id = str(_get(subject_design, "subject_id") or _get(request_spec, "subject_id") or "subject")
    _progress(progress_callback, "evaluate_fitted:start", 0.0)
    if _cancelled(cancel_requested):
        issues.append(make_issue("cancelled", "Avaliação cancelada em ponto seguro.", severity="error"))
        return CandidateAssessment(
            candidate_id=candidate_fit.candidate_id,
            subject_id=subject_id,
            subject_raw=dict(_get(subject_design, "raw_values") or _get(subject_design, "subject_raw") or {}),
            value=_empty_value(),
            normative=_pending_normative(issues),
            statistical={"cancelled": True},
            model_eligibility={"status": "error", "reasons": ["cancelled"]},
            used_row_ids=list(used_before),
            issues=issues,
            excluded_row_ids=list(excluded_before),
        )

    if candidate_fit.status != STATUS_FITTED or candidate_fit.model_object is None:
        issues.append(
            make_issue(
                "fit_not_usable",
                "CandidateFit não está fitted; avaliação não reajusta nem reescolhe amostra.",
                severity="error",
                evidence={"status": candidate_fit.status},
            )
        )
        eligibility = {"status": "error", "reasons": [candidate_fit.status or "not_fitted"]}
        return CandidateAssessment(
            candidate_id=candidate_fit.candidate_id,
            subject_id=subject_id,
            subject_raw=dict(_get(subject_design, "raw_values") or {}),
            value=_empty_value(),
            normative=_pending_normative(),
            statistical={"n": (candidate_fit.diagnostics or {}).get("n"), "k": (candidate_fit.diagnostics or {}).get("k")},
            model_eligibility=eligibility,
            used_row_ids=list(used_before),
            issues=issues + list(candidate_fit.issues or []),
            excluded_row_ids=list(excluded_before),
        )

    X_row, row_issues, supported, raw = _build_subject_row(candidate_fit, subject_design)
    issues.extend(row_issues)
    if X_row is None or not supported:
        eligibility = {"status": "unsupported", "reasons": [i.get("code") for i in row_issues] or ["subject_unsupported"]}
        return CandidateAssessment(
            candidate_id=candidate_fit.candidate_id,
            subject_id=subject_id,
            subject_raw=raw,
            value=_empty_value(),
            normative=_pending_normative(),
            statistical={
                "n": (candidate_fit.diagnostics or {}).get("n"),
                "k": (candidate_fit.diagnostics or {}).get("k"),
                "rank": (candidate_fit.diagnostics or {}).get("rank"),
            },
            model_eligibility=eligibility,
            used_row_ids=list(used_before),
            issues=issues,
            excluded_row_ids=list(excluded_before),
        )

    try:
        pred = _predict_on_design(candidate_fit.model_object, X_row, MEAN_CI_LEVEL)
    except Exception as exc:
        issues.append(
            make_issue(
                "prediction_failed",
                f"Falha ao predizer o avaliando: {exc}",
                severity="error",
                evidence={"type": type(exc).__name__},
            )
        )
        return CandidateAssessment(
            candidate_id=candidate_fit.candidate_id,
            subject_id=subject_id,
            subject_raw=raw,
            value=_empty_value(),
            normative=_pending_normative(),
            statistical={},
            model_eligibility={"status": "error", "reasons": ["prediction_failed"]},
            used_row_ids=list(used_before),
            issues=issues,
            excluded_row_ids=list(excluded_before),
        )

    value = _apply_inverse(pred, candidate_fit)
    limitations = list(value.pop("_limitations", []) or [])
    estimand = value.pop("_estimand", "conditional_mean")
    interval_validated = bool(value.pop("_interval_method_validated", True))
    if value["point"] is None:
        issues.append(
            make_issue(
                "point_not_computed",
                "Ponto estimado não pôde ser calculado; nenhum zero substituto.",
                severity="error",
                evidence={"limitations": limitations},
            )
        )
    if pred.get("computed_mean_ci") and value["mean_ci80"] is None and not interval_validated:
        issues.append(
            make_issue(
                "mean_ci_not_validated_on_original_unit",
                "IC da média não reportado na unidade original: inversa/intervalo sem método validado.",
                severity="warning",
                evidence={"limitations": limitations},
            )
        )
    if pred.get("computed_prediction_interval") is False:
        issues.append(
            make_issue(
                "prediction_interval_not_computed",
                "Intervalo preditivo não calculado.",
                severity="info",
            )
        )
    if value["mean_ci80"] is None and _is_identity_y(candidate_fit.candidate_spec.y_transformation):
        issues.append(
            make_issue(
                "mean_ci80_not_computed",
                "IC da média (80%) não calculado.",
                severity="warning",
            )
        )
    for item in limitations:
        issues.append(
            make_issue(
                "target_transform_limitation",
                str(item),
                severity="warning",
                evidence={"y_transformation": candidate_fit.candidate_spec.y_transformation},
            )
        )

    _progress(progress_callback, "evaluate_fitted:predicted", 0.5)
    if _cancelled(cancel_requested):
        issues.append(make_issue("cancelled", "Avaliação cancelada após predição local; fit congelado intacto.", severity="error"))
        assert candidate_fit.encoder_state == encoder_before
        assert candidate_fit.coefficients == coefs_before
        return CandidateAssessment(
            candidate_id=candidate_fit.candidate_id,
            subject_id=subject_id,
            subject_raw=raw,
            value=_empty_value(),
            normative=_pending_normative(issues),
            statistical={"cancelled": True},
            model_eligibility={"status": "error", "reasons": ["cancelled"]},
            used_row_ids=list(used_before),
            issues=issues,
            excluded_row_ids=list(excluded_before),
        )

    predict_original = _make_predict_original(candidate_fit, request_spec)
    n = (candidate_fit.diagnostics or {}).get("n")
    k = (candidate_fit.diagnostics or {}).get("k")
    axes = _axes_from_effective_sample(candidate_fit, raw)
    amplitude_pct = None
    if interval_validated and value.get("point") and value.get("mean_ci80"):
        point = value["point"]
        width = abs(value["mean_ci80"]["upper"] - value["mean_ci80"]["lower"])
        if point not in (0, None) and np.isfinite(point):
            amplitude_pct = width / abs(point) * 100.0
    context = {
        "schema_version": SCHEMA_VERSION,
        "effective_sample": {
            "used_row_ids": list(used_before),
            "excluded_row_ids": list(excluded_before),
            "n": n,
            "k": k,
            "base_frame": candidate_fit.base_frame,
        },
        "sample": {"used": list(used_before), "n": n, "k": k},
        "n": n,
        "k": k,
        "intercept": (candidate_fit.diagnostics or {}).get("has_intercept"),
        "diagnostics": copy.deepcopy(candidate_fit.diagnostics),
        "pvalues": {rec["name"]: rec.get("pvalue") for rec in candidate_fit.coefficient_records},
        "f_pvalue": (candidate_fit.diagnostics or {}).get("f_pvalue"),
        "value": {key: copy.deepcopy(value[key]) for key in _empty_value()},
        "mean_ci80": copy.deepcopy(value.get("mean_ci80")),
        "prediction_interval": copy.deepcopy(value.get("prediction_interval")),
        "central_estimate": value.get("point"),
        "amplitude_pct": amplitude_pct,
        "axes": axes,
        "extrapolation_details": axes,
        "predict_original": predict_original,
        "documentary": _get(request_spec, "documentary") or {},
        "request_spec": request_spec,
        "subject_raw": raw,
        "subject_design": subject_design,
        "candidate_spec": candidate_fit.candidate_spec.to_dict(),
        "limitations": limitations,
        "interval_method_validated": interval_validated,
        "used_row_ids": list(used_before),
        "statistical": {
            "r2": (candidate_fit.diagnostics or {}).get("r2"),
            "r2_adjusted": (candidate_fit.diagnostics or {}).get("r2_adjusted"),
            "automatic_selection": False,
        },
        "estimand": estimand,
    }
    normative = _call_assess_normative(context)
    if not interval_validated:
        precisao = dict(normative.get("precisao") or {})
        if precisao.get("status") in (None, "classified"):
            precisao["status"] = "not_computed"
            precisao["grade"] = None
            normative["precisao"] = precisao
            issues.append(
                make_issue(
                    "precisao_not_declared",
                    "Precisão normativa não declarada: inversa/intervalo do alvo sem método validado.",
                    severity="warning",
                )
            )

    if value["point"] is None:
        eligibility_status = "error"
        reasons = ["point_not_computed"]
    else:
        eligibility_status = "eligible"
        reasons = []
        if (candidate_fit.diagnostics or {}).get("influence", {}).get("influential_row_ids"):
            reasons.append("influence_reported_not_excluded")
        if not interval_validated:
            eligibility_status = "review_required"
            reasons.append("target_transform_limitations")
        if (normative.get("verification_status") == "pending"):
            if eligibility_status == "eligible":
                eligibility_status = "review_required"
            reasons.append("normative_pending")

    statistical = {
        "n": n,
        "k": k,
        "rank": (candidate_fit.diagnostics or {}).get("rank"),
        "parameters_free": (candidate_fit.diagnostics or {}).get("parameters_free"),
        "r2": (candidate_fit.diagnostics or {}).get("r2"),
        "r2_adjusted": (candidate_fit.diagnostics or {}).get("r2_adjusted"),
        "f_pvalue": (candidate_fit.diagnostics or {}).get("f_pvalue"),
        "significance_invalid": (candidate_fit.diagnostics or {}).get("significance_invalid"),
        "estimand": estimand,
        "interval_method_validated": interval_validated,
        "mean_ci_computed": bool(value["mean_ci80"]),
        "prediction_interval_computed": bool(value["prediction_interval"]),
        "influence": copy.deepcopy((candidate_fit.diagnostics or {}).get("influence") or {}),
        "r2_naive_comparison_blocked": (candidate_fit.diagnostics or {}).get("r2_naive_comparison_blocked"),
        "scenario": (candidate_fit.diagnostics or {}).get("scenario"),
    }

    if candidate_fit.encoder_state != encoder_before or candidate_fit.coefficients != coefs_before or list(candidate_fit.used_row_ids) != used_before:
        issues.append(
            make_issue(
                "frozen_fit_mutated",
                "evaluate_fitted não deve mutar coeficientes, encoder ou amostra.",
                severity="error",
            )
        )
        candidate_fit.encoder_state = encoder_before
        candidate_fit.coefficients = coefs_before
        candidate_fit.used_row_ids = used_before

    _progress(progress_callback, "evaluate_fitted:done", 1.0)
    return CandidateAssessment(
        candidate_id=candidate_fit.candidate_id,
        subject_id=subject_id,
        subject_raw=raw,
        value={k: value[k] for k in _empty_value()},
        normative=normative,
        statistical=statistical,
        model_eligibility={"status": eligibility_status, "reasons": reasons},
        used_row_ids=list(used_before),
        issues=issues,
        excluded_row_ids=list(excluded_before),
    )


class ModelBuilder:
    def __init__(self):
        pass

    def _calculate_metrics(self, model, X, y) -> ModelMetrics:
        try:
            _, normality_p = stats.shapiro(model.resid)
        except Exception:
            normality_p = 0.0
        try:
            _, homoscedasticity_p, _, _ = het_breuschpagan(model.resid, X)
        except Exception:
            homoscedasticity_p = 0.0
        dw = durbin_watson(model.resid)
        return ModelMetrics(
            r2=model.rsquared,
            r2_adjusted=model.rsquared_adj,
            f_statistic=model.fvalue,
            f_pvalue=model.f_pvalue,
            std_error=np.sqrt(model.mse_resid),
            aic=model.aic,
            bic=model.bic,
            condition_number=model.condition_number,
            normality_pvalue=normality_p,
            homoscedasticity_pvalue=homoscedasticity_p,
            autocorrelation_durbin_watson=dw,
        )

    def _get_formula(self, model) -> str:
        try:
            params = model.params
            formula = f"y = {params['const']:.4f}"
            for col in params.index:
                if col != "const":
                    sign = "+" if params[col] >= 0 else "-"
                    formula += f" {sign} {abs(params[col]):.4f}*{col}"
            return formula
        except Exception:
            return "Formula generation failed"

    def detect_outliers(self, model) -> List[int]:
        """Identify influential points (Cook / studentized residuals).

        The returned indices are investigation candidates, not authorization
        to drop a valid observation from the principal sample.
        """
        outliers = set()
        try:
            influence = model.get_influence()
            cooks_d, _ = influence.cooks_distance
            n = len(model.resid)
            cooks_threshold = config.MAX_COOK_DISTANCE if hasattr(config, "MAX_COOK_DISTANCE") else 1.0
            std_resid = influence.resid_studentized_internal
            resid_threshold = 2.5
            for i in range(n):
                if cooks_d[i] > cooks_threshold:
                    outliers.add(model.resid.index[i])
                elif abs(std_resid[i]) > resid_threshold:
                    outliers.add(model.resid.index[i])
            return list(outliers)
        except Exception as e:
            logger.error(f"Error detecting outliers: {str(e)}")
            return []

    def build_model(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        degree: int = 1,
        remove_outliers: bool = False,
        grau_item1: Optional[int] = None,
        grau_item3: Optional[int] = None,
        item1_provenance: Any = None,
        item3_provenance: Any = None,
    ) -> ModelResult:
        """Legacy adapter around fit_candidate.

        ``remove_outliers=True`` no longer silently drops rows. Influence is
        reported on the validation warnings. Documented exclusions belong on
        the MP/1 ``fit_candidate`` path (``outlier_policy``).
        """
        try:
            X_df = pd.DataFrame(X)
            y_s = pd.Series(y)
            prepared = {
                "X": X_df,
                "y": y_s,
                "row_ids": [ _as_id(i) for i in X_df.index ],
                "feature_schema": _default_feature_schema(list(X_df.columns), str(getattr(y_s, "name", None) or "y")),
                "encoder_state": {},
                "base_frame": X_df,
                "issues": [],
            }
            spec = CandidateSpec(
                candidate_id="legacy_build_model",
                features=[str(c) for c in X_df.columns],
                base_variables=[str(c) for c in X_df.columns],
                feature_groups={},
                x_transformations={},
                y_transformation="identity",
                intercept=True,
            )
            request_spec = {
                "schema_version": SCHEMA_VERSION,
                "outlier_policy": {"mode": "report_only", "scenario": "principal"},
                "legacy_remove_outliers_flag": bool(remove_outliers),
            }
            fit = fit_candidate(prepared, spec, request_spec)
            if fit.status != STATUS_FITTED or fit.model_object is None:
                codes = [i.get("code") for i in fit.issues]
                return ModelResult(
                    success=False,
                    message=f"Error building model: {codes}",
                    error="; ".join(i.get("message", "") for i in fit.issues),
                )

            model = fit.model_object
            X_design = fit.X_design if fit.X_design is not None else sm.add_constant(X_df, has_constant="skip")
            y_used = fit.y_design if fit.y_design is not None else y_s
            metrics = self._calculate_metrics(model, X_design, y_used)
            vif = {}
            for i, col in enumerate(X_design.columns):
                try:
                    vif[col] = variance_inflation_factor(X_design.values, i)
                except Exception:
                    vif[col] = float("inf")

            # Documented exclusions only — never Cook/residual drops.
            outliers_removed: List = []
            result = ModelResult(
                success=True,
                model_metrics=metrics,
                coefficients=dict(fit.coefficients),
                pvalues={rec["name"]: rec.get("pvalue") for rec in fit.coefficient_records},
                vif=vif,
                residuals=list(model.resid),
                fitted_values=list(model.fittedvalues),
                formula=self._get_formula(model),
                outliers_removed=outliers_removed,
                model_object=model,
            )
            result.validation_result = NBRValidator.validate_model(
                result,
                X_design,
                y_used,
                degree,
                grau_item1=grau_item1,
                grau_item3=grau_item3,
                item1_provenance=item1_provenance,
                item3_provenance=item3_provenance,
            )
            setattr(result, "_c04_candidate_fit", fit)
            setattr(result, "_c04_used_row_ids", list(fit.used_row_ids))
            influential = (fit.diagnostics or {}).get("influence", {}).get("influential_row_ids") or []
            if remove_outliers:
                result.validation_result.warnings.append(
                    "remove_outliers=True não exclui observações em silêncio. "
                    "Pontos influentes são relatados para investigação; exclusão exige "
                    "revisão documentada (id, motivo, autor/origem) ou regra pré-ajuste com evidência."
                )
            if influential:
                result.validation_result.warnings.append(
                    "Observações influentes mantidas na análise principal "
                    f"(investigação, não retirada): {influential}"
                )
            return result
        except Exception as e:
            logger.error(f"Error building model: {str(e)}")
            return ModelResult(success=False, message=f"Error building model: {str(e)}", error=str(e))

    def add_precision_and_extrapolation(
        self,
        model_result: ModelResult,
        avaliando_raw: Dict[str, float],
        original_df: pd.DataFrame,
        degree: Optional[int] = None,
    ) -> ModelResult:
        """Legacy adapter: numbers from the effective sample, interpretation by C03."""
        try:
            if not model_result.validation_result:
                logger.error("add_precision_and_extrapolation: model_result has no validation_result.")
                return model_result

            if degree is None:
                degree = model_result.validation_result.target_degree
                if degree is None:
                    degree = 1

            columns = [col for col in model_result.coefficients.keys() if col != "const"]
            fit = getattr(model_result, "_c04_candidate_fit", None)
            used_ids = getattr(model_result, "_c04_used_row_ids", None)
            effective_df = original_df
            if used_ids:
                matched = [idx for idx in used_ids if idx in original_df.index]
                if matched:
                    effective_df = original_df.loc[matched]
            elif model_result.outliers_removed:
                matched_outliers = [idx for idx in model_result.outliers_removed if idx in original_df.index]
                if not matched_outliers:
                    logger.warning(
                        "add_precision_and_extrapolation: model_result.outliers_removed is "
                        "non-empty but none of its indices are present in original_df. "
                        "sample_min/sample_max will silently fall back to the full "
                        "original_df, which may re-introduce outliers into item 4's "
                        "extrapolation range. This usually means original_df's index does "
                        "not align with the index used in build_model()."
                    )
                effective_df = original_df.drop(index=matched_outliers)

            row_values = {"const": 1.0}
            extrapolation_details = []
            seen_bases = set()

            for col in columns:
                if "(" in col and col.endswith(")"):
                    func_name = col[: col.index("(")]
                    base = col[col.index("(") + 1 : -1]
                else:
                    func_name = "linear"
                    base = col

                if base not in avaliando_raw:
                    raise KeyError(
                        f"Valor do avaliando não informado para a variável base '{base}' (coluna '{col}')."
                    )

                raw_value = avaliando_raw[base]
                transformed_series, ok = Transformer.apply_transformation(pd.Series([raw_value]), func_name)
                if not ok:
                    raise ValueError(
                        f"Falha ao aplicar transformação '{func_name}' ao valor do avaliando para '{base}'."
                    )
                row_values[col] = transformed_series.iloc[0]

                if base not in seen_bases:
                    seen_bases.add(base)
                    if base not in original_df.columns:
                        raise KeyError(f"Variável base '{base}' não encontrada no DataFrame original.")
                    extrapolation_details.append(
                        {
                            "variable": base,
                            "avaliando_value": raw_value,
                            "sample_min": float(effective_df[base].min()),
                            "sample_max": float(effective_df[base].max()),
                        }
                    )

            ordered_columns = list(model_result.coefficients.keys())
            avaliando_df = pd.DataFrame([row_values], columns=ordered_columns)
            prediction = model_result.model_object.get_prediction(avaliando_df)
            summary = prediction.summary_frame(alpha=1 - config.CONFIDENCE_LEVEL_PRECISION)
            mean = summary["mean"].iloc[0]
            ci_lower = summary["mean_ci_lower"].iloc[0]
            ci_upper = summary["mean_ci_upper"].iloc[0]
            amplitude_pct = abs(ci_upper - ci_lower) / abs(mean) * 100 if mean != 0 else float("inf")

            def predict_original(subject_next):
                raw = dict(subject_next or {})
                row = {"const": 1.0}
                for col_name in columns:
                    if "(" in col_name and col_name.endswith(")"):
                        func_name = col_name[: col_name.index("(")]
                        base = col_name[col_name.index("(") + 1 : -1]
                    else:
                        func_name = "linear"
                        base = col_name
                    series, ok = Transformer.apply_transformation(pd.Series([raw.get(base)]), func_name)
                    if not ok:
                        return None
                    row[col_name] = series.iloc[0]
                frame = pd.DataFrame([row], columns=ordered_columns)
                pred = model_result.model_object.get_prediction(frame)
                return float(pred.summary_frame().iloc[0]["mean"])

            model_result.validation_result = NBRValidator.finalize_precision_and_extrapolation(
                model_result.validation_result,
                amplitude_pct,
                extrapolation_details,
                degree,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
                central_estimate=mean,
                predict_original=predict_original,
                subject_raw=avaliando_raw,
            )
            for detail in extrapolation_details:
                sample_min = detail.get("sample_min")
                sample_max = detail.get("sample_max")
                aval = detail.get("avaliando_value")
                if sample_min is None or sample_max is None or aval is None:
                    continue
                if aval < sample_min or aval > sample_max:
                    frontier = sample_max if aval > sample_max else sample_min
                    clamped = {k: v for k, v in avaliando_raw.items() if k != detail["variable"]}
                    clamped[detail["variable"]] = frontier
                    y_front = predict_original(clamped)
                    y_sub = predict_original(avaliando_raw)
                    if y_front is not None and y_sub is not None and y_front != 0:
                        efeito = abs(y_sub - y_front) / abs(y_front)
                        model_result.validation_result.details["efeito_monetario"] = efeito
                        model_result.validation_result.warnings.append(
                            f"efeito_monetario={efeito:.4f} price_outside_sample predicted={y_sub}"
                        )
            if fit is not None:
                influential = (fit.diagnostics or {}).get("influence", {}).get("influential_row_ids") or []
                if influential:
                    model_result.validation_result.warnings.append(
                        "Item 4 usa a amostra efetiva da análise principal, incluindo "
                        f"pontos influentes não excluídos: {influential}"
                    )
            return model_result
        except Exception as e:
            logger.exception(f"Error in add_precision_and_extrapolation: {str(e)}")
            if model_result.validation_result:
                model_result.validation_result.warnings.append(
                    f"Não foi possível calcular grau de precisão / item 4 (extrapolação) "
                    f"para este candidato: {type(e).__name__}: {str(e)}"
                )
            return model_result
