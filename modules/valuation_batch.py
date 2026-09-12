"""C14: batch valuation and controlled reuse of a frozen model.

Public seam:
    evaluate_batch(frozen_project, subjects, request_spec,
                   progress_callback=None, cancel_requested=None) -> BatchResult

A FrozenProject already holds a fitted specification. This module applies it
to many subjects without a new search or a new fit. Selection that was
conditioned on one subject (model_scope=subject_specific) is never treated as
a silent population model. Domain misses and unknown categories fail only the
affected item. Fit/matrices are reused only when the complete reuse key
matches; filename, row count or target column alone are not a key.

Peer campaigns C02/C03/C04/C06 are consumed by name when published. When they
are absent, a frozen-application fallback in this file evaluates the stored
coefficients and encoder_state. That fallback is not a substitute fitter.
C11, if present, is used as the only persistence coordinator; this module
does not open a second database and does not unpickle user objects.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import threading
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from modules.pro_workflow.residual_state import (
    CALCULATION_VERSION,
    LIMITATION_INCOMPLETE,
    LIMITATION_MALFORMED,
    LIMITATION_NO_INTERVALS,
    STATUS_INCOMPLETE,
    STATUS_MALFORMED,
    apply_mean_prediction_intervals,
    declared_residual_status,
    extract_residual_state,
    json_safe_residual_state,
    residual_state_is_complete,
)

SCHEMA_VERSION = "MP/1"
MODEL_SCOPE_SUBJECT_SPECIFIC = "subject_specific"
MODEL_SCOPE_POPULATION = "population_model"
VALID_MODEL_SCOPES = frozenset({MODEL_SCOPE_SUBJECT_SPECIFIC, MODEL_SCOPE_POPULATION})

ELIGIBLE = "eligible"
REVIEW_REQUIRED = "review_required"
UNSUPPORTED = "unsupported"
ERROR = "error"
VALID_ELIGIBILITY = frozenset({ELIGIBLE, REVIEW_REQUIRED, UNSUPPORTED, ERROR})

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"
STATUS_CANCELLED = "cancelled"
STATUS_UNSUPPORTED = "unsupported"

COMPLETED_STATUSES = frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_UNSUPPORTED})
BATCH_STATES = frozenset({"running", "succeeded", "failed", "cancelled", "interrupted"})

REASON_REQUIRES_INDIVIDUAL = "requires_individual_analysis"
REASON_OUT_OF_DOMAIN = "out_of_domain"
REASON_SUBJECT_SPECIFIC = "subject_specific_model_not_reusable"
REASON_UNKNOWN_CATEGORY = "unknown_category"
REASON_MISSING_DOMAIN = "population_model_missing_domain"
REASON_POLICY_MISMATCH = "request_spec_mismatch"

DEFAULT_MAX_WORKERS = 1
MAX_WORKERS_CAP = 8
# Historical constant kept as a named leftover so tests can prove we do NOT
# apply it as a statistical interval. C05 supplies arbitration when present.
ARBITRATION_FRACTION = 0.15
MEAN_CI_LEVEL = 0.80

_FROZEN_REQUIRED = (
    "schema_version",
    "project_id",
    "revision_id",
    "input_sha256",
    "dataset_sha256",
    "request_spec",
    "feature_schema",
    "encoder_state",
    "model_spec",
    "model_state",
    "model_scope",
    "subject_constraints",
    "domain",
    "sample_ledger",
    "normative_version",
    "artifact_refs",
    "provenance",
)

# Reuse identity is the conjunction of these — never filename / n_rows / target
# column in isolation.
_REUSE_KEY_FIELDS = (
    "input_sha256",
    "dataset_sha256",
    "sample_identity",
    "feature_schema",
    "encoder_state",
    "model_spec",
    "model_sha256",
    "target",
    "policies",
    "normative_version",
    "model_scope",
    "subject_constraints",
)


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

def _as_mapping(obj: Any, what: str = "value") -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise TypeError(f"{what} must be a mapping, got {type(obj).__name__}")


def _as_list(obj: Any) -> List[Any]:
    if obj is None:
        return []
    if isinstance(obj, list):
        return list(obj)
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]


def _issue(
    code: str,
    severity: str,
    origin: str,
    message: str,
    affected_ids: Optional[Sequence[Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": str(code),
        "severity": str(severity),
        "origin": str(origin),
        "message": str(message),
        "affected_ids": [str(x) for x in (affected_ids or [])],
        "evidence": dict(evidence or {}),
    }


def _finite_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, int) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return float(obj)
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "tolist"):
        try:
            return _json_safe(obj.tolist())
        except Exception:
            return str(obj)
    return str(obj)


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(_json_safe(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_value() -> Dict[str, Any]:
    """ResultSnapshot.value shape. Failure is nulls, never a substitute zero."""
    return {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }


def _interval(lower: Optional[float], upper: Optional[float], extra: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    lo = _finite_or_none(lower)
    hi = _finite_or_none(upper)
    if lo is None or hi is None:
        return None
    payload = {"lower": lo, "upper": hi}
    if extra:
        payload.update(dict(extra))
    return payload


def _empty_normative() -> Dict[str, Any]:
    return {
        "edition": None,
        "rule_sources": [],
        "verification_status": "pending",
        "fundamentacao": {"grade": None, "points": None, "items": []},
        "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
        "documentary": {"items": [], "origin": "subject"},
        "issues": [],
    }


def _empty_eligibility(status: str, reasons: Sequence[str]) -> Dict[str, Any]:
    if status not in VALID_ELIGIBILITY:
        status = ERROR
    return {"status": status, "reasons": [str(r) for r in reasons]}


# ---------------------------------------------------------------------------
# FrozenProject validation and reuse key
# ---------------------------------------------------------------------------

def validate_frozen_project(frozen_project: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    frozen = _as_mapping(frozen_project, "frozen_project")
    missing = [key for key in _FROZEN_REQUIRED if key not in frozen]
    if missing:
        issues.append(
            _issue(
                "frozen_project_incomplete",
                "error",
                "c14.validate_frozen_project",
                "FrozenProject ausente de campos obrigatórios.",
                evidence={"missing": missing},
            )
        )
    schema = frozen.get("schema_version")
    if schema not in (None, SCHEMA_VERSION):
        issues.append(
            _issue(
                "frozen_schema_version",
                "warning",
                "c14.validate_frozen_project",
                f"schema_version {schema!r} difere de {SCHEMA_VERSION}.",
                evidence={"schema_version": schema},
            )
        )
    scope = frozen.get("model_scope")
    if scope not in VALID_MODEL_SCOPES:
        issues.append(
            _issue(
                "invalid_model_scope",
                "error",
                "c14.validate_frozen_project",
                "model_scope deve ser subject_specific ou population_model.",
                evidence={"model_scope": scope},
            )
        )
    # candidate_fit is in-memory only after validated restore; never required.
    return frozen, issues


def _sample_identity(sample_ledger: Mapping[str, Any]) -> Dict[str, Any]:
    ledger = _as_mapping(sample_ledger, "sample_ledger")
    used = sorted(str(x) for x in _as_list(ledger.get("used_row_ids")))
    excluded = sorted(str(x) for x in _as_list(ledger.get("excluded_row_ids")))
    reasons = _as_mapping(ledger.get("exclusion_reasons"), "exclusion_reasons")
    return {
        "used_row_ids": used,
        "excluded_row_ids": excluded,
        "exclusion_reasons": {str(k): reasons[k] for k in sorted(reasons, key=str)},
        "reviewed_exclusions": sorted(str(x) for x in _as_list(ledger.get("reviewed_exclusions"))),
    }


def _policy_slice(request_spec: Mapping[str, Any]) -> Dict[str, Any]:
    spec = _as_mapping(request_spec, "request_spec")
    return {
        "missing_policy": _as_mapping(spec.get("missing_policy")),
        "outlier_policy": _as_mapping(spec.get("outlier_policy")),
        "search_policy": _as_mapping(spec.get("search_policy")),
        "evaluation_policy": _as_mapping(spec.get("evaluation_policy")),
    }


def compute_reuse_key(frozen_project: Any, request_spec: Any = None) -> str:
    """Complete reuse identity. Changing any constituent invalidates the key.

    Filename, isolated row counts and isolated target-column names are not
    part of this key. Subject constraints enter the key only when the frozen
    model was selected under a subject_specific scope.
    """
    frozen, _ = validate_frozen_project(frozen_project)
    spec = _as_mapping(request_spec if request_spec is not None else frozen.get("request_spec"), "request_spec")
    frozen_spec = _as_mapping(frozen.get("request_spec"), "frozen.request_spec")
    model_state = _as_mapping(frozen.get("model_state"), "model_state")
    scope = frozen.get("model_scope")
    constraints = frozen.get("subject_constraints") if scope == MODEL_SCOPE_SUBJECT_SPECIFIC else None
    material = {
        "input_sha256": frozen.get("input_sha256"),
        "dataset_sha256": frozen.get("dataset_sha256"),
        "sample_identity": _sample_identity(frozen.get("sample_ledger") or {}),
        "feature_schema": frozen.get("feature_schema"),
        "encoder_state": frozen.get("encoder_state"),
        "model_spec": frozen.get("model_spec"),
        "model_sha256": model_state.get("model_sha256"),
        "target": {
            "column": spec.get("target_col", frozen_spec.get("target_col")),
            "unit": spec.get("target_unit", frozen_spec.get("target_unit")),
        },
        "policies": _policy_slice(spec if spec else frozen_spec),
        "normative_version": frozen.get("normative_version"),
        "model_scope": scope,
        "subject_constraints": constraints,
        "calculation_version": frozen.get("calculation_version")
        or model_state.get("calculation_version")
        or CALCULATION_VERSION,
        "residual_state_status": (_as_mapping(model_state.get("residual_state")).get("status")
                                  or ("complete" if model_state.get("xtx_inv") else "incomplete")),
        "feature_order": model_state.get("feature_order"),
        "xtx_inv_kind": model_state.get("xtx_inv_kind"),
    }
    return _sha256_text(_canonical_dumps(material))


class ReuseLedger:
    """In-process reuse of a restored frozen fit. Not a second database.

    Coordinates with C11 when a ProjectStore-like object is supplied: only
    JSON-safe metadata/references are remembered, never a user pickle.
    """

    def __init__(self, project_store: Any = None) -> None:
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._project_store = project_store

    def lookup(self, reuse_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            payload = self._mem.get(str(reuse_key))
            return copy.deepcopy(payload) if payload is not None else None

    def remember(self, reuse_key: str, payload: Mapping[str, Any]) -> None:
        safe = _json_safe(dict(payload))
        with self._lock:
            self._mem[str(reuse_key)] = safe

    def __contains__(self, reuse_key: object) -> bool:
        with self._lock:
            return str(reuse_key) in self._mem


def _bind_c11_store(explicit: Any = None) -> Any:
    if explicit is not None:
        return explicit
    try:
        store_mod = importlib.import_module("modules.project_store")
        store_cls = getattr(store_mod, "ProjectStore", None)
        if store_cls is not None:
            return store_cls
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Peer resolution (C02 / C03 / C04 / C06)
# ---------------------------------------------------------------------------

def _try_import(module_name: str, attr: str) -> Optional[Callable[..., Any]]:
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    fn = getattr(mod, attr, None)
    return fn if callable(fn) else None


def _subject_design_to_mapping(design: Any) -> Dict[str, Any]:
    if design is None:
        return {"X": {}, "raw_values": {}, "issues": [], "supported": False}
    if isinstance(design, Mapping):
        x_obj = design.get("X")
        return {
            "X": _row_from_x(x_obj),
            "raw_values": dict(design.get("raw_values") or {}),
            "issues": list(design.get("issues") or []),
            "supported": bool(design.get("supported")),
        }
    x_obj = getattr(design, "X", {})
    return {
        "X": _row_from_x(x_obj),
        "raw_values": dict(getattr(design, "raw_values", {}) or {}),
        "issues": list(getattr(design, "issues", []) or []),
        "supported": bool(getattr(design, "supported", False)),
    }


def _row_from_x(x_obj: Any) -> Dict[str, Any]:
    if x_obj is None:
        return {}
    if isinstance(x_obj, Mapping):
        return dict(x_obj)
    # pandas DataFrame / Series — stay in-process; export uses a dict row.
    try:
        import pandas as pd  # local: optional at export time
    except Exception:
        pd = None  # type: ignore
    if pd is not None and isinstance(x_obj, pd.DataFrame):
        if x_obj.empty:
            return {}
        row = x_obj.iloc[0]
        return {str(k): (None if _is_na(v) else v) for k, v in row.items()}
    if pd is not None and isinstance(x_obj, pd.Series):
        return {str(k): (None if _is_na(v) else v) for k, v in x_obj.items()}
    if hasattr(x_obj, "iloc"):
        try:
            row = x_obj.iloc[0]
            return {str(k): v for k, v in dict(row).items()}
        except Exception:
            pass
    return {}


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    try:
        import pandas as pd
        return bool(pd.isna(value))
    except Exception:
        return False


def _parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _finite_or_none(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "").replace("\xa0", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return _finite_or_none(float(text))
    except ValueError:
        return None


def _stringify_category(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "na", "n/a"}:
        return None
    return text


def builtin_transform_subject(
    subject_raw: Any,
    feature_schema: Any,
    encoder_state: Any,
) -> Dict[str, Any]:
    """Apply a declarative encoder_state. Unknown categories are never the reference."""
    origin = "c14.builtin_transform_subject"
    raw = _as_mapping(subject_raw, "subject_raw")
    state = _as_mapping(encoder_state, "encoder_state")
    schema = _as_mapping(feature_schema, "feature_schema")
    issues: List[Dict[str, Any]] = []
    x_row: Dict[str, Any] = {}
    supported = True
    unknown_policy = state.get("unknown_category_policy") or "unsupported"

    base_variables = list(state.get("base_variables") or [])
    if not base_variables:
        # feature_schema.columns fallback: kind numeric vs categorical
        columns = _as_mapping(schema.get("columns"), "feature_schema.columns")
        for internal, meta in columns.items():
            info = _as_mapping(meta)
            kind = info.get("kind") or "numeric"
            original = info.get("original_name") or internal
            base_variables.append(
                {
                    "original_name": original,
                    "internal_name": internal,
                    "kind": kind,
                    "categories": info.get("categories"),
                    "reference_category": info.get("reference_category"),
                    "indicator_columns": info.get("indicator_columns"),
                    "indicator_levels": info.get("indicator_levels"),
                }
            )

    for spec_bv in base_variables:
        bv = _as_mapping(spec_bv)
        name = str(bv.get("original_name") or bv.get("internal_name") or "")
        raw_value = raw.get(name)
        if raw_value is None:
            # allow nested "raw" already unwrapped
            raw_value = raw.get(bv.get("internal_name"))
        kind = str(bv.get("kind") or "numeric")
        if kind == "categorical":
            label = _stringify_category(raw_value)
            seen = [str(c) for c in _as_list(bv.get("categories"))]
            reference = bv.get("reference_category")
            indicators = [str(c) for c in _as_list(bv.get("indicator_columns"))]
            levels = [str(c) for c in _as_list(bv.get("indicator_levels"))]
            if not indicators and seen:
                levels = [c for c in seen if c != reference]
                prefix = str(bv.get("internal_name") or name)
                indicators = [f"{prefix}_{lvl}" for lvl in levels]
            if label is None:
                supported = False
                for col in indicators:
                    x_row[col] = None
                issues.append(
                    _issue(
                        "predictor_missing",
                        "error",
                        origin,
                        f"Preditor categórico '{name}' ausente; ausência não é referência.",
                        affected_ids=[name],
                        evidence={"reference_category": reference},
                    )
                )
                continue
            if seen and label not in seen:
                supported = False
                for col in indicators:
                    x_row[col] = None
                issues.append(
                    _issue(
                        REASON_UNKNOWN_CATEGORY,
                        "error",
                        origin,
                        (
                            f"Categoria {label!r} de '{name}' não foi vista no treino; "
                            f"política {unknown_policy!r} (nunca recodificada como "
                            f"referência {reference!r})."
                        ),
                        affected_ids=[name, label],
                        evidence={
                            "value": label,
                            "reference_category": reference,
                            "seen": seen,
                            "policy": unknown_policy,
                        },
                    )
                )
                continue
            for col, lvl in zip(indicators, levels):
                x_row[col] = 1.0 if label == lvl else 0.0
            if not indicators:
                internal = str(bv.get("internal_name") or name)
                x_row[internal] = label
            continue

        internal = str(bv.get("internal_name") or name)
        number = _parse_number(raw_value)
        if number is None:
            supported = False
            x_row[internal] = None
            issues.append(
                _issue(
                    "predictor_missing",
                    "error",
                    origin,
                    f"Preditor numérico '{name}' ausente ou não numérico.",
                    affected_ids=[name],
                    evidence={"raw": None if raw_value is None else str(raw_value)},
                )
            )
        else:
            x_row[internal] = number

    column_order = [str(c) for c in _as_list(state.get("column_order"))]
    if column_order:
        for col in column_order:
            x_row.setdefault(col, None)

    return {
        "X": x_row,
        "raw_values": dict(raw),
        "issues": issues,
        "supported": supported,
    }


def _apply_x_transform(value: Optional[float], transform_name: str) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    name = (transform_name or "linear").lower()
    if value is None:
        return None, _issue("transform_failed", "error", "c14.x_transform", "Valor ausente para transformação.", evidence={"transform": name})
    # Prefer C06 Transformer.apply_transformation when present.
    apply_fn = None
    try:
        trans_mod = importlib.import_module("modules.transformations")
        transformer = getattr(trans_mod, "Transformer", None)
        if transformer is not None and hasattr(transformer, "apply_transformation"):
            apply_fn = transformer.apply_transformation
    except Exception:
        apply_fn = None
    if apply_fn is not None:
        try:
            import pandas as pd
            series, ok = apply_fn(pd.Series([value]), name)
            if not ok:
                return None, _issue(
                    "transform_failed",
                    "error",
                    "c14.x_transform",
                    f"Transformação '{name}' inválida para o valor do avaliando.",
                    evidence={"transform": name, "value": value},
                )
            out = _finite_or_none(series.iloc[0])
            if out is None:
                return None, _issue(
                    "transform_failed",
                    "error",
                    "c14.x_transform",
                    f"Transformação '{name}' produziu valor não finito.",
                    evidence={"transform": name},
                )
            return out, None
        except Exception as exc:
            return None, _issue(
                "transform_failed",
                "error",
                "c14.x_transform",
                f"Falha ao aplicar transformação '{name}': {exc}",
                evidence={"transform": name},
            )
    # Minimal domain-checked fallback if C06 is unavailable.
    try:
        if name in {"linear", "identity", "none", ""}:
            return float(value), None
        if name == "ln":
            if value <= 0:
                raise ValueError("ln domain")
            return math.log(value), None
        if name == "sqrt":
            if value < 0:
                raise ValueError("sqrt domain")
            return math.sqrt(value), None
        if name == "sqr":
            return float(value) ** 2, None
        if name == "inverse":
            if value == 0:
                raise ValueError("inverse domain")
            return 1.0 / float(value), None
        if name == "inv_sqr":
            if value == 0:
                raise ValueError("inv_sqr domain")
            return 1.0 / (float(value) ** 2), None
        if name == "inv_sqrt":
            if value <= 0:
                raise ValueError("inv_sqrt domain")
            return 1.0 / math.sqrt(value), None
    except Exception:
        return None, _issue(
            "transform_failed",
            "error",
            "c14.x_transform",
            f"Transformação '{name}' inválida para o valor do avaliando.",
            evidence={"transform": name, "value": value},
        )
    return None, _issue(
        "transform_failed",
        "error",
        "c14.x_transform",
        f"Transformação '{name}' desconhecida.",
        evidence={"transform": name},
    )


def _invert_target(prediction: Any, state: Any, residual_context: Any = None) -> Dict[str, Any]:
    """Use C06 inverse for identity/log; never treat unknown Y as identity."""
    st = _as_mapping(state, "target_transform_state")
    name = str(st.get("name") if st.get("name") is not None else "linear").lower()
    if name not in _KNOWN_Y_NAMES:
        return {
            "value": empty_value(),
            "estimand": None,
            "supported": False,
            "error": f"unknown target transform {st.get('name')!r}",
            "limitations": [f"unknown_y_transform:{st.get('name')}"],
        }
    c06 = _try_import("modules.target_transform", "inverse_target_prediction")
    inverse_meta = st.get("inverse") if isinstance(st.get("inverse"), Mapping) else {}
    complete_c06 = (
        name in {"identity", "log", "ln", "logarithm"}
        and (isinstance(st.get("domain"), Mapping) or bool(inverse_meta.get("invocation")))
    )
    if callable(c06) and complete_c06:
        try:
            return c06(prediction, st, residual_context)
        except Exception as exc:
            return {
                "value": empty_value(),
                "estimand": None,
                "supported": False,
                "error": f"target inverse failed for {name!r}: {exc}",
                "limitations": [f"y_inverse_failed:{name}"],
            }
    return builtin_inverse_target_prediction(prediction, st, residual_context)


_KNOWN_Y_NAMES = frozenset({"linear", "identity", "none", "", "ln", "log", "logarithm"})


def builtin_inverse_target_prediction(
    prediction: Any,
    state: Any,
    residual_context: Any = None,
) -> Dict[str, Any]:
    """Invert a transformed prediction to the original unit. No silent IC claim."""
    st = _as_mapping(state, "target_transform_state")
    raw_name = st.get("name")
    name = str(raw_name if raw_name is not None else "linear").lower()
    limitations: List[str] = []
    if name not in _KNOWN_Y_NAMES:
        return {
            "value": empty_value(),
            "estimand": None,
            "supported": False,
            "error": f"unknown target transform {raw_name!r}",
            "limitations": [f"unknown_y_transform:{raw_name}"],
        }

    def _inv_scalar(z: Optional[float]) -> Optional[float]:
        if z is None:
            return None
        if name in {"linear", "identity", "none", ""}:
            return _finite_or_none(z)
        if name in {"ln", "log", "logarithm"}:
            try:
                return _finite_or_none(math.exp(z))
            except Exception:
                return None
        return None

    if isinstance(prediction, Mapping):
        out = empty_value()
        out["point"] = _inv_scalar(_finite_or_none(prediction.get("point")))
        for key in ("mean_ci80", "prediction_interval", "arbitration_interval", "admissible_interval"):
            block = prediction.get(key)
            if isinstance(block, Mapping):
                lo = _inv_scalar(_finite_or_none(block.get("lower")))
                hi = _inv_scalar(_finite_or_none(block.get("upper")))
                if lo is not None and hi is not None and lo > hi:
                    lo, hi = hi, lo
                extra = {k: v for k, v in block.items() if k not in {"lower", "upper"}}
                out[key] = _interval(lo, hi, extra or None)
            else:
                out[key] = None
        if name not in {"linear", "identity", "none", ""}:
            limitations.append(
                "Intervalos invertidos pela transformação do alvo; IC normativo "
                "só é atribuído quando C06 publica método validado."
            )
            # Retransformed log endpoints are not a monetary mean CI.
            retransformed = out.get("mean_ci80")
            out["mean_ci80"] = None
            out["prediction_interval"] = None
            return {
                "value": out,
                "estimand": st.get("estimand") or "exp(E[log Y|X])",
                "limitations": limitations,
                "interval_interpretation": None,
                "retransformed_interval": retransformed,
            }
        return {
            "value": out,
            "estimand": st.get("estimand") or "original_unit",
            "limitations": limitations,
        }

    point = _inv_scalar(_finite_or_none(prediction))
    value = empty_value()
    value["point"] = point
    return {"value": value, "estimand": st.get("estimand") or "original_unit", "limitations": limitations}


def _t_critical(df: int, level: float = MEAN_CI_LEVEL) -> Optional[float]:
    if df <= 0:
        return None
    try:
        from scipy import stats
        # two-sided: 80% → 0.90 quantile
        q = 1.0 - (1.0 - level) / 2.0
        return float(stats.t.ppf(q, df))
    except Exception:
        # coarse normal fallback only if scipy is missing; documented as such
        return 1.2815515655446004 if abs(level - 0.80) < 1e-9 else None


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _matvec(matrix: Sequence[Sequence[float]], vec: Sequence[float]) -> List[float]:
    return [_dot(row, vec) for row in matrix]


def builtin_evaluate_fitted(
    candidate_fit: Any,
    subject_design: Any,
    request_spec: Any,
) -> Dict[str, Any]:
    """Apply stored coefficients to one encoded subject. Does not refit."""
    fit = _as_mapping(candidate_fit, "candidate_fit")
    design = _subject_design_to_mapping(subject_design)
    spec = _as_mapping(request_spec, "request_spec")
    issues: List[Dict[str, Any]] = list(design.get("issues") or [])
    candidate_id = fit.get("candidate_id") or _as_mapping(fit.get("candidate_spec")).get("candidate_id")
    used_row_ids = [str(x) for x in _as_list(fit.get("used_row_ids"))]
    subject_id = fit.get("subject_id")  # may be overwritten by caller

    if not design.get("supported"):
        return {
            "candidate_id": candidate_id,
            "subject_id": subject_id,
            "subject_raw": design.get("raw_values") or {},
            "value": empty_value(),
            "normative": _empty_normative(),
            "statistical": {},
            "model_eligibility": _empty_eligibility(ERROR, [REASON_UNKNOWN_CATEGORY]),
            "used_row_ids": used_row_ids,
            "issues": issues
            or [
                _issue(
                    "subject_unsupported",
                    "error",
                    "c14.evaluate_fitted",
                    "SubjectDesign.supported=false; avaliação não forçada.",
                )
            ],
        }

    coefficients = _as_mapping(fit.get("coefficients"), "coefficients")
    model_state = _as_mapping(fit.get("model_state"), "model_state")
    if not coefficients:
        coefficients = _as_mapping(model_state.get("coefficients"), "model_state.coefficients")
    candidate_spec = _as_mapping(fit.get("candidate_spec") or fit.get("model_spec"), "candidate_spec")
    x_transformations = _as_mapping(candidate_spec.get("x_transformations"), "x_transformations")
    feature_order = [str(c) for c in _as_list(model_state.get("feature_order") or fit.get("feature_order"))]
    if not feature_order:
        feature_order = list(coefficients.keys())
    x_row = dict(design.get("X") or {})
    raw_values = dict(design.get("raw_values") or {})

    row_values: Dict[str, float] = {}
    for feat in feature_order:
        if feat == "const":
            row_values["const"] = 1.0
            continue
        transform_name = "linear"
        base = feat
        if "(" in feat and feat.endswith(")"):
            transform_name = feat[: feat.index("(")]
            base = feat[feat.index("(") + 1 : -1]
        if base in x_transformations:
            transform_name = str(x_transformations[base] or transform_name)
        raw_num = _parse_number(x_row.get(feat))
        if raw_num is None:
            raw_num = _parse_number(x_row.get(base))
        if raw_num is None:
            raw_num = _parse_number(raw_values.get(base))
        if transform_name not in {"linear", "identity", "none", ""}:
            transformed, err = _apply_x_transform(raw_num, transform_name)
            if err is not None:
                issues.append(err)
                return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)
            row_values[feat] = float(transformed)
        else:
            if raw_num is None:
                issues.append(
                    _issue(
                        "predictor_missing",
                        "error",
                        "c14.evaluate_fitted",
                        f"Coluna '{feat}' ausente no SubjectDesign.",
                        affected_ids=[feat],
                    )
                )
                return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)
            row_values[feat] = float(raw_num)

    intercept = candidate_spec.get("intercept")
    if intercept is False and "const" in row_values:
        row_values.pop("const", None)

    point_t = 0.0
    for name, beta in coefficients.items():
        coef = _finite_or_none(beta)
        if coef is None:
            issues.append(
                _issue(
                    "non_finite_coefficient",
                    "error",
                    "c14.evaluate_fitted",
                    f"Coeficiente não finito em '{name}'.",
                    affected_ids=[name],
                )
            )
            return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)
        x_i = row_values.get(name)
        if x_i is None:
            if name == "const":
                x_i = 1.0
            else:
                issues.append(
                    _issue(
                        "predictor_missing",
                        "error",
                        "c14.evaluate_fitted",
                        f"Regressora '{name}' sem valor no sujeito.",
                        affected_ids=[name],
                    )
                )
                return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)
        point_t += coef * float(x_i)

    if not math.isfinite(point_t):
        issues.append(
            _issue(
                "non_finite_value",
                "error",
                "c14.evaluate_fitted",
                "Predição não finita; valor não é substituído por zero.",
            )
        )
        return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)

    n = int(model_state.get("n") or fit.get("n") or 0)
    k = int(model_state.get("k") or max(0, len(coefficients) - (1 if "const" in coefficients else 0)))
    df = n - k - (1 if "const" in coefficients else 0)
    residual_state = model_state.get("residual_state") or fit.get("residual_state")
    declared = declared_residual_status(residual_state)
    if declared in {STATUS_INCOMPLETE, STATUS_MALFORMED}:
        residual_state = json_safe_residual_state(residual_state)
    elif residual_state_is_complete(residual_state):
        residual_state = json_safe_residual_state(residual_state)
    elif fit.get("model_object") is not None and _is_inprocess_model(fit.get("model_object")):
        residual_state = json_safe_residual_state(extract_residual_state(fit))
    else:
        residual_state = json_safe_residual_state(
            residual_state
            if isinstance(residual_state, Mapping)
            else {"schema_version": "MP-PRO/1", "status": STATUS_INCOMPLETE}
        )
    interval_block = apply_mean_prediction_intervals(
        row_values, residual_state, point_transformed=point_t
    )
    mean_ci = interval_block.get("mean_ci80")
    pred_int = interval_block.get("prediction_interval")
    se_mean = interval_block.get("se_mean")
    residual_std = _finite_or_none(
        (_as_mapping(residual_state).get("residual_std") if isinstance(residual_state, Mapping) else None)
        or model_state.get("residual_std")
    )
    df_resid = _finite_or_none((_as_mapping(residual_state).get("df_resid") if isinstance(residual_state, Mapping) else None))
    if df_resid is not None:
        df = int(df_resid) if df_resid == int(df_resid) else df_resid
    interval_limitations = list(interval_block.get("limitations") or [])

    transformed_value = {
        "point": point_t,
        "mean_ci80": mean_ci,
        "prediction_interval": pred_int,
        "arbitration_interval": None,
        "admissible_interval": None,
    }
    y_state = fit.get("target_transform_state") or model_state.get("target_transform_state") or candidate_spec.get("y_transformation")
    if isinstance(y_state, str):
        y_state = {"name": y_state}
    inverted = _invert_target(transformed_value, y_state, residual_context={"se_mean": se_mean, "df": df})
    if isinstance(inverted, Mapping) and "value" in inverted:
        value = dict(empty_value())
        value.update(_as_mapping(inverted.get("value")))
        limitations = list(inverted.get("limitations") or [])
        estimand = inverted.get("estimand")
    else:
        value = _as_mapping(inverted) if isinstance(inverted, Mapping) else empty_value()
        limitations = []
        estimand = None
    for item in interval_limitations:
        if item not in limitations:
            limitations.append(item)

    y_name = ""
    if isinstance(y_state, Mapping):
        y_name = str(y_state.get("name") or "")
    elif isinstance(y_state, str):
        y_name = y_state
    y_name = y_name.lower()
    log_target = y_name in {"ln", "log", "logarithm"}
    if log_target:
        # exp(E[log Y|X]) is not a monetary mean CI. Do not invent one.
        if inverted.get("interval_interpretation") not in {None, "mean_ci80"}:
            value["mean_ci80"] = None
        if estimand and estimand not in {"E[Y|X]"}:
            value["mean_ci80"] = None
            if "interval_not_mean_ci80" not in limitations:
                limitations.append("interval_not_mean_ci80")

    point = _finite_or_none(value.get("point"))
    if point is None:
        issues.append(
            _issue(
                "non_finite_value",
                "error",
                "c14.evaluate_fitted",
                "Valor na unidade original não finito; não substituído por zero.",
            )
        )
        return _failed_assessment(candidate_id, subject_id, raw_values, used_row_ids, issues)

    from modules.valuation_policy.intervals import compose_value_intervals

    residual_complete = LIMITATION_NO_INTERVALS not in limitations and LIMITATION_INCOMPLETE not in limitations and LIMITATION_MALFORMED not in limitations
    c05_rule = None
    if isinstance(spec, Mapping):
        c05_rule = spec.get("c05_interval_rule") or (spec.get("qualification_profile") or {}).get("interval_rule")
    unified, interval_notes = compose_value_intervals(
        point=point,
        mean_ci80=value.get("mean_ci80"),
        prediction_interval=value.get("prediction_interval"),
        c05_interval_rule=c05_rule,
        residual_complete=residual_complete,
        limitations=limitations,
    )
    value["mean_ci80"] = unified.get("mean_ci80")
    value["prediction_interval"] = unified.get("prediction_interval")
    value["arbitration_interval"] = unified.get("arbitration_interval")
    value["admissible_interval"] = unified.get("admissible_interval")
    for note in interval_notes:
        if note not in limitations:
            limitations.append(note)
    mean_ci80 = value.get("mean_ci80") if isinstance(value.get("mean_ci80"), Mapping) else None
    if mean_ci80 is None and (LIMITATION_NO_INTERVALS in limitations or LIMITATION_INCOMPLETE in limitations or LIMITATION_MALFORMED in limitations):
        issues.append(
            _issue(
                LIMITATION_NO_INTERVALS,
                "warning",
                "c14.evaluate_fitted",
                "Intervalos estatísticos indisponíveis: estado residual incompleto ou malformado; faixa percentual não é IC.",
            )
        )

    statistical = {
        "n": n or None,
        "k": k or None,
        "df": df if df > 0 else None,
        "residual_std": residual_std,
        "se_mean": se_mean,
        "limitations": limitations,
        "target_unit": spec.get("target_unit"),
        "estimand": estimand,
        "residual_state_status": (_as_mapping(residual_state).get("status") if isinstance(residual_state, Mapping) else None),
    }
    return {
        "candidate_id": candidate_id,
        "subject_id": subject_id,
        "subject_raw": raw_values,
        "value": {
            "point": point,
            "mean_ci80": value.get("mean_ci80"),
            "prediction_interval": value.get("prediction_interval"),
            "arbitration_interval": value.get("arbitration_interval"),
            "admissible_interval": value.get("admissible_interval"),
        },
        "normative": _empty_normative(),
        "statistical": statistical,
        "model_eligibility": _empty_eligibility(ELIGIBLE, []),
        "used_row_ids": used_row_ids,
        "issues": issues,
    }


def _failed_assessment(
    candidate_id: Any,
    subject_id: Any,
    raw_values: Mapping[str, Any],
    used_row_ids: Sequence[str],
    issues: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "subject_id": subject_id,
        "subject_raw": dict(raw_values),
        "value": empty_value(),
        "normative": _empty_normative(),
        "statistical": {},
        "model_eligibility": _empty_eligibility(ERROR, [str(i.get("code")) for i in issues if i.get("code")]),
        "used_row_ids": list(used_row_ids),
        "issues": list(issues),
    }


def _sample_ranges(frozen: Mapping[str, Any]) -> Dict[str, Dict[str, float]]:
    ledger = _as_mapping(frozen.get("sample_ledger"), "sample_ledger")
    ranges = _as_mapping(ledger.get("sample_ranges") or ledger.get("ranges"), "sample_ranges")
    out: Dict[str, Dict[str, float]] = {}
    for name, block in ranges.items():
        info = _as_mapping(block)
        vmin = _finite_or_none(info.get("min") if "min" in info else info.get("sample_min"))
        vmax = _finite_or_none(info.get("max") if "max" in info else info.get("sample_max"))
        if vmin is not None and vmax is not None:
            out[str(name)] = {"min": vmin, "max": vmax}
    domain_vars = _as_mapping(_as_mapping(frozen.get("domain")).get("variables"), "domain.variables")
    for name, block in domain_vars.items():
        if name in out:
            continue
        info = _as_mapping(block)
        vmin = _finite_or_none(
            info.get("sample_min") if info.get("sample_min") is not None else info.get("min")
        )
        vmax = _finite_or_none(
            info.get("sample_max") if info.get("sample_max") is not None else info.get("max")
        )
        if vmin is not None and vmax is not None:
            out[str(name)] = {"min": vmin, "max": vmax}
    return out


def _extrapolation_details(raw: Mapping[str, Any], ranges: Mapping[str, Mapping[str, float]]) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    for var, bounds in ranges.items():
        val = _parse_number(raw.get(var))
        if val is None:
            continue
        details.append(
            {
                "variable": var,
                "avaliando_value": val,
                "sample_min": bounds["min"],
                "sample_max": bounds["max"],
            }
        )
    return details


def builtin_assess_normative(context: Any) -> Dict[str, Any]:
    """Per-subject fundamentação/precisão. Documentary items come from THIS subject."""
    ctx = _as_mapping(context, "normative_context")
    issues: List[Dict[str, Any]] = []
    raw = _as_mapping(ctx.get("subject_raw"), "subject_raw")
    documentary_in = ctx.get("documentary") or {}
    # Never accept another subject's documentary payload mixed in.
    if isinstance(documentary_in, Mapping):
        documentary_items = [copy.deepcopy(x) for x in _as_list(documentary_in.get("items"))]
        documentary_origin = documentary_in.get("origin") or "subject"
        documentary_subject_id = documentary_in.get("subject_id")
    else:
        documentary_items = []
        documentary_origin = "subject"
        documentary_subject_id = None

    expected_sid = ctx.get("subject_id")
    if documentary_subject_id is not None and expected_sid is not None and str(documentary_subject_id) != str(expected_sid):
        issues.append(
            _issue(
                "documentary_subject_mismatch",
                "error",
                "c14.assess_normative",
                "Itens documentais de outro imóvel não são copiados.",
                affected_ids=[expected_sid, documentary_subject_id],
            )
        )
        documentary_items = []

    sample_item_scores = _as_mapping(ctx.get("sample_item_scores"), "sample_item_scores")
    item_scores = {int(k): int(v) for k, v in sample_item_scores.items() if str(k).isdigit()}
    details = list(ctx.get("extrapolation_details") or [])
    if not details:
        details = _extrapolation_details(raw, _as_mapping(ctx.get("sample_ranges"), "sample_ranges"))

    item4_grau = None
    item4_detail = "Item 4 não calculado."
    nbr = None
    try:
        nbr_mod = importlib.import_module("modules.nbr14653_validation")
        nbr = getattr(nbr_mod, "NBRValidator", None)
    except Exception:
        nbr = None

    amplitude_pct = _finite_or_none(ctx.get("amplitude_pct"))
    point = _finite_or_none(ctx.get("point"))
    ci_lower = _finite_or_none(ctx.get("ci_lower"))
    ci_upper = _finite_or_none(ctx.get("ci_upper"))

    if nbr is not None and hasattr(nbr, "_classify_item4_extrapolacao"):
        item4_grau, item4_detail = nbr._classify_item4_extrapolacao(details)
    else:
        item4_grau, item4_detail = _fallback_item4(details)
    item_scores[4] = int(item4_grau or 0)

    if nbr is not None and hasattr(nbr, "_classify_fundamentacao"):
        grade, points = nbr._classify_fundamentacao(item_scores)
    else:
        points = sum(item_scores.get(i, 0) for i in range(1, 7))
        grade = None

    precisao_status = "not_computed"
    precisao_grade = None
    if amplitude_pct is None:
        precisao_status = "not_computed"
    elif nbr is not None and hasattr(nbr, "_classify_precisao"):
        precisao_grade, _msg = nbr._classify_precisao(amplitude_pct)
        precisao_status = "classified" if precisao_grade is not None else "unclassified"
    else:
        if amplitude_pct <= 30:
            precisao_grade = 3
        elif amplitude_pct <= 40:
            precisao_grade = 2
        elif amplitude_pct <= 50:
            precisao_grade = 1
        else:
            precisao_grade = None
        precisao_status = "classified" if precisao_grade is not None else "unclassified"

    items = []
    descriptions = {
        1: "Caracterização da região e do imóvel",
        2: "Quantidade mínima de dados de mercado",
        3: "Identificação dos dados de mercado",
        4: "Extrapolação",
        5: "Nível de significância dos regressores",
        6: "Nível de significância da regressão (F)",
    }
    for i in range(1, 7):
        items.append(
            {
                "id": f"tabela1_item{i}",
                "item": i,
                "description": descriptions[i],
                "points": item_scores.get(i),
                "grade": item_scores.get(i),
                "evidence_status": "calculated" if i == 4 else (ctx.get("sample_evidence_status") or "declared"),
                "source": "NBR 14653-2:2011 Tabela 1" if i != 4 else "NBR 14653-2:2011 Tabela 1 item 4 (recalculado por sujeito)",
                "detail": item4_detail if i == 4 else None,
            }
        )

    verification = "partial"
    if ctx.get("rule_sources"):
        verification = "verified_rules_listed"
    edition = ctx.get("edition") or ctx.get("normative_version") or "NBR 14653-2:2011"

    return {
        "edition": edition,
        "rule_sources": list(ctx.get("rule_sources") or ["NBR 14653-2:2011 Tabela 1", "NBR 14653-2:2011 Tabela 5"]),
        "verification_status": verification,
        "fundamentacao": {
            "grade": grade,
            "points": points,
            "items": items,
        },
        "precisao": {
            "status": precisao_status,
            "grade": precisao_grade,
            "amplitude_pct": amplitude_pct,
        },
        "documentary": {
            "items": documentary_items,
            "origin": documentary_origin,
            "subject_id": expected_sid,
        },
        "issues": issues,
        "extrapolation_details": details,
        "central_estimate": point,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
    }


def _fallback_item4(details: Sequence[Mapping[str, Any]]) -> Tuple[int, str]:
    if not details:
        return 0, "Nenhuma variável do avaliando informada para checagem de extrapolação."
    extrapolated = []
    out_of_bounds = []
    for item in details:
        val = item.get("avaliando_value")
        vmin = item.get("sample_min")
        vmax = item.get("sample_max")
        if val is None or vmin is None or vmax is None:
            continue
        ext_min = 0.5 * vmin
        ext_max = 2.0 * vmax
        if vmin <= val <= vmax:
            continue
        if ext_min <= val <= ext_max:
            extrapolated.append(item.get("variable"))
        else:
            out_of_bounds.append(item.get("variable"))
    if out_of_bounds:
        return 0, f"Item 4 reprovado: variável(is) {out_of_bounds} fora do intervalo estendido."
    if not extrapolated:
        return 3, "Nenhuma extrapolação."
    if len(extrapolated) == 1:
        return 2, f"Extrapolação admitida (Grau II): {extrapolated[0]}."
    return 1, f"Extrapolação admitida apenas em Grau I: {extrapolated}."


def _assessment_to_mapping(assessment: Any) -> Dict[str, Any]:
    if assessment is None:
        return {}
    if isinstance(assessment, Mapping):
        return dict(assessment)
    if hasattr(assessment, "to_dict") and callable(assessment.to_dict):
        return dict(assessment.to_dict())
    return {
        "candidate_id": getattr(assessment, "candidate_id", None),
        "subject_id": getattr(assessment, "subject_id", None),
        "subject_raw": dict(getattr(assessment, "subject_raw", {}) or {}),
        "value": dict(getattr(assessment, "value", None) or empty_value()),
        "normative": dict(getattr(assessment, "normative", None) or _empty_normative()),
        "statistical": dict(getattr(assessment, "statistical", {}) or {}),
        "model_eligibility": dict(getattr(assessment, "model_eligibility", {}) or {}),
        "used_row_ids": list(getattr(assessment, "used_row_ids", []) or []),
        "issues": list(getattr(assessment, "issues", []) or []),
    }


def _peer_evaluate_fitted(candidate_fit: Any, subject_design: Any, request_spec: Any) -> Dict[str, Any]:
    """Use C04 when a live CandidateFit with model_object is in memory; else apply frozen state.

    C04 refuses mappings and fits without model_object (it will not unpickle). A FrozenProject
    that only carries specification/coefficients is evaluated here without a new fit.
    """
    peer = _try_import("modules.model_builder", "evaluate_fitted")
    if peer is not None:
        candidate_cls = None
        try:
            mb = importlib.import_module("modules.model_builder")
            candidate_cls = getattr(mb, "CandidateFit", None)
        except Exception:
            candidate_cls = None
        live = (
            candidate_cls is not None
            and isinstance(candidate_fit, candidate_cls)
            and getattr(candidate_fit, "model_object", None) is not None
            and getattr(candidate_fit, "status", None) in {None, "fitted"}
        )
        if live:
            return _assessment_to_mapping(peer(candidate_fit, subject_design, request_spec))
    return builtin_evaluate_fitted(candidate_fit, subject_design, request_spec)


def _peer_transform_subject(subject_raw: Any, feature_schema: Any, encoder_state: Any) -> Any:
    peer = _try_import("modules.preprocessing", "transform_subject")
    if peer is None:
        return builtin_transform_subject(subject_raw, feature_schema, encoder_state)
    try:
        design = peer(subject_raw, feature_schema, encoder_state)
    except Exception as exc:
        fallback = builtin_transform_subject(subject_raw, feature_schema, encoder_state)
        mapped = _subject_design_to_mapping(fallback)
        issues = list(mapped.get("issues") or [])
        issues.append(
            _issue(
                "peer_transform_exception",
                "error",
                "c14.transform_subject",
                f"C02 transform_subject recusou o sujeito: {type(exc).__name__}: {exc}",
            )
        )
        mapped["issues"] = issues
        if any(str(i.get("code")) == REASON_UNKNOWN_CATEGORY for i in issues):
            mapped["supported"] = False
        return mapped
    mapped = _subject_design_to_mapping(design)
    # C02 may return an empty design if encoder_state is not its full fit output.
    # In that case the frozen-application encoder still has to run so the batch
    # remains usable against a specification-only FrozenProject.
    x_row = mapped.get("X") or {}
    has_numeric = any(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in x_row.values())
    if has_numeric or mapped.get("issues"):
        return design
    return builtin_transform_subject(subject_raw, feature_schema, encoder_state)


def resolve_adapters(overrides: Optional[Mapping[str, Callable[..., Any]]] = None) -> Dict[str, Callable[..., Any]]:
    """Prefer published MP/1 callables; otherwise the frozen-application builtins."""
    adapters = {
        "transform_subject": _peer_transform_subject,
        "evaluate_fitted": _peer_evaluate_fitted,
        "assess_normative": _try_import("modules.nbr14653_validation", "assess_normative") or builtin_assess_normative,
        "inverse_target_prediction": _invert_target,
    }
    if overrides:
        for key, fn in overrides.items():
            if callable(fn):
                adapters[key] = fn
    return adapters


# ---------------------------------------------------------------------------
# Domain / scope eligibility
# ---------------------------------------------------------------------------

def _normalize_subject(subject: Any, index: int) -> Dict[str, Any]:
    if not isinstance(subject, Mapping):
        raise TypeError(f"subject[{index}] must be a mapping")
    data = dict(subject)
    raw = data.get("raw")
    if raw is None:
        raw = data.get("subject_raw")
    if raw is None:
        reserved = {
            "subject_id",
            "id",
            "documentary",
            "raw",
            "subject_raw",
            "constraints",
        }
        raw = {k: v for k, v in data.items() if k not in reserved}
    raw = _as_mapping(raw, f"subject[{index}].raw")
    subject_id = data.get("subject_id") or data.get("id")
    if subject_id is None or str(subject_id).strip() == "":
        subject_id = f"index:{index}"
        missing_id = True
    else:
        subject_id = str(subject_id)
        missing_id = False
    documentary = data.get("documentary") or {}
    if isinstance(documentary, Mapping):
        documentary = dict(documentary)
        documentary.setdefault("subject_id", subject_id)
        documentary.setdefault("origin", "subject")
        documentary.setdefault("items", list(documentary.get("items") or []))
    else:
        documentary = {"subject_id": subject_id, "origin": "subject", "items": []}
    return {
        "subject_id": subject_id,
        "raw": raw,
        "documentary": documentary,
        "constraints": _as_mapping(data.get("constraints"), "subject.constraints"),
        "missing_id": missing_id,
        "index": index,
    }


def _in_declared_domain(domain: Any, raw: Mapping[str, Any]) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    reasons: List[str] = []
    issues: List[Dict[str, Any]] = []
    domain_map = _as_mapping(domain, "domain")
    variables = _as_mapping(domain_map.get("variables"), "domain.variables")
    if not variables:
        return True, reasons, issues
    for name, spec in variables.items():
        info = _as_mapping(spec)
        raw_val = raw.get(name)
        allowed = info.get("allowed_categories") or info.get("categories")
        if allowed is not None:
            label = _stringify_category(raw_val)
            allowed_s = [str(x) for x in _as_list(allowed)]
            if label is None or label not in allowed_s:
                reasons.append(REASON_OUT_OF_DOMAIN)
                issues.append(
                    _issue(
                        REASON_OUT_OF_DOMAIN,
                        "error",
                        "c14.domain",
                        f"Sujeito fora do domínio categórico de '{name}'.",
                        affected_ids=[name],
                        evidence={"value": label, "allowed": allowed_s},
                    )
                )
            continue
        vmin = _finite_or_none(info.get("min"))
        vmax = _finite_or_none(info.get("max"))
        number = _parse_number(raw_val)
        if vmin is None and vmax is None:
            continue
        if number is None:
            reasons.append(REASON_OUT_OF_DOMAIN)
            issues.append(
                _issue(
                    REASON_OUT_OF_DOMAIN,
                    "error",
                    "c14.domain",
                    f"Sujeito sem valor numérico de domínio para '{name}'.",
                    affected_ids=[name],
                )
            )
            continue
        if vmin is not None and number < vmin:
            reasons.append(REASON_OUT_OF_DOMAIN)
            issues.append(
                _issue(
                    REASON_OUT_OF_DOMAIN,
                    "error",
                    "c14.domain",
                    f"Valor de '{name}' abaixo do domínio declarado.",
                    affected_ids=[name],
                    evidence={"value": number, "min": vmin, "max": vmax},
                )
            )
        if vmax is not None and number > vmax:
            reasons.append(REASON_OUT_OF_DOMAIN)
            issues.append(
                _issue(
                    REASON_OUT_OF_DOMAIN,
                    "error",
                    "c14.domain",
                    f"Valor de '{name}' acima do domínio declarado.",
                    affected_ids=[name],
                    evidence={"value": number, "min": vmin, "max": vmax},
                )
            )
    ok = REASON_OUT_OF_DOMAIN not in reasons
    return ok, reasons, issues


def _subject_constraints_satisfied(
    frozen: Mapping[str, Any],
    subject: Mapping[str, Any],
) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    """A subject_specific model is reusable only under its original constraints."""
    reasons: List[str] = []
    issues: List[Dict[str, Any]] = []
    if frozen.get("model_scope") != MODEL_SCOPE_SUBJECT_SPECIFIC:
        return True, reasons, issues
    constraints = _as_mapping(frozen.get("subject_constraints"), "subject_constraints")
    if not constraints:
        reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
        issues.append(
            _issue(
                REASON_SUBJECT_SPECIFIC,
                "error",
                "c14.scope",
                (
                    "Modelo subject_specific sem subject_constraints verificáveis; "
                    "não é reutilizado como modelo de população."
                ),
                affected_ids=[subject.get("subject_id")],
            )
        )
        return False, reasons, issues

    selection_id = constraints.get("selection_subject_id")
    if selection_id is not None and str(subject.get("subject_id")) == str(selection_id):
        # The original subject of the search remains eligible on identity,
        # still subject to domain checks elsewhere.
        pass
    elif selection_id is not None:
        reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
        issues.append(
            _issue(
                REASON_SUBJECT_SPECIFIC,
                "error",
                "c14.scope",
                (
                    "Modelo escolhido sob restrições de um avaliando "
                    f"({selection_id!r}) não é automaticamente adequado a "
                    f"{subject.get('subject_id')!r}."
                ),
                affected_ids=[subject.get("subject_id"), selection_id],
                evidence={"selection_subject_id": selection_id},
            )
        )
        return False, reasons, issues

    bound = _as_mapping(constraints.get("bound_variables"), "bound_variables")
    raw = _as_mapping(subject.get("raw"), "raw")
    for name, spec in bound.items():
        info = _as_mapping(spec)
        number = _parse_number(raw.get(name))
        vmin = _finite_or_none(info.get("min"))
        vmax = _finite_or_none(info.get("max"))
        equals = info.get("equals")
        if equals is not None and str(raw.get(name)) != str(equals) and _parse_number(equals) != number:
            reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
            issues.append(
                _issue(
                    REASON_SUBJECT_SPECIFIC,
                    "error",
                    "c14.scope",
                    f"Restrição de seleção em '{name}' não satisfeita.",
                    affected_ids=[subject.get("subject_id"), name],
                )
            )
            return False, reasons, issues
        if vmin is not None and (number is None or number < vmin):
            reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
            issues.append(
                _issue(
                    REASON_SUBJECT_SPECIFIC,
                    "error",
                    "c14.scope",
                    f"Sujeito fora da vizinhança de seleção em '{name}'.",
                    affected_ids=[subject.get("subject_id"), name],
                    evidence={"value": number, "min": vmin, "max": vmax},
                )
            )
            return False, reasons, issues
        if vmax is not None and (number is None or number > vmax):
            reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
            issues.append(
                _issue(
                    REASON_SUBJECT_SPECIFIC,
                    "error",
                    "c14.scope",
                    f"Sujeito fora da vizinhança de seleção em '{name}'.",
                    affected_ids=[subject.get("subject_id"), name],
                    evidence={"value": number, "min": vmin, "max": vmax},
                )
            )
            return False, reasons, issues

    required_equals = _as_mapping(constraints.get("required_raw_equals"), "required_raw_equals")
    for name, expected in required_equals.items():
        if str(raw.get(name)) != str(expected) and _parse_number(raw.get(name)) != _parse_number(expected):
            reasons.extend([REASON_SUBJECT_SPECIFIC, REASON_REQUIRES_INDIVIDUAL])
            issues.append(
                _issue(
                    REASON_SUBJECT_SPECIFIC,
                    "error",
                    "c14.scope",
                    f"Sujeito não reproduz a restrição de seleção em '{name}'.",
                    affected_ids=[subject.get("subject_id"), name],
                )
            )
            return False, reasons, issues

    return True, reasons, issues


def restore_candidate_fit(frozen: Mapping[str, Any]) -> Dict[str, Any]:
    """Build an in-memory CandidateFit from safe specification/state. No pickle."""
    existing = frozen.get("candidate_fit")
    if existing is not None:
        fit = _as_mapping(existing, "candidate_fit")
        # Drop any pickled/user-supplied model_object that is not already in-process.
        if fit.get("model_object") is not None and not _is_inprocess_model(fit.get("model_object")):
            fit = dict(fit)
            fit["model_object"] = None
            fit.setdefault("issues", []).append(
                _issue(
                    "pickle_rejected",
                    "warning",
                    "c14.restore",
                    "model_object não reconhecido como objeto in-process; ignorado (sem unpickle).",
                )
            )
        return fit
    spec = _as_mapping(frozen.get("model_spec"), "model_spec")
    state = _as_mapping(frozen.get("model_state"), "model_state")
    ledger = _as_mapping(frozen.get("sample_ledger"), "sample_ledger")
    return {
        "candidate_id": spec.get("candidate_id") or "frozen",
        "status": "fitted",
        "candidate_spec": spec,
        "model_object": None,
        "coefficients": dict(_as_mapping(state.get("coefficients"), "coefficients")),
        "feature_schema": frozen.get("feature_schema"),
        "encoder_state": frozen.get("encoder_state"),
        "used_row_ids": list(_as_list(state.get("used_row_ids") or ledger.get("used_row_ids"))),
        "excluded_row_ids": list(_as_list(state.get("excluded_row_ids") or ledger.get("excluded_row_ids"))),
        "base_frame": None,
        "diagnostics": dict(_as_mapping(state.get("diagnostics"), "diagnostics")),
        "target_transform_state": state.get("target_transform_state") or spec.get("y_transformation"),
        "model_sha256": state.get("model_sha256"),
        "model_state": state,
        "model_spec": spec,
        "n": state.get("n"),
        "k": state.get("k"),
        "feature_order": list(_as_list(state.get("feature_order"))),
        "residual_state": state.get("residual_state") or frozen.get("residual_state"),
        "issues": [],
    }


def _is_inprocess_model(obj: Any) -> bool:
    if obj is None:
        return False
    # statsmodels Results is acceptable if already in this process.
    name = type(obj).__name__
    module = getattr(type(obj), "__module__", "") or ""
    if "statsmodels" in module:
        return True
    if name in {"RegressionResultsWrapper", "OLSResults"}:
        return True
    return False


def _request_spec_conflicts(frozen_spec: Mapping[str, Any], request_spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    keys = ("target_col", "target_unit")
    for key in keys:
        left = frozen_spec.get(key)
        right = request_spec.get(key)
        if left is not None and right is not None and str(left) != str(right):
            issues.append(
                _issue(
                    REASON_POLICY_MISMATCH,
                    "warning",
                    "c14.request_spec",
                    f"request_spec.{key} difere do FrozenProject; reúso da chave completa muda.",
                    evidence={"frozen": left, "request": right, "field": key},
                )
            )
    return issues


def _amplitude_pct(value: Mapping[str, Any]) -> Optional[float]:
    point = _finite_or_none(value.get("point"))
    mean_ci = value.get("mean_ci80")
    if not isinstance(mean_ci, Mapping) or point is None or point == 0:
        return None
    lo = _finite_or_none(mean_ci.get("lower"))
    hi = _finite_or_none(mean_ci.get("upper"))
    if lo is None or hi is None:
        return None
    return abs(hi - lo) / abs(point) * 100.0


def _version_link(frozen: Mapping[str, Any], reuse_key: str) -> Dict[str, Any]:
    state = _as_mapping(frozen.get("model_state"))
    prov = _as_mapping(frozen.get("provenance"))
    return {
        "project_id": frozen.get("project_id"),
        "revision_id": frozen.get("revision_id"),
        "input_sha256": frozen.get("input_sha256"),
        "dataset_sha256": frozen.get("dataset_sha256"),
        "model_sha256": state.get("model_sha256"),
        "reuse_key": reuse_key,
        "normative_version": frozen.get("normative_version"),
        "code_sha": prov.get("code_sha"),
    }


def _pending_item(subject: Mapping[str, Any], frozen: Mapping[str, Any], reuse_key: str, reason: str) -> Dict[str, Any]:
    sid = subject["subject_id"]
    return {
        "subject_id": sid,
        "status": STATUS_PENDING,
        "value": empty_value(),
        "unit": _as_mapping(frozen.get("request_spec")).get("target_unit"),
        "validation": None,
        "pendencias": [_issue(reason, "warning", "c14.batch", "Item ainda não avaliado.", affected_ids=[sid])],
        "version_link": _version_link(frozen, reuse_key),
        "assessment": {
            "candidate_id": _as_mapping(frozen.get("model_spec")).get("candidate_id"),
            "subject_id": sid,
            "subject_raw": dict(subject.get("raw") or {}),
            "value": empty_value(),
            "normative": _empty_normative(),
            "statistical": {},
            "model_eligibility": _empty_eligibility(REVIEW_REQUIRED, [reason]),
            "used_row_ids": list(_as_list(_as_mapping(frozen.get("sample_ledger")).get("used_row_ids"))),
            "issues": [],
        },
    }


def _summarize(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    summary = {
        "succeeded": 0,
        "failed": 0,
        "pending": 0,
        "cancelled": 0,
        "unsupported": 0,
        "total": len(items),
    }
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
        elif status == STATUS_CANCELLED:
            summary["cancelled"] += 1
    return summary


def export_batch_result(batch_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Structured export for C10/C12. Not a consolidated PDF."""
    return _json_safe(dict(batch_result))


