"""Explicit feature schema and declarative encoder for MP/1 (C02).

The same schema serves the training sample, the subject form, reserved
evaluation and batches. Encoder state is a JSON-safe mapping (no code),
fit only on the rows the caller marked as train.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCHEMA_VERSION = "MP/1"
FEATURE_SCHEMA_VERSION = "MP/1"
ENCODER_STATE_VERSION = "MP/1"

# Distinct, visible states. Absence is never the reference category.
ISSUE_EMPTY_CANDIDATES = "empty_candidates"
ISSUE_MISSING_POLICY_UNDECLARED = "missing_policy_undeclared"
ISSUE_TARGET_IMPUTE_FORBIDDEN = "target_impute_forbidden"
ISSUE_TARGET_COL_MISSING = "target_col_missing"
ISSUE_TARGET_MISSING = "target_missing"
ISSUE_PREDICTOR_MISSING = "predictor_missing"
ISSUE_PREDICTOR_IMPUTED = "predictor_imputed"
ISSUE_UNKNOWN_CATEGORY = "unknown_category"
ISSUE_CONSTANT_COLUMN = "constant_column"
ISSUE_COLLINEAR_COLUMNS = "collinear_columns"
ISSUE_GROUP_NO_SUPPORT = "group_no_support"
ISSUE_CATEGORY_NO_SUPPORT = "category_no_support"
ISSUE_HIGH_CARDINALITY = "high_cardinality"
ISSUE_DATE_PENDING = "date_pending"
ISSUE_IDENTIFIER_EXCLUDED = "identifier_excluded"
ISSUE_NO_TRAIN_ROWS = "no_train_rows"
ISSUE_UNPARSEABLE_NUMERIC = "unparseable_numeric"
ISSUE_HELD_OUT = "held_out_not_used"
ISSUE_REFERENCE_UNAVAILABLE = "reference_unavailable"
ISSUE_SCHEMA_MISMATCH = "schema_mismatch"
ISSUE_ROLE_EXCLUDED = "role_excluded"

RESERVED_ROLES = frozenset({"identifier", "source", "excluded", "date"})
PREDICTOR_IMPUTE_METHODS = frozenset({"complete_case", "mean", "median"})
NEVER_IMPUTE_TARGET = frozenset({None, "never_impute", "none", "never", "complete_case"})
_MISSING_STRINGS = frozenset(
    {"", "na", "nan", "none", "null", "nat", "-", "--", "n/a", "n.d.", "nd"}
)
_HIGH_CARDINALITY_ABS = 20

_CURRENCY_RE = re.compile(r"[R$\s\xa0]")


class _DataclassMapping(MappingABC):
    """In-process objects remain mappings so C05/C10/C12 can call .get()."""

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
class PreparedDataset(_DataclassMapping):
    """In-process MP/1 prepared sample. DataFrames stay in-process, not JSON."""

    X: pd.DataFrame
    y: pd.Series
    row_ids: List[str]
    feature_schema: Dict[str, Any]
    encoder_state: Dict[str, Any]
    sample_ledger: Dict[str, Any]
    issues: List[Dict[str, Any]]
    dataset_sha256: str
    base_frame: pd.DataFrame
    schema_version: str = SCHEMA_VERSION


@dataclass
class SubjectDesign(_DataclassMapping):
    """One subject encoded with a frozen schema/encoder."""

    X: pd.DataFrame
    raw_values: Dict[str, Any]
    issues: List[Dict[str, Any]]
    supported: bool
    schema_version: str = SCHEMA_VERSION


def make_issue(
    code: str,
    severity: str,
    origin: str,
    message: str,
    affected_ids: Optional[Sequence[Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": origin,
        "message": message,
        "affected_ids": [str(x) for x in (affected_ids or [])],
        "evidence": json_safe(dict(evidence or {})),
    }


def json_safe(obj: Any) -> Any:
    """JSON-serializable mapping/list/scalar. Rejects non-finite numbers."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int, np.integer)) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        if not math.isfinite(value):
            raise ValueError("non-finite number cannot enter encoder_state/JSON")
        return value
    if isinstance(obj, dict):
        return {str(key): json_safe(val) for key, val in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(val) for val in obj]
    if isinstance(obj, np.ndarray):
        return json_safe(obj.tolist())
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"value of type {type(obj).__name__} is not JSON-safe")


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip().lower() in _MISSING_STRINGS:
        return True
    return False


