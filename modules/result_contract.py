"""MP/1 runtime contract: RequestSpec and ResultSnapshot.

C10 is the sole owner of this module. Peer campaigns consume the structural
format described here; they do not need this file to exist in order to
develop, but production composition in backend/worker.py and backend/api.py
validates and freezes through these entry points.

JSON emitted by freeze_result_snapshot is RFC-8259 strict: no NaN, no
Infinity, no DataFrame/model objects. A non-finite or non-JSON value becomes
an Issue plus JSON null — never 0 and never a false success. value.point is
the model's direct point estimate and is never rebuilt from
arbitration_interval.

Documented defaults applied by validate_request_spec (and only these):
- import_options.locale = "auto"; delimiter/encoding = null when omitted
  inside an otherwise present or synthesized import_options object.
- outlier_policy.mode = "report_only"; reviewed_exclusions = [] when
  outlier_policy is omitted or incomplete.
- evaluation_policy.method = "none" is the documented way to skip C07.

No default fills target_unit with "BRL" / "BRL/m2", reference_date or
inspection_date with today, or candidate_cols=[] with "all columns".
candidate_cols must be present: JSON null means automatic selection by
role; [] is an explicit error (no authorized predictors).

Additive optional RequestSpec fields (documented, not required):
- declared_documentary: {item1_grade, item3_grade} ints 1..3 or null
- search_policy.target_degree: 1|2|3|null
Unknown extra keys are preserved (additive compatibility) and not
reinterpreted.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "MP/1"

ROLE_TARGET = "target"
ROLE_PREDICTOR = "predictor"
ROLE_IDENTIFIER = "identifier"
ROLE_SOURCE = "source"
ROLE_DATE = "date"
ROLE_EXCLUDED = "excluded"
ROLE_VALUES = frozenset(
    {
        ROLE_TARGET,
        ROLE_PREDICTOR,
        ROLE_IDENTIFIER,
        ROLE_SOURCE,
        ROLE_DATE,
        ROLE_EXCLUDED,
    }
)

LOCALE_VALUES = frozenset({"auto", "pt-BR", "en-US"})
MISSING_TARGET_POLICY = "never_impute"
OUTLIER_MODE_DEFAULT = "report_only"
EVALUATION_METHOD_NONE = "none"

ISSUE_SEVERITIES = frozenset({"info", "warning", "error"})
PRECISAO_STATUSES = frozenset({"not_computed", "classified", "unclassified", "error"})
ISSUANCE_STATUSES = frozenset(
    {"draft", "review_required", "ready_for_professional_review"}
)
JOB_STATES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}
)
ARTIFACT_LIFECYCLE_STATES = frozenset({"pending", "running", "ready", "failed"})
ELIGIBILITY_STATUSES = frozenset(
    {"eligible", "review_required", "unsupported", "error"}
)

ALLOWED_ARTIFACT_NAMES = frozenset(
    {"report.pdf", "evidence_manifest.json", "frozen_project.json"}
)

DEGREE_MIN = 1
DEGREE_MAX = 3
MAX_UPLOAD_BYTES_DEFAULT = 20 * 1024 * 1024

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

REQUEST_SPEC_REQUIRED_KEYS = (
    "schema_version",
    "target_col",
    "candidate_cols",
    "roles",
    "units",
    "import_options",
    "missing_policy",
    "outlier_policy",
    "search_policy",
    "evaluation_policy",
    "reference_date",
    "inspection_date",
    "target_unit",
    "applicant",
    "purpose",
)

SNAPSHOT_REQUIRED_KEYS = (
    "schema_version",
    "job_id",
    "project_id",
    "input_sha256",
    "code_sha",
    "reference_date",
    "generated_at",
    "target",
    "value",
    "sample",
    "validation",
    "issues",
    "model",
    "search",
    "alternatives",
    "next_actions",
    "provenance",
)

VALUE_REQUIRED_KEYS = (
    "point",
    "mean_ci80",
    "prediction_interval",
    "arbitration_interval",
    "admissible_interval",
)

SAMPLE_REQUIRED_KEYS = (
    "received",
    "observed_target",
    "prepared",
    "used",
    "excluded",
    "used_row_ids",
    "excluded_row_ids",
)

SEARCH_POLICY_REQUIRED_KEYS = ("mode", "budget", "objective", "seed")
EVALUATION_POLICY_REQUIRED_KEYS = ("method", "partitions", "groups", "seed")

DOCUMENTED_REQUEST_SPEC_DEFAULTS = {
    "import_options": {
        "locale": "auto",
        "delimiter": None,
        "encoding": None,
    },
    "outlier_policy": {
        "mode": OUTLIER_MODE_DEFAULT,
        "reviewed_exclusions": [],
    },
}


class ContractError(ValueError):
    """Structured contract rejection. issues is a list of Issue mappings."""

    def __init__(self, message: str, issues: Optional[Sequence[Mapping[str, Any]]] = None):
        super().__init__(message)
        self.issues = [dict(i) for i in (issues or [])]
        if not self.issues:
            self.issues = [
                make_issue("CONTRACT_ERROR", message, origin="result_contract")
            ]


class RequestSpecError(ContractError):
    pass


class ResultSnapshotError(ContractError):
    pass


def make_issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    origin: str = "result_contract",
    affected_ids: Optional[Sequence[Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> dict:
    if severity not in ISSUE_SEVERITIES:
        raise ValueError(f"invalid issue severity: {severity!r}")
    return {
        "code": str(code),
        "severity": severity,
        "origin": str(origin),
        "message": str(message),
        "affected_ids": [str(x) for x in (affected_ids or [])],
        "evidence": dict(evidence or {}),
    }


def dumps_strict(obj: Any) -> str:
    """RFC-8259 JSON. Raises ValueError on NaN/Infinity."""
    return json.dumps(
        obj,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_strict_default,
    )


def _strict_default(obj: Any) -> Any:
    raise TypeError(f"not JSON-serializable: {type(obj).__name__}")


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def _numpy_scalar_to_python(value: Any) -> Any:
    try:
        import numpy as np
    except Exception:
        return value
    if isinstance(value, np.generic):
        return value.item()
    return value


def _is_pandas_object(value: Any) -> bool:
    try:
        import pandas as pd
    except Exception:
        return False
    if isinstance(value, (pd.DataFrame, pd.Series, pd.Index)):
        return True
    timestamp = getattr(pd, "Timestamp", None)
    if timestamp is not None and isinstance(value, timestamp):
        return True
    period = getattr(pd, "Period", None)
    if period is not None and isinstance(value, period):
        return True
    na = getattr(pd, "NA", None)
    if na is not None and value is na:
        return True
    nat = getattr(pd, "NaT", None)
    if nat is not None and value is nat:
        return True
    return False


def _is_model_object(value: Any) -> bool:
    if value is None:
        return False
    module = getattr(type(value), "__module__", "") or ""
    name = type(value).__name__
    if module.startswith("statsmodels") or module.startswith("sklearn"):
        return True
    if name in {
        "RegressionResults",
        "RegressionResultsWrapper",
        "OLS",
        "OLSResults",
        "Pipeline",
    }:
        return True
    if callable(value) and not isinstance(value, (str, bytes)):
        # Keep dict/list out; functions, methods, and model predict callables
        # must not enter frozen JSON.
        if hasattr(value, "__call__") and not isinstance(value, type):
            qual = getattr(value, "__module__", "") or ""
            if not isinstance(value, Mapping) and not isinstance(value, (list, tuple)):
                # Built-in and user functions / bound methods.
                if hasattr(value, "__func__") or getattr(value, "__name__", None):
                    if module.startswith("builtins") and name in {"builtin_function_or_method"}:
                        return True
                    if type(value).__name__ in {"function", "method", "builtin_function_or_method"}:
                        return True
    return False


def canonicalize_json_value(
    value: Any,
    *,
    path: str = "$",
    issues: Optional[List[dict]] = None,
    origin: str = "result_contract",
) -> Any:
    """Walk a structure into RFC-8259 JSON values.

    Non-finite numbers, pandas objects, and model objects become None and
    append an Issue. Finite numpy scalars become Python int/float.
    """
    if issues is None:
        issues = []

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            issues.append(
                make_issue(
                    "NON_FINITE_NUMBER",
                    f"Non-finite number at {path} replaced with null",
                    origin=origin,
                    evidence={"path": path, "repr": repr(value)},
                )
            )
            return None
        return float(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        issues.append(
            make_issue(
                "NON_JSON_VALUE",
                f"Bytes at {path} replaced with null",
                origin=origin,
                evidence={"path": path, "type": "bytes", "n": len(value)},
            )
        )
        return None
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out[str(key)] = canonicalize_json_value(
                item, path=f"{path}.{key}", issues=issues, origin=origin
            )
        return out
    if isinstance(value, (list, tuple)):
        return [
            canonicalize_json_value(item, path=f"{path}[{i}]", issues=issues, origin=origin)
            for i, item in enumerate(value)
        ]
    if isinstance(value, (datetime, date)):
        # Dates in frozen snapshots must already be strings (generated_at,
        # reference_date). A raw datetime is a non-JSON object.
        issues.append(
            make_issue(
                "NON_JSON_VALUE",
                f"datetime/date object at {path} replaced with null",
                origin=origin,
                evidence={"path": path, "type": type(value).__name__},
            )
        )
        return None

    coerced = _numpy_scalar_to_python(value)
    if coerced is not value:
        return canonicalize_json_value(coerced, path=path, issues=issues, origin=origin)

    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            issues.append(
                make_issue(
                    "NON_JSON_VALUE",
                    f"numpy.ndarray at {path} replaced with null",
                    origin=origin,
                    evidence={"path": path, "shape": list(value.shape)},
                )
            )
            return None
    except Exception:
        pass

    if _is_pandas_object(value) or _is_model_object(value):
        issues.append(
            make_issue(
                "NON_JSON_VALUE",
                f"Non-JSON object {type(value).__name__} at {path} replaced with null",
                origin=origin,
                evidence={"path": path, "type": type(value).__name__,
                          "module": getattr(type(value), "__module__", "")},
            )
        )
        return None

    issues.append(
        make_issue(
            "NON_JSON_VALUE",
            f"Unsupported type {type(value).__name__} at {path} replaced with null",
            origin=origin,
            evidence={"path": path, "type": type(value).__name__},
        )
    )
    return None


def _as_mapping(payload: Any, *, what: str) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    raise ContractError(
        f"{what} must be a mapping",
        [make_issue("TYPE_ERROR", f"{what} must be a mapping, got {type(payload).__name__}")],
    )


def _require_str(value: Any, *, field: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise RequestSpecError(
            f"{field} must be a string",
            [make_issue("TYPE_ERROR", f"{field} must be a string, got {type(value).__name__}",
                        evidence={"field": field})],
        )
    if not allow_empty and not value.strip():
        raise RequestSpecError(
            f"{field} must be a non-empty string",
            [make_issue("MISSING_FIELD", f"{field} must be a non-empty string",
                        evidence={"field": field})],
        )
    return value


def _parse_iso_date(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestSpecError(
            f"{field} must be an ISO date string or null",
            [make_issue("TYPE_ERROR", f"{field} must be ISO-date or null",
                        evidence={"field": field, "type": type(value).__name__})],
        )
    if not _ISO_DATE.match(value):
        raise RequestSpecError(
            f"{field} is not an ISO date (YYYY-MM-DD)",
            [make_issue("INVALID_DATE", f"{field}={value!r} is not YYYY-MM-DD",
                        evidence={"field": field, "value": value})],
        )
    year, month, day = (int(p) for p in value.split("-"))
    try:
        date(year, month, day)
    except ValueError as exc:
        raise RequestSpecError(
            f"{field} is not a real calendar date",
            [make_issue("INVALID_DATE", f"{field}={value!r}: {exc}",
                        evidence={"field": field, "value": value})],
        ) from exc
    return value


def _validate_degree(value: Any, *, field: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestSpecError(
            f"{field} must be an integer 1..3 or null",
            [make_issue("TYPE_ERROR", f"{field} must be int 1..3 or null",
                        evidence={"field": field, "value": repr(value)})],
        )
    if value < DEGREE_MIN or value > DEGREE_MAX:
        raise RequestSpecError(
            f"{field} out of range",
            [make_issue(
                "DEGREE_OUT_OF_RANGE",
                f"{field}={value} is outside {DEGREE_MIN}..{DEGREE_MAX}",
                evidence={"field": field, "value": value,
                          "min": DEGREE_MIN, "max": DEGREE_MAX},
            )],
        )
    return value


def empty_value_block() -> dict:
    """value object with the exact ResultSnapshot / CandidateAssessment shape."""
    return {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }


def _validate_interval(value: Any, *, field: str, issues: List[dict]) -> Optional[dict]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        issues.append(
            make_issue("TYPE_ERROR", f"{field} must be an object with lower/upper or null",
                       evidence={"field": field})
        )
        raise ResultSnapshotError(f"{field} must be a mapping or null", issues)
    lower = value.get("lower")
    upper = value.get("upper")
    out = dict(value)
    for bound_name, bound in (("lower", lower), ("upper", upper)):
        if bound is None or not _is_finite_number(bound):
            issues.append(
                make_issue(
                    "NON_FINITE_NUMBER",
                    f"{field}.{bound_name} is not a finite number; interval set to null",
                    evidence={"field": field, "bound": bound_name, "repr": repr(bound)},
                )
            )
            return None
        if isinstance(bound, float):
            out[bound_name] = float(bound)
        else:
            out[bound_name] = int(bound)
    return out


def fill_preview_spec(payload: Any) -> dict:
    """Preview RequestSpec: target_col may be empty; structural defaults only.

    Does not invent BRL, today's date, or candidate_cols=[]→all. Used by
    POST /preview so the first file view works before the user picks a target.
    """
    raw = dict(payload) if isinstance(payload, Mapping) else {}
    raw.setdefault("schema_version", SCHEMA_VERSION)
    if raw.get("target_col") is None:
        raw["target_col"] = ""
    if "candidate_cols" not in raw:
        raw["candidate_cols"] = None
    raw.setdefault("roles", {})
    raw.setdefault("units", {})
    raw.setdefault("import_options", {"locale": "auto", "delimiter": None, "encoding": None})
    raw.setdefault("missing_policy", {"target": "never_impute", "predictors": "complete_case"})
    raw.setdefault("outlier_policy", {"mode": OUTLIER_MODE_DEFAULT, "reviewed_exclusions": []})
    raw.setdefault(
        "search_policy",
        {"mode": "exact", "budget": 64, "objective": "aic", "seed": 0},
    )
    raw.setdefault(
        "evaluation_policy",
        {"method": EVALUATION_METHOD_NONE, "partitions": None, "groups": None, "seed": 0},
    )
    raw.setdefault("reference_date", None)
    raw.setdefault("inspection_date", None)
    raw.setdefault("target_unit", "")
    raw.setdefault("applicant", "")
    raw.setdefault("purpose", "preview")
    return validate_request_spec(raw, allow_empty_target=True)


def validate_request_spec(payload: Any, *, allow_empty_target: bool = False) -> dict:
    """Validate and normalize a RequestSpec mapping.

    Returns a new dict. Raises RequestSpecError with .issues on rejection.
    Does not invent BRL, today's date, or candidate_cols from silence.
    """
    issues: List[dict] = []
    try:
        raw = _as_mapping(payload, what="RequestSpec")
    except ContractError as exc:
        raise RequestSpecError(str(exc), exc.issues) from exc
    spec = dict(raw)

    if spec.get("schema_version") != SCHEMA_VERSION:
        raise RequestSpecError(
            "schema_version must be MP/1",
            [make_issue(
                "SCHEMA_VERSION",
                f"schema_version must be {SCHEMA_VERSION!r}, got {spec.get('schema_version')!r}",
            )],
        )

    missing = [k for k in REQUEST_SPEC_REQUIRED_KEYS if k not in spec]
    # import_options / outlier_policy may be synthesized from documented defaults.
    synthesizable = {"import_options", "outlier_policy"}
    hard_missing = [k for k in missing if k not in synthesizable]
    if hard_missing:
        raise RequestSpecError(
            "RequestSpec missing required keys",
            [make_issue(
                "MISSING_FIELD",
                f"Missing required keys: {', '.join(hard_missing)}",
                evidence={"missing": hard_missing},
            )],
        )

    raw_target = spec.get("target_col")
    if raw_target is None and allow_empty_target:
        spec["target_col"] = ""
    else:
        spec["target_col"] = _require_str(
            raw_target, field="target_col", allow_empty=allow_empty_target
        )

    candidate_cols = spec.get("candidate_cols")
    if candidate_cols is None:
        spec["candidate_cols"] = None
    elif isinstance(candidate_cols, list):
        if len(candidate_cols) == 0:
            raise RequestSpecError(
                "candidate_cols=[] authorizes no predictors",
                [make_issue(
                    "CANDIDATE_COLS_EMPTY",
                    "candidate_cols=[] means no authorized predictors, never all columns",
                    evidence={"candidate_cols": []},
                )],
            )
        cleaned = []
        for i, col in enumerate(candidate_cols):
            if not isinstance(col, str) or not col:
                raise RequestSpecError(
                    "candidate_cols entries must be non-empty strings",
                    [make_issue(
                        "TYPE_ERROR",
                        f"candidate_cols[{i}] must be a non-empty string",
                        evidence={"index": i, "value": repr(col)},
                    )],
                )
            cleaned.append(col)
        spec["candidate_cols"] = cleaned
    else:
        raise RequestSpecError(
            "candidate_cols must be null or a list of strings",
            [make_issue(
                "TYPE_ERROR",
                f"candidate_cols must be null or list, got {type(candidate_cols).__name__}",
            )],
        )

    roles = spec.get("roles")
    if not isinstance(roles, Mapping):
        raise RequestSpecError(
            "roles must be a mapping",
            [make_issue("TYPE_ERROR", "roles must be a mapping of column → role")],
        )
    normalized_roles = {}
    for col, role in roles.items():
        col_s = str(col)
        if role not in ROLE_VALUES:
            raise RequestSpecError(
                "invalid role",
                [make_issue(
                    "INVALID_ROLE",
                    f"roles[{col_s!r}]={role!r} is not a known role",
                    evidence={"column": col_s, "role": role,
                              "allowed": sorted(ROLE_VALUES)},
                )],
            )
        normalized_roles[col_s] = role
    if spec["target_col"]:
        if spec["target_col"] not in normalized_roles:
            raise RequestSpecError(
                "target_col must be declared in roles as target",
                [make_issue(
                    "TARGET_ROLE_MISSING",
                    f"roles must include {spec['target_col']!r} with role 'target' before cleaning",
                    evidence={"target_col": spec["target_col"]},
                )],
            )
        if normalized_roles[spec["target_col"]] != ROLE_TARGET:
            raise RequestSpecError(
                "target_col role must be target",
                [make_issue(
                    "TARGET_ROLE_MISSING",
                    f"roles[{spec['target_col']!r}] must be 'target'",
                    evidence={"target_col": spec["target_col"],
                              "role": normalized_roles[spec["target_col"]]},
                )],
            )
    spec["roles"] = normalized_roles

    units = spec.get("units")
    if not isinstance(units, Mapping):
        raise RequestSpecError(
            "units must be a mapping",
            [make_issue("TYPE_ERROR", "units must be a mapping")],
        )
    spec["units"] = {str(k): (None if v is None else str(v)) for k, v in units.items()}

    import_options = spec.get("import_options")
    if import_options is None:
        import_options = dict(DOCUMENTED_REQUEST_SPEC_DEFAULTS["import_options"])
        issues.append(
            make_issue(
                "DEFAULT_APPLIED",
                "import_options omitted; documented default locale=auto applied",
                severity="info",
                evidence={"default": import_options},
            )
        )
    if not isinstance(import_options, Mapping):
        raise RequestSpecError(
            "import_options must be a mapping",
            [make_issue("TYPE_ERROR", "import_options must be a mapping")],
        )
    locale = import_options.get("locale", "auto")
    if locale not in LOCALE_VALUES:
        raise RequestSpecError(
            "import_options.locale invalid",
            [make_issue(
                "INVALID_LOCALE",
                f"import_options.locale must be one of {sorted(LOCALE_VALUES)}",
                evidence={"locale": locale},
            )],
        )
    delimiter = import_options.get("delimiter", None)
    encoding = import_options.get("encoding", None)
    if delimiter is not None and not isinstance(delimiter, str):
        raise RequestSpecError(
            "import_options.delimiter must be string or null",
            [make_issue("TYPE_ERROR", "import_options.delimiter must be string or null")],
        )
    if encoding is not None and not isinstance(encoding, str):
        raise RequestSpecError(
            "import_options.encoding must be string or null",
            [make_issue("TYPE_ERROR", "import_options.encoding must be string or null")],
        )
    spec["import_options"] = {
        "locale": locale,
        "delimiter": delimiter,
        "encoding": encoding,
    }

    missing_policy = spec.get("missing_policy")
    if not isinstance(missing_policy, Mapping):
        raise RequestSpecError(
            "missing_policy must be a declared mapping",
            [make_issue(
                "MISSING_POLICY_REQUIRED",
                "missing_policy must distinguish target (never_impute) from predictors",
            )],
        )
    target_policy = missing_policy.get("target")
    predictors_policy = missing_policy.get("predictors")
    if target_policy != MISSING_TARGET_POLICY:
        raise RequestSpecError(
            "missing target values must never be imputed",
            [make_issue(
                "TARGET_IMPUTATION_FORBIDDEN",
                "missing_policy.target must be 'never_impute'",
                evidence={"target": target_policy},
            )],
        )
    if not isinstance(predictors_policy, str) or not predictors_policy:
        raise RequestSpecError(
            "missing_policy.predictors must be a declared method",
            [make_issue(
                "PREDICTOR_MISSING_POLICY_REQUIRED",
                "missing_policy.predictors must be 'complete_case' or an explicit method fitted on train",
                evidence={"predictors": predictors_policy},
            )],
        )
    spec["missing_policy"] = {
        **dict(missing_policy),
        "target": MISSING_TARGET_POLICY,
        "predictors": predictors_policy,
    }

    outlier_policy = spec.get("outlier_policy")
    if outlier_policy is None:
        outlier_policy = dict(DOCUMENTED_REQUEST_SPEC_DEFAULTS["outlier_policy"])
        issues.append(
            make_issue(
                "DEFAULT_APPLIED",
                "outlier_policy omitted; documented default mode=report_only applied",
                severity="info",
                evidence={"default": outlier_policy},
            )
        )
    if not isinstance(outlier_policy, Mapping):
        raise RequestSpecError(
            "outlier_policy must be a mapping",
            [make_issue("TYPE_ERROR", "outlier_policy must be a mapping")],
        )
    mode = outlier_policy.get("mode", OUTLIER_MODE_DEFAULT)
    if not isinstance(mode, str) or not mode:
        raise RequestSpecError(
            "outlier_policy.mode must be a non-empty string",
            [make_issue("TYPE_ERROR", "outlier_policy.mode must be a string")],
        )
    reviewed = outlier_policy.get("reviewed_exclusions", [])
    if reviewed is None:
        reviewed = []
    if not isinstance(reviewed, list):
        raise RequestSpecError(
            "outlier_policy.reviewed_exclusions must be a list",
            [make_issue("TYPE_ERROR", "outlier_policy.reviewed_exclusions must be a list")],
        )
    spec["outlier_policy"] = {
        **dict(outlier_policy),
        "mode": mode,
        "reviewed_exclusions": reviewed,
    }

    search_policy = spec.get("search_policy")
    if not isinstance(search_policy, Mapping):
        raise RequestSpecError(
            "search_policy must be a declared mapping",
            [make_issue(
                "SEARCH_POLICY_REQUIRED",
                "search_policy must declare mode, budget, objective and seed",
            )],
        )
    missing_search = [k for k in SEARCH_POLICY_REQUIRED_KEYS if k not in search_policy]
    if missing_search:
        raise RequestSpecError(
            "search_policy incomplete",
            [make_issue(
                "SEARCH_POLICY_REQUIRED",
                f"search_policy missing keys: {', '.join(missing_search)}",
                evidence={"missing": missing_search},
            )],
        )
    if not isinstance(search_policy.get("mode"), str) or not search_policy.get("mode"):
        raise RequestSpecError(
            "search_policy.mode must be a non-empty string",
            [make_issue("TYPE_ERROR", "search_policy.mode must be a non-empty string")],
        )
    target_degree = None
    if "target_degree" in search_policy:
        target_degree = _validate_degree(
            search_policy.get("target_degree"), field="search_policy.target_degree"
        )
    spec["search_policy"] = dict(search_policy)
    if "target_degree" in search_policy:
        spec["search_policy"]["target_degree"] = target_degree

    evaluation_policy = spec.get("evaluation_policy")
    if not isinstance(evaluation_policy, Mapping):
        raise RequestSpecError(
            "evaluation_policy must be a declared mapping",
            [make_issue(
                "EVALUATION_POLICY_REQUIRED",
                "evaluation_policy must declare method, partitions, groups and seed",
            )],
        )
    evaluation_policy = dict(evaluation_policy)
    evaluation_policy.setdefault("partitions", None)
    evaluation_policy.setdefault("groups", None)
    missing_eval = [k for k in EVALUATION_POLICY_REQUIRED_KEYS if k not in evaluation_policy]
    if missing_eval:
        raise RequestSpecError(
            "evaluation_policy incomplete",
            [make_issue(
                "EVALUATION_POLICY_REQUIRED",
                f"evaluation_policy missing keys: {', '.join(missing_eval)}",
                evidence={"missing": missing_eval},
            )],
        )
    method = evaluation_policy.get("method")
    if not isinstance(method, str) or not method:
        raise RequestSpecError(
            "evaluation_policy.method must be a non-empty string",
            [make_issue(
                "TYPE_ERROR",
                "evaluation_policy.method must be a non-empty string "
                f"(use {EVALUATION_METHOD_NONE!r} to skip C07)",
            )],
        )
    spec["evaluation_policy"] = dict(evaluation_policy)

    spec["reference_date"] = _parse_iso_date(spec.get("reference_date"), field="reference_date")
    spec["inspection_date"] = _parse_iso_date(spec.get("inspection_date"), field="inspection_date")
    spec["target_unit"] = _require_str(spec.get("target_unit"), field="target_unit", allow_empty=True)
    spec["applicant"] = _require_str(spec.get("applicant"), field="applicant", allow_empty=True)
    spec["purpose"] = _require_str(spec.get("purpose"), field="purpose", allow_empty=True)

    if spec["target_unit"] == "":
        issues.append(
            make_issue(
                "UNIT_PENDING",
                "target_unit is empty and remains pending; BRL/BRL/m2 were not assumed",
                severity="info",
                evidence={"target_unit": ""},
            )
        )
    if spec["reference_date"] is None:
        issues.append(
            make_issue(
                "DATE_PENDING",
                "reference_date is null and remains pending; today's date was not assumed",
                severity="info",
                evidence={"field": "reference_date"},
            )
        )

    declared = spec.get("declared_documentary")
    if declared is not None:
        if not isinstance(declared, Mapping):
            raise RequestSpecError(
                "declared_documentary must be a mapping",
                [make_issue("TYPE_ERROR", "declared_documentary must be a mapping")],
            )
        item1 = declared.get("item1_grade")
        item3 = declared.get("item3_grade")
        spec["declared_documentary"] = {
            **dict(declared),
            "item1_grade": _validate_degree(item1, field="declared_documentary.item1_grade"),
            "item3_grade": _validate_degree(item3, field="declared_documentary.item3_grade"),
        }

    spec["_applied_defaults"] = issues
    return spec


def request_spec_for_peers(spec: Mapping[str, Any]) -> dict:
    """Strip C10 bookkeeping keys before handing RequestSpec to peers."""
    return {k: v for k, v in spec.items() if not str(k).startswith("_")}


def _validate_issue(item: Any, *, index: int) -> dict:
    if not isinstance(item, Mapping):
        raise ResultSnapshotError(
            "issues entries must be mappings",
            [make_issue("TYPE_ERROR", f"issues[{index}] must be a mapping")],
        )
    severity = item.get("severity")
    if severity not in ISSUE_SEVERITIES:
        raise ResultSnapshotError(
            "invalid issue severity",
            [make_issue(
                "INVALID_ISSUE",
                f"issues[{index}].severity must be one of {sorted(ISSUE_SEVERITIES)}",
                evidence={"index": index, "severity": severity},
            )],
        )
    for key in ("code", "origin", "message"):
        if not isinstance(item.get(key), str) or item.get(key) == "":
            raise ResultSnapshotError(
                f"issues[{index}].{key} must be a non-empty string",
                [make_issue("INVALID_ISSUE", f"issues[{index}].{key} required")],
            )
    affected = item.get("affected_ids", [])
    evidence = item.get("evidence", {})
    if not isinstance(affected, list):
        raise ResultSnapshotError(
            "affected_ids must be a list",
            [make_issue("TYPE_ERROR", f"issues[{index}].affected_ids must be a list")],
        )
    if not isinstance(evidence, Mapping):
        raise ResultSnapshotError(
            "evidence must be a mapping",
            [make_issue("TYPE_ERROR", f"issues[{index}].evidence must be a mapping")],
        )
    return {
        "code": item["code"],
        "severity": severity,
        "origin": item["origin"],
        "message": item["message"],
        "affected_ids": [str(x) for x in affected],
        "evidence": dict(evidence),
    }


def _validate_value_block(value: Any, issues: List[dict]) -> dict:
    if not isinstance(value, Mapping):
        raise ResultSnapshotError(
            "value must be a mapping",
            [make_issue("TYPE_ERROR", "value must be a mapping with point and intervals")],
        )
    missing = [k for k in VALUE_REQUIRED_KEYS if k not in value]
    if missing:
        raise ResultSnapshotError(
            "value missing keys",
            [make_issue("MISSING_FIELD", f"value missing keys: {', '.join(missing)}",
                        evidence={"missing": missing})],
        )
    point = value.get("point")
    if point is not None and not _is_finite_number(point):
        issues.append(
            make_issue(
                "NON_FINITE_NUMBER",
                "value.point is not a finite number; stored as null (not 0)",
                evidence={"repr": repr(point)},
            )
        )
        point = None
    elif isinstance(point, float):
        point = float(point)
    elif isinstance(point, int) and not isinstance(point, bool):
        point = int(point)

    out = {
        "point": point,
        "mean_ci80": _validate_interval(value.get("mean_ci80"), field="value.mean_ci80", issues=issues),
        "prediction_interval": _validate_interval(
            value.get("prediction_interval"), field="value.prediction_interval", issues=issues
        ),
        "arbitration_interval": _validate_interval(
            value.get("arbitration_interval"), field="value.arbitration_interval", issues=issues
        ),
        "admissible_interval": _validate_interval(
            value.get("admissible_interval"), field="value.admissible_interval", issues=issues
        ),
    }
    # Extra additive keys on value are preserved if JSON-canonical.
    for key, item in value.items():
        if key not in out:
            out[key] = item
    return out


def freeze_result_snapshot(payload: Any) -> dict:
    """Canonicalize, validate and freeze a ResultSnapshot.

    Returns a new dict that json.dumps(..., allow_nan=False) can emit.
    Never reconstructs value.point from arbitration_interval.
    Never writes artifact bytes or artifact content hashes into the snapshot
    (those live on the external job/manifest record).
    """
    issues: List[dict] = []
    try:
        raw = _as_mapping(payload, what="ResultSnapshot")
    except ContractError as exc:
        raise ResultSnapshotError(str(exc), exc.issues) from exc

    # Canonicalize first so NaN/pandas/model objects become null + issues
    # before structural validation.
    canonical = canonicalize_json_value(dict(raw), path="$", issues=issues, origin="result_contract")
    if not isinstance(canonical, dict):
        raise ResultSnapshotError(
            "ResultSnapshot vanished during canonicalize",
            issues,
        )

    if canonical.get("schema_version") != SCHEMA_VERSION:
        raise ResultSnapshotError(
            "schema_version must be MP/1",
            issues + [make_issue(
                "SCHEMA_VERSION",
                f"schema_version must be {SCHEMA_VERSION!r}",
            )],
        )

    missing = [k for k in SNAPSHOT_REQUIRED_KEYS if k not in canonical]
    if missing:
        raise ResultSnapshotError(
            "ResultSnapshot missing required keys",
            issues + [make_issue(
                "MISSING_FIELD",
                f"Missing required keys: {', '.join(missing)}",
                evidence={"missing": missing},
            )],
        )

    job_id = canonical.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise ResultSnapshotError(
            "job_id must be a non-empty string",
            issues + [make_issue("TYPE_ERROR", "job_id must be a non-empty string")],
        )
    project_id = canonical.get("project_id")
    if project_id is not None and not isinstance(project_id, str):
        raise ResultSnapshotError(
            "project_id must be string or null",
            issues + [make_issue("TYPE_ERROR", "project_id must be string or null")],
        )
    for digest_field in ("input_sha256", "code_sha"):
        if not isinstance(canonical.get(digest_field), str) or not canonical.get(digest_field):
            raise ResultSnapshotError(
                f"{digest_field} must be a non-empty string",
                issues + [make_issue("TYPE_ERROR", f"{digest_field} must be a non-empty string")],
            )
    reference_date = canonical.get("reference_date")
    if reference_date is not None:
        if not isinstance(reference_date, str) or not _ISO_DATE.match(reference_date):
            raise ResultSnapshotError(
                "reference_date must be YYYY-MM-DD or null",
                issues + [make_issue("INVALID_DATE", "reference_date must be YYYY-MM-DD or null")],
            )
    generated_at = canonical.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ResultSnapshotError(
            "generated_at must be an ISO-8601 string",
            issues + [make_issue("TYPE_ERROR", "generated_at must be an ISO-8601 string")],
        )

    target = canonical.get("target")
    if not isinstance(target, Mapping):
        raise ResultSnapshotError(
            "target must be a mapping",
            issues + [make_issue("TYPE_ERROR", "target must be {column, unit, estimand}")],
        )
    for key in ("column", "unit", "estimand"):
        if not isinstance(target.get(key), str):
            raise ResultSnapshotError(
                f"target.{key} must be a string",
                issues + [make_issue("TYPE_ERROR", f"target.{key} must be a string")],
            )
    target_out = {
        "column": target["column"],
        "unit": target["unit"],
        "estimand": target["estimand"],
        **{k: v for k, v in target.items() if k not in {"column", "unit", "estimand"}},
    }

    value_out = _validate_value_block(canonical.get("value"), issues)

    sample = canonical.get("sample")
    if not isinstance(sample, Mapping):
        raise ResultSnapshotError(
            "sample must be a mapping",
            issues + [make_issue("TYPE_ERROR", "sample must be a mapping")],
        )
    missing_sample = [k for k in SAMPLE_REQUIRED_KEYS if k not in sample]
    if missing_sample:
        raise ResultSnapshotError(
            "sample missing keys",
            issues + [make_issue(
                "MISSING_FIELD",
                f"sample missing keys: {', '.join(missing_sample)}",
                evidence={"missing": missing_sample},
            )],
        )
    sample_out = dict(sample)
    for count_key in ("received", "observed_target", "prepared", "used", "excluded"):
        n = sample.get(count_key)
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ResultSnapshotError(
                f"sample.{count_key} must be a non-negative int",
                issues + [make_issue(
                    "TYPE_ERROR",
                    f"sample.{count_key} must be a non-negative int",
                    evidence={"value": repr(n)},
                )],
            )
        sample_out[count_key] = int(n)
    for id_key in ("used_row_ids", "excluded_row_ids"):
        ids = sample.get(id_key)
        if not isinstance(ids, list):
            raise ResultSnapshotError(
                f"sample.{id_key} must be a list",
                issues + [make_issue("TYPE_ERROR", f"sample.{id_key} must be a list")],
            )
        sample_out[id_key] = [str(x) for x in ids]

    validation = canonical.get("validation")
    if not isinstance(validation, Mapping):
        raise ResultSnapshotError(
            "validation must be a mapping",
            issues + [make_issue("TYPE_ERROR", "validation must be a mapping")],
        )
    for key in ("fundamentacao", "precisao", "statistical", "documentary", "issuance"):
        if key not in validation:
            raise ResultSnapshotError(
                f"validation.{key} required",
                issues + [make_issue("MISSING_FIELD", f"validation.{key} required")],
            )
    precisao = validation.get("precisao")
    if not isinstance(precisao, Mapping) or precisao.get("status") not in PRECISAO_STATUSES:
        raise ResultSnapshotError(
            "validation.precisao.status invalid",
            issues + [make_issue(
                "INVALID_PRECISAO_STATUS",
                f"precisao.status must be one of {sorted(PRECISAO_STATUSES)}",
            )],
        )
    issuance = validation.get("issuance")
    if not isinstance(issuance, Mapping) or issuance.get("status") not in ISSUANCE_STATUSES:
        raise ResultSnapshotError(
            "validation.issuance.status invalid",
            issues + [make_issue(
                "INVALID_ISSUANCE_STATUS",
                f"issuance.status must be one of {sorted(ISSUANCE_STATUSES)}",
            )],
        )
    reasons = issuance.get("reasons")
    if not isinstance(reasons, list):
        raise ResultSnapshotError(
            "issuance.reasons must be a list",
            issues + [make_issue("TYPE_ERROR", "issuance.reasons must be a list")],
        )
    # Documentary declared scores are never treated as verified proof and
    # never authorize automatic issuance of a laudo.
    if issuance.get("status") == "ready_for_professional_review":
        # Allowed as a status name, but C10 never auto-promotes to an
        # approved report. The status is review readiness, not approval.
        pass

    validation_out = {
        "fundamentacao": dict(validation["fundamentacao"])
        if isinstance(validation["fundamentacao"], Mapping) else validation["fundamentacao"],
        "precisao": dict(precisao),
        "statistical": dict(validation["statistical"])
        if isinstance(validation["statistical"], Mapping) else validation["statistical"],
        "documentary": dict(validation["documentary"])
        if isinstance(validation["documentary"], Mapping) else validation["documentary"],
        "issuance": {"status": issuance["status"], "reasons": list(reasons),
                     **{k: v for k, v in issuance.items() if k not in {"status", "reasons"}}},
        **{k: v for k, v in validation.items()
           if k not in {"fundamentacao", "precisao", "statistical", "documentary", "issuance"}},
    }

    raw_issues = canonical.get("issues")
    if not isinstance(raw_issues, list):
        raise ResultSnapshotError(
            "issues must be a list",
            issues + [make_issue("TYPE_ERROR", "issues must be a list")],
        )
    frozen_issues = [_validate_issue(item, index=i) for i, item in enumerate(raw_issues)]
    frozen_issues.extend(issues)

    model = canonical.get("model")
    if not isinstance(model, Mapping):
        raise ResultSnapshotError(
            "model must be a mapping",
            frozen_issues + [make_issue("TYPE_ERROR", "model must be a mapping")],
        )
    search = canonical.get("search")
    if not isinstance(search, Mapping):
        raise ResultSnapshotError(
            "search must be a mapping",
            frozen_issues + [make_issue("TYPE_ERROR", "search must be a mapping")],
        )
    alternatives = canonical.get("alternatives")
    if not isinstance(alternatives, list):
        raise ResultSnapshotError(
            "alternatives must be a list",
            frozen_issues + [make_issue("TYPE_ERROR", "alternatives must be a list")],
        )
    next_actions = canonical.get("next_actions")
    if not isinstance(next_actions, list):
        raise ResultSnapshotError(
            "next_actions must be a list",
            frozen_issues + [make_issue("TYPE_ERROR", "next_actions must be a list")],
        )
    provenance = canonical.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ResultSnapshotError(
            "provenance must be a mapping",
            frozen_issues + [make_issue("TYPE_ERROR", "provenance must be a mapping")],
        )

    frozen = {
        **canonical,
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "project_id": project_id,
        "input_sha256": canonical["input_sha256"],
        "code_sha": canonical["code_sha"],
        "reference_date": reference_date,
        "generated_at": generated_at,
        "target": target_out,
        "value": value_out,
        "sample": sample_out,
        "validation": validation_out,
        "issues": frozen_issues,
        "model": dict(model),
        "search": dict(search),
        "alternatives": list(alternatives),
        "next_actions": list(next_actions),
        "provenance": dict(provenance),
    }

    # Artifacts and their hashes stay off the frozen snapshot so a later PDF
    # that embeds this snapshot cannot create a self-referential hash.
    frozen.pop("artifacts", None)
    frozen.pop("artifact_states", None)
    frozen.pop("report_pdf_base64", None)

    try:
        dumps_strict(frozen)
    except (TypeError, ValueError) as exc:
        raise ResultSnapshotError(
            "frozen snapshot is not strict JSON",
            frozen_issues + [make_issue(
                "STRICT_JSON",
                f"json.dumps(allow_nan=False) failed: {exc}",
            )],
        ) from exc

    return frozen


def validate_job_status_progress(progress: Any) -> Optional[float]:
    """progress is null or a number in [0, 1]; never invent a percentage."""
    if progress is None:
        return None
    if not _is_finite_number(progress):
        return None
    value = float(progress)
    if value < 0.0 or value > 1.0:
        raise ContractError(
            "progress out of range",
            [make_issue(
                "PROGRESS_OUT_OF_RANGE",
                "progress must be null or in [0, 1]",
                evidence={"progress": value},
            )],
        )
    return value


def is_evaluation_requested(request_spec: Mapping[str, Any]) -> bool:
    method = (request_spec.get("evaluation_policy") or {}).get("method")
    if not method:
        return False
    return str(method) not in {EVALUATION_METHOD_NONE, "not_requested", "skip"}


def subject_numeric_values_finite(subject: Any) -> Tuple[bool, List[dict]]:
    """Reject NaN/inf in a subject mapping before a job is created."""
    issues: List[dict] = []
    if subject is None:
        return True, issues
    if not isinstance(subject, Mapping):
        return False, [make_issue("TYPE_ERROR", "subject_json must decode to a mapping")]

    def walk(node: Any, path: str) -> None:
        if node is None or isinstance(node, (str, bool)):
            return
        if isinstance(node, float) and not math.isfinite(node):
            issues.append(
                make_issue(
                    "NON_FINITE_NUMBER",
                    f"Non-finite number in subject at {path}",
                    evidence={"path": path, "repr": repr(node)},
                )
            )
            return
        if isinstance(node, Mapping):
            for key, item in node.items():
                walk(item, f"{path}.{key}")
            return
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
            return
        coerced = _numpy_scalar_to_python(node)
        if coerced is not node:
            walk(coerced, path)

    walk(subject, "$")
    return len(issues) == 0, issues