# ---------------------------------------------------------------------------
# Per-subject evaluation
# ---------------------------------------------------------------------------

def _assess_subject_normative(
    adapters: Mapping[str, Callable[..., Any]],
    frozen: Mapping[str, Any],
    candidate_fit: Mapping[str, Any],
    subject: Mapping[str, Any],
    raw: Mapping[str, Any],
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """C03 with axes/n/k from the frozen sample, else builtin; stamp this subject's documentary."""
    extra = dict(extra or {})
    sid = subject.get("subject_id")
    documentary_in = subject.get("documentary") if isinstance(subject.get("documentary"), Mapping) else {}
    documentary = dict(documentary_in)
    documentary.setdefault("subject_id", sid)
    documentary.setdefault("origin", "subject")
    documentary.setdefault("items", list(documentary.get("items") or []))

    ranges = _sample_ranges(frozen)
    details = extra.pop("extrapolation_details", None) or _extrapolation_details(raw, ranges)
    axes = extra.pop("axes", None)
    if not axes:
        axes = []
        for item in details:
            axes.append(
                {
                    "name": item.get("variable") or item.get("name"),
                    "variable": item.get("variable") or item.get("name"),
                    "kind": item.get("kind") or "quantitative",
                    "avaliando_value": item.get("avaliando_value"),
                    "sample_min": item.get("sample_min"),
                    "sample_max": item.get("sample_max"),
                    "sample_values": item.get("sample_values"),
                }
            )

    diagnostics = _as_mapping(candidate_fit.get("diagnostics"))
    model_state = _as_mapping(candidate_fit.get("model_state"))
    coefficients = _as_mapping(candidate_fit.get("coefficients") or model_state.get("coefficients"))
    n = extra.pop("n", None)
    if n is None:
        n = candidate_fit.get("n") or model_state.get("n") or diagnostics.get("n")
    k = extra.pop("k", None)
    if k is None:
        k = candidate_fit.get("k") or model_state.get("k") or diagnostics.get("k")
    sample_item_scores = extra.pop("sample_item_scores", None)
    if sample_item_scores is None:
        sample_item_scores = _as_mapping(diagnostics.get("item_scores"))

    pvalues = extra.pop("pvalues", None)
    if not isinstance(pvalues, Mapping) or not pvalues:
        pvalues = diagnostics.get("pvalues") or model_state.get("pvalues") or {}
    f_pvalue = extra.pop("f_pvalue", None)
    if f_pvalue is None:
        f_pvalue = diagnostics.get("f_pvalue")
    if f_pvalue is None:
        f_pvalue = model_state.get("f_pvalue")

    ctx: Dict[str, Any] = {
        "subject_id": sid,
        "subject_raw": raw,
        "documentary": documentary,
        # Sample-level scores are evidence about the fitted sample, not a
        # substitute for this subject's items 1/3. C03 ignores them as grades.
        "sample_item_scores": sample_item_scores,
        "sample_ranges": ranges,
        "axes": axes,
        "extrapolation_details": details,
        "n": n,
        "k": k,
        "intercept": True if "const" in coefficients else extra.get("intercept"),
        "pvalues": pvalues,
        "f_pvalue": f_pvalue,
        "normative_version": frozen.get("normative_version"),
        "edition": frozen.get("normative_version"),
    }
    ctx.update(extra)

    peer = adapters.get("assess_normative") or builtin_assess_normative
    # Grade None is a legitimate pending/unclassified result. It does not
    # authorize a second classifier, even when sample_item_scores exist.
    result = _as_mapping(peer(ctx), "normative")

    doc = result.get("documentary")
    if not isinstance(doc, dict):
        doc = {}
        result["documentary"] = doc
    doc["subject_id"] = documentary.get("subject_id") or sid
    doc.setdefault("origin", documentary.get("origin") or "subject")
    if "items" not in doc:
        doc["items"] = list(documentary.get("items") or [])
    return result


def _evaluate_one(
    *,
    frozen: Mapping[str, Any],
    subject: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    candidate_fit: Mapping[str, Any],
    adapters: Mapping[str, Callable[..., Any]],
    reuse_key: str,
) -> Dict[str, Any]:
    sid = subject["subject_id"]
    raw = dict(subject["raw"])
    issues: List[Dict[str, Any]] = []
    if subject.get("missing_id"):
        issues.append(
            _issue(
                "missing_subject_id",
                "warning",
                "c14.batch",
                "subject_id ausente; atribuído índice estável para rastreio.",
                affected_ids=[sid],
            )
        )

    eligibility_reasons: List[str] = []
    ok_scope, scope_reasons, scope_issues = _subject_constraints_satisfied(frozen, subject)
    issues.extend(scope_issues)
    eligibility_reasons.extend(scope_reasons)

    domain = frozen.get("domain")
    domain_map = _as_mapping(domain, "domain")
    if frozen.get("model_scope") == MODEL_SCOPE_POPULATION and not _as_mapping(domain_map.get("variables")):
        eligibility_reasons.append(REASON_MISSING_DOMAIN)
        eligibility_reasons.append(REASON_REQUIRES_INDIVIDUAL)
        issues.append(
            _issue(
                REASON_MISSING_DOMAIN,
                "warning",
                "c14.domain",
                "population_model sem domínio declarado; não autorizado como população irrestrita.",
                affected_ids=[sid],
            )
        )

    in_domain, domain_reasons, domain_issues = _in_declared_domain(domain, raw)
    issues.extend(domain_issues)
    eligibility_reasons.extend(domain_reasons)

    design_obj = adapters["transform_subject"](raw, frozen.get("feature_schema"), frozen.get("encoder_state"))
    design = _subject_design_to_mapping(design_obj)
    issues.extend(list(design.get("issues") or []))

    unknown = any(
        str(i.get("code")) == REASON_UNKNOWN_CATEGORY for i in design.get("issues") or []
    )
    if unknown or not design.get("supported"):
        assessment = adapters["evaluate_fitted"](candidate_fit, design_obj, request_spec)
        assessment = _as_mapping(assessment, "assessment")
        assessment["subject_id"] = sid
        assessment["subject_raw"] = raw
        assessment["value"] = empty_value()
        assessment["used_row_ids"] = list(_as_list(candidate_fit.get("used_row_ids")))
        # Per-subject normative still runs (own grades); documentary of THIS subject only.
        normative = _assess_subject_normative(
            adapters,
            frozen,
            candidate_fit,
            subject,
            raw,
            extra={"amplitude_pct": None, "point": None},
        )
        assessment["normative"] = _as_mapping(normative, "normative")
        assessment["model_eligibility"] = _empty_eligibility(
            ERROR,
            [REASON_UNKNOWN_CATEGORY] if unknown else [str(i.get("code")) for i in design.get("issues") or []],
        )
        merged_issues = list(assessment.get("issues") or []) + issues
        assessment["issues"] = merged_issues
        return {
            "subject_id": sid,
            "status": STATUS_FAILED,
            "value": empty_value(),
            "unit": request_spec.get("target_unit"),
            "validation": assessment.get("normative"),
            "pendencias": [i for i in merged_issues if i.get("severity") in {"error", "warning"}],
            "version_link": _version_link(frozen, reuse_key),
            "assessment": assessment,
        }

    if not ok_scope or not in_domain or REASON_MISSING_DOMAIN in eligibility_reasons:
        if REASON_REQUIRES_INDIVIDUAL not in eligibility_reasons:
            eligibility_reasons.append(REASON_REQUIRES_INDIVIDUAL)
        # Do not force a predicted value for an inadequate model.
        normative = _assess_subject_normative(
            adapters,
            frozen,
            candidate_fit,
            subject,
            raw,
            extra={"amplitude_pct": None, "point": None},
        )
        reasons = []
        for r in eligibility_reasons:
            if r not in reasons:
                reasons.append(r)
        assessment = {
            "candidate_id": candidate_fit.get("candidate_id"),
            "subject_id": sid,
            "subject_raw": raw,
            "value": empty_value(),
            "normative": _as_mapping(normative, "normative"),
            "statistical": {},
            "model_eligibility": _empty_eligibility(UNSUPPORTED, reasons),
            "used_row_ids": list(_as_list(candidate_fit.get("used_row_ids"))),
            "issues": issues,
        }
        return {
            "subject_id": sid,
            "status": STATUS_UNSUPPORTED,
            "value": empty_value(),
            "unit": request_spec.get("target_unit"),
            "validation": assessment["normative"],
            "pendencias": [i for i in issues if i.get("severity") in {"error", "warning"}],
            "version_link": _version_link(frozen, reuse_key),
            "assessment": assessment,
        }

    assessment_obj = adapters["evaluate_fitted"](candidate_fit, design_obj, request_spec)
    assessment = _as_mapping(assessment_obj, "assessment")
    assessment["subject_id"] = sid
    assessment["subject_raw"] = raw
    value = dict(empty_value())
    value.update(_as_mapping(assessment.get("value"), "value"))
    point = _finite_or_none(value.get("point"))
    if point is None:
        issues.extend(list(assessment.get("issues") or []))
        issues.append(
            _issue(
                "evaluation_failed",
                "error",
                "c14.batch",
                "Falha de cálculo: valor nulo, nunca zero substituto.",
                affected_ids=[sid],
            )
        )
        assessment["value"] = empty_value()
        assessment["issues"] = issues
        assessment["model_eligibility"] = _empty_eligibility(ERROR, ["evaluation_failed"])
        return {
            "subject_id": sid,
            "status": STATUS_FAILED,
            "value": empty_value(),
            "unit": request_spec.get("target_unit"),
            "validation": assessment.get("normative"),
            "pendencias": issues,
            "version_link": _version_link(frozen, reuse_key),
            "assessment": assessment,
        }

    mean_ci = value.get("mean_ci80") if isinstance(value.get("mean_ci80"), Mapping) else None
    amplitude = _amplitude_pct(value)
    normative = _assess_subject_normative(
        adapters,
        frozen,
        candidate_fit,
        subject,
        raw,
        extra={
            "amplitude_pct": amplitude,
            "point": point,
            "ci_lower": None if mean_ci is None else mean_ci.get("lower"),
            "ci_upper": None if mean_ci is None else mean_ci.get("upper"),
            "predict_original": lambda subject_raw: _predict_original_callback(
                frozen, candidate_fit, adapters, request_spec, subject_raw
            ),
        },
    )
    assessment["value"] = value
    assessment["normative"] = _as_mapping(normative, "normative")
    merged_issues = list(assessment.get("issues") or []) + issues
    assessment["issues"] = merged_issues
    elig = _as_mapping(assessment.get("model_eligibility"), "model_eligibility")
    if elig.get("status") not in VALID_ELIGIBILITY:
        elig = _empty_eligibility(ELIGIBLE, [])
    # eligible is not issuance authorization — recorded on the item, never upgraded.
    assessment["model_eligibility"] = elig
    assessment["used_row_ids"] = list(_as_list(candidate_fit.get("used_row_ids")))
    return {
        "subject_id": sid,
        "status": STATUS_SUCCEEDED,
        "value": value,
        "unit": request_spec.get("target_unit"),
        "validation": assessment["normative"],
        "pendencias": [i for i in merged_issues if i.get("severity") in {"error", "warning"}],
        "version_link": _version_link(frozen, reuse_key),
        "assessment": assessment,
    }


def _predict_original_callback(
    frozen: Mapping[str, Any],
    candidate_fit: Mapping[str, Any],
    adapters: Mapping[str, Callable[..., Any]],
    request_spec: Mapping[str, Any],
    subject_raw: Any,
) -> Optional[float]:
    design = adapters["transform_subject"](subject_raw, frozen.get("feature_schema"), frozen.get("encoder_state"))
    assessment = _as_mapping(adapters["evaluate_fitted"](candidate_fit, design, request_spec), "assessment")
    return _finite_or_none(_as_mapping(assessment.get("value")).get("point"))


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def evaluate_batch(
    frozen_project: Any,
    subjects: Any,
    request_spec: Any,
    progress_callback: Optional[Callable[[Mapping[str, Any]], None]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    *,
    resume_from: Optional[Mapping[str, Any]] = None,
    reuse_ledger: Optional[ReuseLedger] = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    adapters: Optional[Mapping[str, Callable[..., Any]]] = None,
    project_store: Any = None,
) -> Dict[str, Any]:
    """Evaluate many subjects with one frozen project/model.

    Does not refit. Does not copy grau or documentary items across subjects.
    Cancel leaves remaining items pending (never success). Resume evaluates
    only items whose previous status is not a completed terminal state.
    """
    frozen, frozen_issues = validate_frozen_project(frozen_project)
    spec = _as_mapping(request_spec, "request_spec")
    frozen_spec = _as_mapping(frozen.get("request_spec"), "frozen.request_spec")
    if not spec:
        spec = dict(frozen_spec)
    batch_issues: List[Dict[str, Any]] = list(frozen_issues)
    batch_issues.extend(_request_spec_conflicts(frozen_spec, spec))

    if not isinstance(subjects, Sequence) or isinstance(subjects, (str, bytes)):
        raise TypeError("subjects must be a sequence of mappings")

    normalized = [_normalize_subject(s, i) for i, s in enumerate(list(subjects))]
    # Idempotency: first occurrence of each subject_id wins; later duplicates
    # are not evaluated twice and do not append a second result.
    seen_ids: Dict[str, int] = {}
    unique_subjects: List[Dict[str, Any]] = []
    for sub in normalized:
        sid = sub["subject_id"]
        if sid in seen_ids:
            batch_issues.append(
                _issue(
                    "duplicate_subject_id",
                    "warning",
                    "c14.batch",
                    "subject_id duplicado no lote; a primeira ocorrência é conservada.",
                    affected_ids=[sid],
                )
            )
            continue
        seen_ids[sid] = len(unique_subjects)
        unique_subjects.append(sub)

    reuse_key = compute_reuse_key(frozen, spec)
    ledger = reuse_ledger if reuse_ledger is not None else ReuseLedger(project_store=_bind_c11_store(project_store))
    ledger_hit = False
    restored_from_ledger = ledger.lookup(reuse_key)
    candidate_fit = restore_candidate_fit(frozen)
    if restored_from_ledger is not None:
        ledger_hit = True
        # Restore coefficients/state from the ledger payload (JSON-safe), not pickle.
        for field in ("coefficients", "model_state", "diagnostics", "target_transform_state", "model_sha256", "n", "k", "feature_order", "used_row_ids"):
            if field in restored_from_ledger and restored_from_ledger[field] is not None:
                candidate_fit[field] = copy.deepcopy(restored_from_ledger[field])
    else:
        ledger.remember(
            reuse_key,
            {
                "coefficients": candidate_fit.get("coefficients"),
                "model_state": candidate_fit.get("model_state"),
                "diagnostics": candidate_fit.get("diagnostics"),
                "target_transform_state": candidate_fit.get("target_transform_state"),
                "model_sha256": candidate_fit.get("model_sha256"),
                "n": candidate_fit.get("n"),
                "k": candidate_fit.get("k"),
                "feature_order": candidate_fit.get("feature_order"),
                "used_row_ids": candidate_fit.get("used_row_ids"),
            },
        )

    resolved_adapters = resolve_adapters(adapters)

    previous_by_id: Dict[str, Dict[str, Any]] = {}
    if resume_from is not None:
        prev = _as_mapping(resume_from, "resume_from")
        for item in _as_list(prev.get("items")):
            mapping = _as_mapping(item, "resume item")
            psid = mapping.get("subject_id")
            if psid is not None:
                previous_by_id[str(psid)] = mapping

    items: List[Optional[Dict[str, Any]]] = [None] * len(unique_subjects)
    to_run: List[int] = []
    for idx, sub in enumerate(unique_subjects):
        prev_item = previous_by_id.get(sub["subject_id"])
        if prev_item is not None and prev_item.get("status") in COMPLETED_STATUSES:
            items[idx] = copy.deepcopy(prev_item)
        else:
            to_run.append(idx)

    cancelled = False
    workers = int(max_workers) if max_workers else DEFAULT_MAX_WORKERS
    if workers < 1:
        workers = 1
    if workers > MAX_WORKERS_CAP:
        workers = MAX_WORKERS_CAP

    completed_count = sum(1 for it in items if it is not None)
    total = len(unique_subjects)

    def _emit(event: str, extra: Optional[Mapping[str, Any]] = None) -> None:
        if progress_callback is None:
            return
        payload = {
            "event": event,
            "completed": completed_count,
            "total": total,
            "progress": (completed_count / total) if total else 1.0,
        }
        if extra:
            payload.update(dict(extra))
        progress_callback(payload)

    _emit("batch_started")

    cancel_flag = threading.Event()

    def _is_cancelled() -> bool:
        if cancel_flag.is_set():
            return True
        if cancel_requested is None:
            return False
        try:
            if bool(cancel_requested()):
                cancel_flag.set()
                return True
        except Exception:
            return False
        return False

    def _run_index(idx: int) -> Tuple[int, Dict[str, Any]]:
        # Queued executor tasks that have not started must not become success
        # after cancel. In-flight evaluate_one calls keep their real status.
        if _is_cancelled():
            return idx, _pending_item(unique_subjects[idx], frozen, reuse_key, "cancelled")
        return idx, _evaluate_one(
            frozen=frozen,
            subject=unique_subjects[idx],
            request_spec=spec,
            candidate_fit=candidate_fit,
            adapters=resolved_adapters,
            reuse_key=reuse_key,
        )

    def _record_item(idx: int, item: Mapping[str, Any]) -> None:
        nonlocal completed_count
        items[idx] = item
        if item.get("status") in COMPLETED_STATUSES:
            completed_count += 1
            _emit(
                "item_completed",
                {"subject_id": item["subject_id"], "item_status": item["status"]},
            )

    if _is_cancelled():
        cancelled = True
        for idx in to_run:
            items[idx] = _pending_item(unique_subjects[idx], frozen, reuse_key, "cancelled")
        to_run = []

    if to_run and workers == 1:
        for idx in to_run:
            if _is_cancelled():
                cancelled = True
                items[idx] = _pending_item(unique_subjects[idx], frozen, reuse_key, "cancelled")
                # remaining also pending; do not mark success
                for rest in to_run[to_run.index(idx) + 1 :]:
                    if items[rest] is None:
                        items[rest] = _pending_item(unique_subjects[rest], frozen, reuse_key, "cancelled")
                break
            _idx, item = _run_index(idx)
            _record_item(_idx, item)
    elif to_run:
        # Submit at most `workers` at a time. After cancel, do not submit the
        # remainder; those stay pending (never success). In-flight tasks that
        # already entered evaluate_one keep their real completed status.
        queue = deque(to_run)
        in_flight: set = set()
        with ThreadPoolExecutor(max_workers=workers) as pool:

            def _submit_available() -> None:
                while queue and len(in_flight) < workers:
                    if _is_cancelled():
                        return
                    idx = queue.popleft()
                    in_flight.add(pool.submit(_run_index, idx))

            _submit_available()
            while in_flight:
                done, not_done = wait(in_flight, return_when=FIRST_COMPLETED)
                in_flight = set(not_done)
                for fut in done:
                    idx, item = fut.result()
                    _record_item(idx, item)
                if _is_cancelled():
                    cancelled = True
                    break
                _submit_available()
            if cancelled:
                if in_flight:
                    drained, _ = wait(in_flight)
                    for fut in drained:
                        idx, item = fut.result()
                        _record_item(idx, item)
                    in_flight.clear()
                while queue:
                    idx = queue.popleft()
                    if items[idx] is None:
                        items[idx] = _pending_item(
                            unique_subjects[idx], frozen, reuse_key, "cancelled"
                        )
            for idx in to_run:
                if items[idx] is None:
                    items[idx] = _pending_item(
                        unique_subjects[idx], frozen, reuse_key, "cancelled"
                    )

    final_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        if item is None:
            final_items.append(_pending_item(unique_subjects[idx], frozen, reuse_key, "pending"))
        else:
            final_items.append(item)

    summary = _summarize(final_items)
    blocking = [i for i in frozen_issues if i.get("severity") == "error"]
    if cancelled:
        state = "cancelled"
    elif blocking and summary["succeeded"] == 0 and summary["unsupported"] == 0:
        state = "failed"
    elif summary["pending"] > 0:
        state = "interrupted"
    elif summary["failed"] > 0 and summary["succeeded"] == 0 and summary["unsupported"] == 0:
        state = "failed"
    else:
        state = "succeeded"

    _emit("batch_finished", {"state": state})

    result = {
        "schema_version": SCHEMA_VERSION,
        "batch_id": _as_mapping(frozen.get("provenance")).get("batch_id"),
        "project_id": frozen.get("project_id"),
        "revision_id": frozen.get("revision_id"),
        "model_scope": frozen.get("model_scope"),
        "reuse": {
            "key": reuse_key,
            "fit_reused": True,
            "ledger_hit": ledger_hit,
            "fields": list(_REUSE_KEY_FIELDS),
        },
        "state": state,
        "items": final_items,
        "summary": summary,
        "issues": batch_issues,
        "progress": 1.0 if not final_items else summary["pending"] and (summary["total"] - summary["pending"]) / summary["total"] or 1.0,
        "max_workers": workers,
        "export": None,
    }
    # Honest progress: completed fraction, never an invented percent.
    done = summary["total"] - summary["pending"] - summary["cancelled"]
    # cancelled items are not completed work
    completed_real = summary["succeeded"] + summary["failed"] + summary["unsupported"]
    result["progress"] = (completed_real / summary["total"]) if summary["total"] else 1.0
    result["export"] = export_batch_result({k: v for k, v in result.items() if k != "export"})
    # Public alias: C14 items are the per-subject assessments.
    result["assessments"] = result["items"]
    return result