def parse_numeric(value: Any, locale: str = "auto") -> Optional[float]:
    """Parse a numeric scalar via C01 ``parse_numeric_token``.

    None means missing, unparseable, non-finite, or **ambiguous**. Tokens such
    as ``1.234`` with locale ``auto`` stay None; they are never silently
    converted to 1.234 or 1234.
    """
    from modules.utils import parse_numeric_token

    parsed = parse_numeric_token(value, locale or "auto")
    if parsed.status in {"parsed", "already_numeric"}:
        return parsed.value
    return None


def dataset_sha256(
    feature_schema: Mapping[str, Any],
    encoder_state: Mapping[str, Any],
    row_ids: Sequence[str],
) -> str:
    payload = json.dumps(
        {
            "schema_version": SCHEMA_VERSION,
            "feature_schema": json_safe(feature_schema),
            "encoder_state": json_safe(encoder_state),
            "row_ids": [str(r) for r in row_ids],
        },
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dumps_encoder_artifacts(feature_schema: Mapping[str, Any], encoder_state: Mapping[str, Any]) -> str:
    """Stdlib JSON mapping path. DataFrames never enter this string."""
    return json.dumps(
        {
            "feature_schema": json_safe(feature_schema),
            "encoder_state": json_safe(encoder_state),
        },
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    )


def loads_encoder_artifacts(payload: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data = json.loads(payload)
    return data["feature_schema"], data["encoder_state"]


def _locale_from_spec(spec: Mapping[str, Any]) -> str:
    options = spec.get("import_options") or {}
    locale = options.get("locale") or "auto"
    if locale not in {"auto", "pt-BR", "en-US"}:
        return "auto"
    return locale


def _role(spec: Mapping[str, Any], column: str, target_col: str) -> str:
    roles = spec.get("roles") or {}
    if column in roles and roles[column]:
        return str(roles[column])
    if column == target_col:
        return "target"
    if column == "row_id":
        return "identifier"
    return "predictor"


def infer_kind(
    name: str,
    series: pd.Series,
    spec: Mapping[str, Any],
    target_col: str,
) -> str:
    role = _role(spec, name, target_col)
    if role in {"identifier", "source", "excluded", "date", "target"}:
        return role if role != "target" else "numeric"
    kinds = spec.get("kinds") or spec.get("semantic_types") or {}
    if name in kinds and kinds[name]:
        return str(kinds[name])
    locale = _locale_from_spec(spec)
    if pd.api.types.is_bool_dtype(series):
        return "categorical"
    observed = [v for v in series.tolist() if not is_missing(v)]
    if not observed:
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"
        return "categorical"
    numeric_hits = sum(parse_numeric(v, locale) is not None for v in observed)
    # Majority-numeric strings (incl. pt-BR formatted) are quantitative.
    # Nominal labels such as bairro="Centro" do not parse and stay categorical.
    # Integer codes are quantitative only when the caller declared kind=numeric
    # or the values are already a numeric dtype; we do not invent an ordinal scale
    # from a string enumeration.
    if numeric_hits > 0.5 * len(observed):
        if pd.api.types.is_string_dtype(series) or series.dtype == object:
            return "numeric"
        if pd.api.types.is_numeric_dtype(series):
            return "numeric"
        return "numeric"
    return "categorical"


def _stringify_category(value: Any) -> Optional[str]:
    if is_missing(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in _MISSING_STRINGS:
        return None
    return text


def _indicator_name(base: str, category: str) -> str:
    safe = re.sub(r"\s+", "_", str(category).strip())
    safe = re.sub(r"[^\w\.\-]+", "_", safe, flags=re.UNICODE)
    return f"{base}_{safe}"


def _choose_reference(
    counts: Mapping[str, int],
    requested: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not counts:
        return None, None
    if requested is not None and requested in counts:
        return requested, None
    issue = None
    if requested is not None and requested not in counts:
        issue = make_issue(
            ISSUE_REFERENCE_UNAVAILABLE,
            "warning",
            "c02.fit_dataset",
            (
                f"Categoria de referência pedida {requested!r} não aparece no treino; "
                "a referência passa a ser a mais frequente (empate alfabético)."
            ),
            affected_ids=[requested],
            evidence={"requested": requested, "seen": sorted(counts)},
        )
    max_count = max(counts.values())
    tied = sorted(name for name, n in counts.items() if n == max_count)
    return tied[0], issue


def _grouping_for(spec: Mapping[str, Any], column: str) -> Dict[str, Any]:
    policy = (spec.get("grouping_policy") or {}).get(column) or {}
    mapping = dict(policy.get("map") or policy.get("mapping") or {})
    return {
        "policy": "mapped" if mapping else "none",
        "justification": policy.get("justification"),
        "mapping": {str(k): str(v) for k, v in mapping.items()},
    }


def _apply_group_map(value: Optional[str], mapping: Mapping[str, str]) -> Optional[str]:
    if value is None:
        return None
    return mapping.get(value, value)


def fit_encoder(
    train_frame: pd.DataFrame,
    candidate_cols: Sequence[str],
    spec: Mapping[str, Any],
    target_col: str,
    origin: str = "c02.fit_dataset",
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Learn a declarative encoder from TRAIN rows only."""
    issues: List[Dict[str, Any]] = []
    locale = _locale_from_spec(spec)
    units = spec.get("units") or {}
    missing_policy = spec.get("missing_policy") or {}
    pred_method = missing_policy.get("predictors")
    unknown_policy = (
        (spec.get("unknown_category_policy") or missing_policy.get("unknown_category") or "unsupported")
    )
    if unknown_policy not in {"unsupported"}:
        # Silent recode-to-reference is forbidden; only a previously declared
        # non-reference strategy would be added here. Unknown stays unsupported.
        unknown_policy = "unsupported"

    n_train = int(len(train_frame))
    base_variables: List[Dict[str, Any]] = []
    columns: Dict[str, Any] = {}
    groups: Dict[str, Any] = {}
    column_order: List[str] = []
    used_names = set()

    def _unique_internal(name: str) -> str:
        candidate = name
        suffix = 2
        while candidate in used_names:
            candidate = f"{name}__{suffix}"
            suffix += 1
        used_names.add(candidate)
        return candidate

    for col in candidate_cols:
        if col not in train_frame.columns:
            issues.append(
                make_issue(
                    ISSUE_ROLE_EXCLUDED,
                    "warning",
                    origin,
                    f"Coluna candidata '{col}' não existe no parsed_frame.",
                    affected_ids=[col],
                )
            )
            continue
        role = _role(spec, col, target_col)
        if col == "row_id" or role == "identifier":
            issues.append(
                make_issue(
                    ISSUE_IDENTIFIER_EXCLUDED,
                    "info",
                    origin,
                    f"Identificador '{col}' não entra em X.",
                    affected_ids=[col],
                    evidence={"role": role},
                )
            )
            continue
        if role in {"source", "excluded"}:
            issues.append(
                make_issue(
                    ISSUE_ROLE_EXCLUDED,
                    "info",
                    origin,
                    f"Coluna '{col}' com papel '{role}' não entra em X.",
                    affected_ids=[col],
                    evidence={"role": role},
                )
            )
            continue
        if role == "date" or infer_kind(col, train_frame[col], spec, target_col) == "date":
            date_interp = (spec.get("date_interpretations") or {}).get(col)
            if not date_interp:
                issues.append(
                    make_issue(
                        ISSUE_DATE_PENDING,
                        "warning",
                        origin,
                        (
                            f"Coluna de data '{col}' permanece pendente: nenhuma interpretação "
                            "explícita foi declarada antes de derivação quantitativa."
                        ),
                        affected_ids=[col],
                        evidence={"reference_date": spec.get("reference_date")},
                    )
                )
                continue

        kind = infer_kind(col, train_frame[col], spec, target_col)
        unit = units.get(col)
        if unit == "":
            unit = None

        if kind == "numeric":
            parsed_vals: List[float] = []
            unparseable = 0
            missing_n = 0
            for raw in train_frame[col].tolist():
                if is_missing(raw):
                    missing_n += 1
                    continue
                number = parse_numeric(raw, locale)
                if number is None:
                    unparseable += 1
                    continue
                parsed_vals.append(number)
            if unparseable:
                issues.append(
                    make_issue(
                        ISSUE_UNPARSEABLE_NUMERIC,
                        "warning",
                        origin,
                        f"Coluna numérica '{col}' tem {unparseable} valor(es) não parseáveis no treino.",
                        affected_ids=[col],
                        evidence={"unparseable": unparseable, "locale": locale},
                    )
                )
            train_mean = float(np.mean(parsed_vals)) if parsed_vals else None
            train_median = float(np.median(parsed_vals)) if parsed_vals else None
            train_var = float(np.var(parsed_vals, ddof=0)) if parsed_vals else None
            impute_value = None
            impute_method = pred_method
            if pred_method == "mean":
                impute_value = train_mean
            elif pred_method == "median":
                impute_value = train_median
            internal = _unique_internal(col)
            if parsed_vals and len(set(parsed_vals)) <= 1:
                issues.append(
                    make_issue(
                        ISSUE_CONSTANT_COLUMN,
                        "warning",
                        origin,
                        f"Coluna numérica '{col}' é constante no treino.",
                        affected_ids=[internal],
                        evidence={
                            "original_name": col,
                            "value": parsed_vals[0],
                            "variance": train_var,
                            "n": len(parsed_vals),
                        },
                    )
                )
            if not parsed_vals:
                issues.append(
                    make_issue(
                        ISSUE_GROUP_NO_SUPPORT,
                        "warning",
                        origin,
                        f"Coluna numérica '{col}' sem valores observáveis no treino.",
                        affected_ids=[col],
                        evidence={"missing": missing_n, "unparseable": unparseable},
                    )
                )
            columns[internal] = {
                "original_name": col,
                "role": "predictor",
                "kind": "numeric",
                "unit": unit,
                "group_id": None,
                "categories": None,
                "reference_category": None,
            }
            column_order.append(internal)
            base_variables.append(
                {
                    "original_name": col,
                    "internal_name": internal,
                    "role": "predictor",
                    "kind": "numeric",
                    "unit": unit,
                    "group_id": None,
                    "impute_value": impute_value,
                    "impute_method": impute_method,
                    "train_mean": train_mean,
                    "train_median": train_median,
                    "train_variance": train_var,
                    "train_n": len(parsed_vals),
                    "locale": locale,
                }
            )
            continue

        # categorical — never treated as a quantitative scale
        grouping = _grouping_for(spec, col)
        mapping = grouping["mapping"]
        counts: Dict[str, int] = {}
        for raw in train_frame[col].tolist():
            label = _apply_group_map(_stringify_category(raw), mapping)
            if label is None:
                continue
            counts[label] = counts.get(label, 0) + 1
        requested_ref = (spec.get("reference_categories") or {}).get(col)
        reference, ref_issue = _choose_reference(counts, requested_ref)
        if ref_issue:
            issues.append(ref_issue)
        levels = sorted(counts)
        indicator_levels = [lv for lv in levels if lv != reference]
        indicator_columns: List[str] = []
        for level in indicator_levels:
            indicator_columns.append(_unique_internal(_indicator_name(col, level)))

        support = {lv: int(counts[lv]) for lv in levels}
        zero_support = [lv for lv, n in support.items() if n <= 0]
        for lv in zero_support:
            issues.append(
                make_issue(
                    ISSUE_CATEGORY_NO_SUPPORT,
                    "warning",
                    origin,
                    f"Categoria {lv!r} de '{col}' não tem suporte no treino.",
                    affected_ids=[col, lv],
                    evidence={"support": support},
                )
            )

        if not levels:
            issues.append(
                make_issue(
                    ISSUE_GROUP_NO_SUPPORT,
                    "warning",
                    origin,
                    f"Grupo categórico '{col}' sem categorias observadas no treino.",
                    affected_ids=[col],
                    evidence={"support": support},
                )
            )
        elif len(levels) == 1:
            issues.append(
                make_issue(
                    ISSUE_GROUP_NO_SUPPORT,
                    "warning",
                    origin,
                    (
                        f"Grupo categórico '{col}' tem um único nível no treino "
                        f"({levels[0]!r}); sem parâmetro livre (referência única)."
                    ),
                    affected_ids=[col],
                    evidence={
                        "categories": levels,
                        "reference_category": reference,
                        "n_indicators": 0,
                        "support": support,
                    },
                )
            )

        if len(levels) >= _HIGH_CARDINALITY_ABS or (n_train and len(levels) > max(n_train / 2.0, 1)):
            issues.append(
                make_issue(
                    ISSUE_HIGH_CARDINALITY,
                    "info",
                    origin,
                    (
                        f"Coluna '{col}' tem {len(levels)} níveis no treino (n={n_train}). "
                        "Alta cardinalidade é decisão de orçamento e adequação amostral, "
                        "não impossibilidade técnica; os níveis vistos foram codificados."
                    ),
                    affected_ids=[col],
                    evidence={
                        "n_levels": len(levels),
                        "n_train": n_train,
                        "n_free_parameters": len(indicator_columns),
                    },
                )
            )

        group_id = col
        groups[group_id] = {
            "columns": list(indicator_columns),
            "base_variable": col,
        }
        for internal, level in zip(indicator_columns, indicator_levels):
            columns[internal] = {
                "original_name": col,
                "role": "predictor",
                "kind": "categorical",
                "unit": unit,
                "group_id": group_id,
                "categories": list(levels),
                "reference_category": reference,
                "level": level,
            }
            column_order.append(internal)

        base_variables.append(
            {
                "original_name": col,
                "internal_name": None,
                "role": "predictor",
                "kind": "categorical",
                "unit": unit,
                "group_id": group_id,
                "categories": list(levels),
                "reference_category": reference,
                "indicator_columns": list(indicator_columns),
                "indicator_levels": list(indicator_levels),
                "support": support,
                "grouping": grouping,
                "unknown_policy": unknown_policy,
                "locale": locale,
            }
        )

    n_quantitative = sum(1 for spec_bv in base_variables if spec_bv["kind"] == "numeric")
    n_groups = sum(1 for spec_bv in base_variables if spec_bv["kind"] == "categorical")
    n_indicators = sum(
        len(spec_bv.get("indicator_columns") or [])
        for spec_bv in base_variables
        if spec_bv["kind"] == "categorical"
    )
    parameter_accounting = {
        "n_effective_placeholder": n_train,
        "n_quantitative": n_quantitative,
        "n_categorical_groups": n_groups,
        "n_indicator_columns": n_indicators,
        "n_free_slopes": n_quantitative + n_indicators,
        "n_free_with_intercept": n_quantitative + n_indicators + 1,
        "groups": {
            spec_bv["group_id"]: {
                "base_variable": spec_bv["original_name"],
                "n_levels_seen": len(spec_bv.get("categories") or []),
                "n_indicators": len(spec_bv.get("indicator_columns") or []),
                "n_free_parameters": len(spec_bv.get("indicator_columns") or []),
                "reference_category": spec_bv.get("reference_category"),
                "support": spec_bv.get("support") or {},
                "atomic": True,
            }
            for spec_bv in base_variables
            if spec_bv["kind"] == "categorical" and spec_bv.get("group_id")
        },
    }

    target_unit = spec.get("target_unit")
    if target_unit == "":
        target_unit = None
    if target_unit is None:
        target_unit = units.get(target_col)

    feature_schema = {
        "version": FEATURE_SCHEMA_VERSION,
        "column_order": list(column_order),
        "columns": columns,
        "groups": groups,
        "target": {"column": target_col, "unit": target_unit},
        "parameter_accounting": parameter_accounting,
        "base_variables": {
            spec_bv["original_name"]: {
                "kind": spec_bv["kind"],
                "role": spec_bv["role"],
                "unit": spec_bv.get("unit"),
                "categories": spec_bv.get("categories"),
                "reference_category": spec_bv.get("reference_category"),
                "group_id": spec_bv.get("group_id"),
                "original_name": spec_bv["original_name"],
            }
            for spec_bv in base_variables
        },
    }

    original_to_internal = {}
    internal_to_original = {}
    for spec_bv in base_variables:
        original_to_internal[spec_bv["original_name"]] = spec_bv["original_name"]
        internal_to_original[spec_bv["original_name"]] = spec_bv["original_name"]
    column_map = spec.get("_column_map") or {}
    if isinstance(column_map, dict):
        for original, internal in column_map.items():
            if original == "row_id":
                continue
            original_to_internal[str(original)] = str(internal)
            internal_to_original[str(internal)] = str(original)

    encoder_state = json_safe(
        {
            "version": ENCODER_STATE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "column_order": column_order,
            "locale": locale,
            "missing_policy": {
                "target": "never_impute",
                "predictors": pred_method,
                "unknown_category": unknown_policy,
            },
            "unknown_category_policy": unknown_policy,
            "target": {"column": target_col, "unit": target_unit},
            "base_variables": base_variables,
            "original_to_internal": original_to_internal,
            "internal_to_original": internal_to_original,
        }
    )
    return feature_schema, encoder_state, issues


def _base_lookup_keys(base_name: str, encoder_state: Mapping[str, Any]) -> List[str]:
    keys = [base_name]
    original = (encoder_state.get("internal_to_original") or {}).get(base_name)
    if original and original not in keys:
        keys.append(original)
    internal = (encoder_state.get("original_to_internal") or {}).get(base_name)
    if internal and internal not in keys:
        keys.append(internal)
    return keys


def lookup_subject_value(subject_raw: Mapping[str, Any], base_name: str, encoder_state: Mapping[str, Any]) -> Any:
    if not isinstance(subject_raw, Mapping):
        return None
    layers: list[Mapping[str, Any]] = [subject_raw]
    nested = subject_raw.get("raw_values")
    if isinstance(nested, Mapping):
        layers.append(nested)
    for layer in layers:
        for key in _base_lookup_keys(base_name, encoder_state):
            if key in layer:
                return layer[key]
    return None


def apply_encoder(
    base_frame: pd.DataFrame,
    encoder_state: Mapping[str, Any],
    *,
    origin: str = "c02.transform_subject",
    row_ids: Optional[Sequence[str]] = None,
    allow_imputation: bool = True,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply a frozen encoder. Unknown/missing never become the reference level."""
    issues: List[Dict[str, Any]] = []
    row_flags: List[Dict[str, Any]] = []
    column_order: List[str] = list(encoder_state.get("column_order") or [])
    locale = encoder_state.get("locale") or "auto"
    missing_policy = encoder_state.get("missing_policy") or {}
    pred_method = missing_policy.get("predictors")
    unknown_policy = encoder_state.get("unknown_category_policy") or "unsupported"

    n_rows = len(base_frame)
    if row_ids is None:
        if "row_id" in base_frame.columns:
            row_ids = [str(v) for v in base_frame["row_id"].tolist()]
        else:
            row_ids = [str(i) for i in base_frame.index]
    row_ids = [str(r) for r in row_ids]

    data: Dict[str, List[Any]] = {name: [np.nan] * n_rows for name in column_order}

    for i in range(n_rows):
        rid = row_ids[i] if i < len(row_ids) else str(i)
        flags = {
            "row_id": rid,
            "missing_predictors": [],
            "unknown_categories": [],
            "imputed": [],
            "unparseable": [],
            "unsupported": False,
        }
        row = base_frame.iloc[i]
        for spec_bv in encoder_state.get("base_variables") or []:
            name = spec_bv["original_name"]
            raw = row[name] if name in base_frame.columns else None
            if spec_bv["kind"] == "numeric":
                internal = spec_bv["internal_name"]
                if is_missing(raw):
                    if allow_imputation and pred_method in {"mean", "median"} and spec_bv.get("impute_value") is not None:
                        data[internal][i] = float(spec_bv["impute_value"])
                        flags["imputed"].append(name)
                        issues.append(
                            make_issue(
                                ISSUE_PREDICTOR_IMPUTED,
                                "info",
                                origin,
                                (
                                    f"Preditor numérico '{name}' ausente; preenchido com "
                                    f"{pred_method} do treino."
                                ),
                                affected_ids=[rid, name],
                                evidence={
                                    "impute_value": spec_bv.get("impute_value"),
                                    "method": pred_method,
                                },
                            )
                        )
                    else:
                        data[internal][i] = np.nan
                        flags["missing_predictors"].append(name)
                        flags["unsupported"] = True
                        issues.append(
                            make_issue(
                                ISSUE_PREDICTOR_MISSING,
                                "error",
                                origin,
                                (
                                    f"Preditor numérico '{name}' ausente; ausência não é "
                                    "categoria de referência nem valor imputado (política "
                                    f"{pred_method!r})."
                                ),
                                affected_ids=[rid, name],
                                evidence={"policy": pred_method},
                            )
                        )
                    continue
                number = parse_numeric(raw, spec_bv.get("locale") or locale)
                if number is None:
                    data[internal][i] = np.nan
                    flags["unparseable"].append(name)
                    flags["unsupported"] = True
                    issues.append(
                        make_issue(
                            ISSUE_UNPARSEABLE_NUMERIC,
                            "error",
                            origin,
                            f"Valor {raw!r} de '{name}' não é numérico no locale {locale}.",
                            affected_ids=[rid, name],
                            evidence={"raw": None if is_missing(raw) else str(raw)},
                        )
                    )
                else:
                    data[internal][i] = float(number)
                continue

            # categorical group: atomic indicators; reference => all zeros;
            # missing/unknown => NaN on the whole group, never all-zeros.
            grouping = spec_bv.get("grouping") or {}
            mapping = grouping.get("mapping") or {}
            label = _apply_group_map(_stringify_category(raw), mapping)
            indicators: List[str] = list(spec_bv.get("indicator_columns") or [])
            levels_ind: List[str] = list(spec_bv.get("indicator_levels") or [])
            seen = set(spec_bv.get("categories") or [])
            reference = spec_bv.get("reference_category")

            if label is None:
                for internal in indicators:
                    data[internal][i] = np.nan
                flags["missing_predictors"].append(name)
                flags["unsupported"] = True
                issues.append(
                    make_issue(
                        ISSUE_PREDICTOR_MISSING,
                        "error",
                        origin,
                        (
                            f"Preditor categórico '{name}' ausente; ausência não é a "
                            f"categoria de referência {reference!r}."
                        ),
                        affected_ids=[rid, name],
                        evidence={
                            "reference_category": reference,
                            "categories": list(spec_bv.get("categories") or []),
                        },
                    )
                )
                continue

            if label not in seen:
                for internal in indicators:
                    data[internal][i] = np.nan
                flags["unknown_categories"].append({name: label})
                flags["unsupported"] = True
                policy = spec_bv.get("unknown_policy") or unknown_policy
                issues.append(
                    make_issue(
                        ISSUE_UNKNOWN_CATEGORY,
                        "error",
                        origin,
                        (
                            f"Categoria {label!r} de '{name}' não foi vista no treino; "
                            f"política {policy!r} (nunca recodificada como referência "
                            f"{reference!r})."
                        ),
                        affected_ids=[rid, name, label],
                        evidence={
                            "value": label,
                            "reference_category": reference,
                            "seen": sorted(seen),
                            "policy": policy,
                        },
                    )
                )
                continue

            for internal, level in zip(indicators, levels_ind):
                data[internal][i] = 1.0 if label == level else 0.0

        row_flags.append(flags)

    X = pd.DataFrame(data, columns=column_order)
    X.index = pd.Index(row_ids, name="row_id")
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    return X, issues, row_flags


def diagnose_design_matrix(
    X: pd.DataFrame,
    encoder_state: Mapping[str, Any],
    origin: str = "c02.fit_dataset",
) -> List[Dict[str, Any]]:
    """Constants and collinear columns stay in X; they are diagnosed, not dropped."""
    issues: List[Dict[str, Any]] = []
    if X is None or X.empty or len(X.columns) == 0:
        return issues

    numeric = X.apply(pd.to_numeric, errors="coerce")
    constant_cols: List[str] = []
    for col in numeric.columns:
        series = numeric[col]
        observed = series.dropna()
        if observed.empty:
            continue
        if observed.nunique() <= 1:
            constant_cols.append(col)
            value = float(observed.iloc[0])
            issues.append(
                make_issue(
                    ISSUE_CONSTANT_COLUMN,
                    "warning",
                    origin,
                    f"Coluna '{col}' é constante na matriz de treino.",
                    affected_ids=[col],
                    evidence={"value": value, "variance": 0.0},
                )
            )

    varying = [c for c in numeric.columns if c not in constant_cols]
    if len(varying) >= 2:
        sub = numeric[varying]
        corr = sub.corr().abs()
        reported = set()
        for i, a in enumerate(varying):
            for b in varying[i + 1 :]:
                coeff = corr.loc[a, b]
                if pd.notna(coeff) and float(coeff) >= (1.0 - 1e-10):
                    pair = tuple(sorted((a, b)))
                    if pair in reported:
                        continue
                    reported.add(pair)
                    issues.append(
                        make_issue(
                            ISSUE_COLLINEAR_COLUMNS,
                            "warning",
                            origin,
                            f"Colunas '{a}' e '{b}' são colineares (correlação ~1) no treino.",
                            affected_ids=[a, b],
                            evidence={"pair": [a, b], "abs_corr": float(coeff)},
                        )
                    )
        values = sub.dropna().to_numpy(dtype=float)
        if values.size and values.shape[0] > 0 and values.shape[1] > 0:
            rank = int(np.linalg.matrix_rank(values, tol=1e-8))
            if rank < values.shape[1] and not reported:
                issues.append(
                    make_issue(
                        ISSUE_COLLINEAR_COLUMNS,
                        "warning",
                        origin,
                        (
                            "A matriz de treino tem posto deficiente "
                            f"(posto {rank} < {values.shape[1]} colunas)."
                        ),
                        affected_ids=list(varying),
                        evidence={"rank": rank, "n_columns": int(values.shape[1])},
                    )
                )
    return issues


def finalize_parameter_accounting(
    feature_schema: Dict[str, Any],
    X: pd.DataFrame,
    n_effective: int,
) -> Dict[str, Any]:
    accounting = dict(feature_schema.get("parameter_accounting") or {})
    accounting["n_effective"] = int(n_effective)
    accounting.pop("n_effective_placeholder", None)
    if X is not None and not X.empty and len(X.columns) > 0:
        mat = X.apply(pd.to_numeric, errors="coerce").dropna().to_numpy(dtype=float)
        if mat.size and mat.shape[0] > 0:
            rank_slopes = int(np.linalg.matrix_rank(mat, tol=1e-8))
            with_intercept = np.column_stack([np.ones(mat.shape[0]), mat])
            rank_intercept = int(np.linalg.matrix_rank(with_intercept, tol=1e-8))
            accounting["rank_slopes"] = rank_slopes
            accounting["rank_with_intercept"] = rank_intercept
            accounting["n_columns_in_X"] = int(X.shape[1])
        else:
            accounting["rank_slopes"] = 0
            accounting["rank_with_intercept"] = 0
            accounting["n_columns_in_X"] = int(X.shape[1])
    else:
        accounting["rank_slopes"] = 0
        accounting["rank_with_intercept"] = 0
        accounting["n_columns_in_X"] = 0 if X is None else int(X.shape[1])
    feature_schema["parameter_accounting"] = json_safe(accounting)
    return accounting


def empty_prepared(
    *,
    issues: List[Dict[str, Any]],
    feature_schema: Optional[Dict[str, Any]] = None,
    encoder_state: Optional[Dict[str, Any]] = None,
    sample_ledger: Optional[Dict[str, Any]] = None,
    target_col: str = "",
    target_unit: Any = None,
) -> PreparedDataset:
    schema = feature_schema or {
        "version": FEATURE_SCHEMA_VERSION,
        "columns": {},
        "groups": {},
        "target": {"column": target_col, "unit": target_unit},
        "parameter_accounting": {
            "n_effective": 0,
            "n_quantitative": 0,
            "n_categorical_groups": 0,
            "n_indicator_columns": 0,
            "n_free_slopes": 0,
            "n_free_with_intercept": 1,
            "groups": {},
        },
        "base_variables": {},
    }
    state = encoder_state or {
        "version": ENCODER_STATE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "column_order": [],
        "base_variables": [],
        "missing_policy": {"target": "never_impute", "predictors": None},
        "target": {"column": target_col, "unit": target_unit},
    }
    ledger = sample_ledger or {
        "received": 0,
        "observed_target": 0,
        "prepared": 0,
        "used": 0,
        "excluded": 0,
        "used_row_ids": [],
        "excluded_row_ids": [],
        "exclusions": [],
        "n_effective": 0,
    }
    X = pd.DataFrame(columns=list(schema.get("columns") or {}))
    y = pd.Series(dtype=float, name=target_col or "y")
    sha = dataset_sha256(schema, state, [])
    return PreparedDataset(
        X=X,
        y=y,
        row_ids=[],
        feature_schema=schema,
        encoder_state=json_safe(state),
        sample_ledger=ledger,
        issues=issues,
        dataset_sha256=sha,
        base_frame=pd.DataFrame(),
    )
