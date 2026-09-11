"""Market ingest for C01: read, normalize, then decide disposition.

`ingest_market` is the MP/1 entry point. `DataLoader.load_data` remains the
legacy public adapter and must not invent prices or one-hot-encode here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .config_manager import config
from .import_formats import (
    DEFAULT_MAX_FILE_BYTES,
    SCHEMA_VERSION,
    TabularRead,
    make_issue,
    read_tabular,
)
from .logging_manager import logger
from .results import DataLoadResult, ValidationResult
from .utils import (
    IDENTIFIER_NAME_HINTS,
    NON_QUANTITATIVE_ROLES,
    build_column_map,
    clean_column_name,
    is_missing_token,
    looks_like_non_quantitative,
    parse_numeric_token,
    resolve_column_name,
)

ROW_ID_COLUMN = "row_id"
FATAL_READ_CODES = frozenset(
    {
        "unsupported_format",
        "empty_file",
        "file_size_limit",
        "encoding_error",
        "csv_parse_error",
        "excel_parse_error",
        "excel_engine_missing",
        "missing_request_spec",
    }
)


@dataclass
class InputBundle:
    schema_version: str
    raw_frame: pd.DataFrame
    parsed_frame: pd.DataFrame
    column_map: Dict[str, Any]
    row_ledger: List[Dict[str, Any]]
    input_sha256: str
    issues: List[Dict[str, Any]]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def keys(self):
        return (
            "schema_version",
            "raw_frame",
            "parsed_frame",
            "column_map",
            "row_ledger",
            "input_sha256",
            "issues",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in self.keys()}


def ingest_market(file_bytes: bytes, filename: str, request_spec: Optional[Dict[str, Any]]) -> InputBundle:
    """Read a market file into an InputBundle without inventing observations."""
    input_sha256 = hashlib.sha256(b"" if file_bytes is None else file_bytes).hexdigest()
    issues: List[Dict[str, Any]] = []

    if not isinstance(request_spec, dict):
        issues.append(
            make_issue(
                "missing_request_spec",
                "error",
                "request_spec MP/1 é obrigatório para ingest_market.",
                evidence={"field": "request_spec", "type": type(request_spec).__name__},
            )
        )
        return _empty_bundle(input_sha256, issues)

    spec = _normalize_request_spec(request_spec, issues)
    import_options = spec.get("import_options") or {}
    max_file_bytes = int(import_options.get("max_file_bytes") or DEFAULT_MAX_FILE_BYTES)

    read: TabularRead = read_tabular(
        file_bytes,
        filename,
        import_options=import_options,
        max_file_bytes=max_file_bytes,
    )
    issues.extend(read.issues)
    _log_read(filename, input_sha256, read)

    if read.error is not None:
        return _empty_bundle(input_sha256, issues, column_map=_empty_column_map())

    raw_frame = read.frame.copy()
    column_map = build_column_map(list(raw_frame.columns), reserved=(ROW_ID_COLUMN,))
    if column_map["collisions"]:
        issues.append(
            make_issue(
                "column_name_collision",
                "warning",
                "Colisões de nomes após limpeza: internos desambiguados com sufixo; não resolvido em silêncio.",
                evidence={"collisions": column_map["collisions"]},
            )
        )

    renamed_raw = raw_frame.copy()
    renamed_raw.columns = [entry["internal"] for entry in column_map["entries"]]

    roles = _resolve_roles(spec, column_map, issues)
    target_internal = _resolve_target(spec, column_map, roles, issues)
    authorized = _resolve_candidates(spec, column_map, roles, target_internal, issues)

    n_rows = len(renamed_raw)
    row_ids = [_make_row_id(i, n_rows) for i in range(n_rows)]
    locale = (import_options.get("locale") or "auto")

    missing_before_by_row: List[List[str]] = []
    for i in range(n_rows):
        missing = []
        for internal in renamed_raw.columns:
            if is_missing_token(renamed_raw.iloc[i][internal]):
                missing.append(internal)
        missing_before_by_row.append(missing)

    parsed_columns: Dict[str, List[Any]] = {ROW_ID_COLUMN: list(row_ids)}
    changes_by_row: List[List[Dict[str, Any]]] = [[] for _ in range(n_rows)]
    parse_issues_by_row: List[List[Dict[str, Any]]] = [[] for _ in range(n_rows)]

    for entry in column_map["entries"]:
        internal = entry["internal"]
        original = entry["original"]
        series = renamed_raw[internal]
        role = roles.get(internal)
        convert = _should_convert_numeric(internal, role, series, target_internal)
        parsed_values: List[Any] = []
        for i, raw_value in enumerate(series.tolist()):
            if not convert:
                parsed_values.append(_preserve_identifier_value(raw_value))
                continue
            parsed = parse_numeric_token(raw_value, locale=locale)
            cell = _apply_numeric_parse(
                parsed,
                raw_value=raw_value,
                internal=internal,
                original=original,
                row_id=row_ids[i],
                locale=locale,
                is_target=(internal == target_internal),
                changes_by_row=changes_by_row,
                parse_issues_by_row=parse_issues_by_row,
                row_index=i,
            )
            parsed_values.append(cell)
        parsed_columns[internal] = parsed_values

    parsed_frame = pd.DataFrame(parsed_columns, copy=True)
    if target_internal:
        roles[target_internal] = "target"
    roles[ROW_ID_COLUMN] = "identifier"

    row_ledger: List[Dict[str, Any]] = []
    identifier_internals = [
        name for name, role in roles.items() if role == "identifier" and name != ROW_ID_COLUMN
    ]
    _flag_duplicate_identifiers(renamed_raw, identifier_internals, row_ids, issues)

    for i, row_id in enumerate(row_ids):
        reasons = [item["code"] for item in parse_issues_by_row[i]]
        observed = False
        disposition = "observed"
        if target_internal is None:
            disposition = "observed"
            observed = True
        else:
            target_value = parsed_frame.iloc[i][target_internal]
            raw_target = renamed_raw.iloc[i][target_internal]
            target_missing = target_internal in missing_before_by_row[i] or is_missing_token(raw_target)
            if target_missing:
                observed = False
                disposition = "pending_target"
                reasons.append("missing_target")
            elif _is_non_finite_cell(target_value) or any(
                item["code"] == "non_finite_value" and item.get("column") == target_internal
                for item in parse_issues_by_row[i]
            ):
                observed = False
                disposition = "rejected"
                reasons.append("non_finite_target")
            elif any(
                item["code"] in {"malformed_number", "ambiguous_number"}
                and item.get("column") == target_internal
                for item in parse_issues_by_row[i]
            ):
                observed = False
                disposition = "rejected"
                reasons.append("unusable_target")
            elif _is_numeric_observation(target_value):
                observed = True
                disposition = "observed"
            else:
                observed = False
                disposition = "pending_target"
                reasons.append("unusable_target")

        for item in parse_issues_by_row[i]:
            issues.append(
                make_issue(
                    item["code"],
                    item["severity"],
                    item["message"],
                    affected_ids=[row_id],
                    evidence=item.get("evidence") or {},
                )
            )

        row_ledger.append(
            {
                "row_id": row_id,
                "observed_target": bool(observed),
                "disposition": disposition,
                "missing_before": list(missing_before_by_row[i]),
                "changes": list(changes_by_row[i]),
                "reasons": reasons,
            }
        )

    n_observed = sum(1 for entry in row_ledger if entry["observed_target"])
    issues.append(
        make_issue(
            "ingest_summary",
            "info",
            (
                f"Ingestão: {n_rows} registros recebidos, {n_observed} com alvo observado; "
                "nenhum alvo ausente foi imputado; preditores não imputados nesta camada."
            ),
            evidence={
                "received": n_rows,
                "observed_target": n_observed,
                "authorized_predictors": authorized,
                "target": target_internal,
                "locale": locale,
                "filename": filename,
                "input_sha256": input_sha256,
            },
        )
    )

    if spec.get("target_unit") in (None, ""):
        issues.append(
            make_issue(
                "unit_pending",
                "warning",
                "Unidade do alvo não declarada; não se presume BRL nem BRL/m2.",
                evidence={"field": "target_unit"},
            )
        )
    if spec.get("reference_date") in (None, ""):
        issues.append(
            make_issue(
                "reference_date_pending",
                "info",
                "reference_date ausente; não se presume a data atual.",
                evidence={"field": "reference_date"},
            )
        )

    bundle = InputBundle(
        schema_version=SCHEMA_VERSION,
        raw_frame=raw_frame,
        parsed_frame=parsed_frame,
        column_map=column_map,
        row_ledger=row_ledger,
        input_sha256=input_sha256,
        issues=issues,
    )
    logger.info(
        "ingest_market filename=%s sha256=%s rows=%s observed=%s issues=%s",
        filename,
        input_sha256,
        n_rows,
        n_observed,
        [item["code"] for item in issues if item["severity"] != "info"],
    )
    return bundle


def reconstruct_original_record(bundle: InputBundle, row_id: str) -> Dict[str, Any]:
    """Recover the original record and the list of changes for a stable row_id."""
    for index, entry in enumerate(bundle.row_ledger):
        if entry.get("row_id") == row_id:
            values = {}
            raw_row = bundle.raw_frame.iloc[index]
            for column in bundle.raw_frame.columns:
                values[column] = raw_row[column]
            return {
                "row_id": row_id,
                "values": values,
                "changes": list(entry.get("changes") or []),
                "missing_before": list(entry.get("missing_before") or []),
                "disposition": entry.get("disposition"),
                "observed_target": entry.get("observed_target"),
            }
    raise KeyError(row_id)


def observed_target_count(bundle: InputBundle) -> int:
    return sum(1 for entry in bundle.row_ledger if entry.get("observed_target"))


class DataLoader:
    def __init__(self):
        self.df = None
        self.original_df = None
        self.identification_df = None
        self.input_bundle: Optional[InputBundle] = None
        self.row_ids: List[str] = []

    def load_data(
        self,
        file_content: bytes,
        filename: str,
        request_spec: Optional[Dict[str, Any]] = None,
    ) -> DataLoadResult:
        """Legacy adapter: ingest without inventing prices or encoding dummies."""
        spec = request_spec if isinstance(request_spec, dict) else _legacy_request_spec()
        try:
            bundle = ingest_market(file_content, filename, spec)
        except Exception as exc:
            logger.error("Error loading data: %s", exc)
            return DataLoadResult(success=False, message=f"Error loading data: {str(exc)}", error=str(exc))

        self.input_bundle = bundle
        fatal = [item for item in bundle.issues if item.get("code") in FATAL_READ_CODES and item.get("severity") == "error"]
        if fatal:
            message = fatal[0]["message"]
            if fatal[0]["code"] == "unsupported_format":
                message = "Unsupported file format"
            return DataLoadResult(success=False, message=message, error=fatal[0]["code"])

        parsed = bundle.parsed_frame.copy()
        self.row_ids = []
        if ROW_ID_COLUMN in parsed.columns:
            self.row_ids = [str(v) for v in parsed[ROW_ID_COLUMN].tolist()]
            parsed = parsed.drop(columns=[ROW_ID_COLUMN])

        raw_renamed = bundle.raw_frame.copy()
        raw_renamed.columns = [
            bundle.column_map["original_to_internal"][col] for col in bundle.raw_frame.columns
        ]
        self.original_df = raw_renamed
        self.df = parsed

        excluded_columns: Dict[str, str] = {}
        warnings = []
        for item in bundle.issues:
            if item["severity"] == "warning":
                warnings.append(item["message"])
            elif item["severity"] == "error" and item["code"] not in FATAL_READ_CODES:
                warnings.append(item["message"])

        capacity_limit = config.MAX_ONE_HOT_CATEGORIES
        for col in parsed.columns:
            if pd.api.types.is_string_dtype(parsed[col]) or parsed[col].dtype == object:
                nunique = parsed[col].nunique(dropna=True)
                if nunique > capacity_limit:
                    warnings.append(
                        (
                            f"Coluna '{col}' tem {nunique} categorias; "
                            f"limite de capacidade one-hot (MAX_ONE_HOT_CATEGORIES={capacity_limit}) "
                            "é um limite de capacidade da C02, não uma impossibilidade matemática. "
                            "C01 não exclui nem codifica; C02 define o tratamento."
                        )
                    )

        identifier_cols = [
            entry["internal"]
            for entry in bundle.column_map["entries"]
            if looks_like_non_quantitative(raw_renamed[entry["internal"]].tolist())
            or clean_column_name(str(entry["original"])) in IDENTIFIER_NAME_HINTS
        ]
        identification_df = None
        if identifier_cols:
            present = [c for c in identifier_cols if c in raw_renamed.columns]
            if present:
                identification_df = raw_renamed[present].copy()
                identification_df.index = parsed.index
        self.identification_df = identification_df

        validation = self._validate_initial_requirements(excluded_columns, extra_warnings=warnings)
        return DataLoadResult(
            success=True,
            dataframe=self.df,
            validation=validation,
            variables=list(self.df.columns),
            sample_size=len(self.df),
            missing_values=self.df.isnull().sum().to_dict(),
            identification_df=identification_df,
            excluded_columns=excluded_columns,
        )

    def _validate_initial_requirements(
        self,
        excluded_columns: Optional[Dict[str, str]] = None,
        extra_warnings: Optional[List[str]] = None,
    ) -> ValidationResult:
        messages: List[str] = []
        warnings: List[str] = list(extra_warnings or [])
        is_valid = True
        n_samples = 0 if self.df is None else len(self.df)

        if excluded_columns:
            for col, reason in excluded_columns.items():
                warnings.append(f"Coluna '{col}' excluída da modelagem: {reason}")

        if n_samples < config.MIN_SAMPLES_GRAU_1:
            warnings.append(
                f"Insufficient samples: {n_samples}. Reference minimum for Degree 1 is "
                f"{config.MIN_SAMPLES_GRAU_1} (informational; the binding normative minimum "
                "depends on the number of model variables k)."
            )
        elif n_samples < config.MIN_SAMPLES_GRAU_2:
            warnings.append(
                f"Sample size {n_samples} only sufficient for Degree 1 "
                f"(Minimum for Degree 2 is {config.MIN_SAMPLES_GRAU_2})."
            )
        elif n_samples < config.MIN_SAMPLES_GRAU_3:
            warnings.append(
                f"Sample size {n_samples} sufficient for Degree 1 and 2 "
                f"(Minimum for Degree 3 is {config.MIN_SAMPLES_GRAU_3})."
            )

        return ValidationResult(
            success=True,
            is_valid=is_valid,
            messages=messages,
            warnings=warnings,
            details={"n_samples": n_samples},
        )

    def get_numeric_columns(self) -> List[str]:
        if self.df is None:
            return []
        return self.df.select_dtypes(include=[np.number]).columns.tolist()


def _empty_bundle(
    input_sha256: str,
    issues: List[Dict[str, Any]],
    column_map: Optional[Dict[str, Any]] = None,
) -> InputBundle:
    return InputBundle(
        schema_version=SCHEMA_VERSION,
        raw_frame=pd.DataFrame(),
        parsed_frame=pd.DataFrame(),
        column_map=column_map or _empty_column_map(),
        row_ledger=[],
        input_sha256=input_sha256,
        issues=issues,
    )


def _empty_column_map() -> Dict[str, Any]:
    return {
        "original_to_internal": {},
        "internal_to_original": {},
        "entries": [],
        "collisions": [],
    }


def _legacy_request_spec() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "target_col": "",
        "candidate_cols": None,
        "roles": {},
        "units": {},
        "import_options": {"locale": "auto", "delimiter": None, "encoding": None},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {},
        "evaluation_policy": {},
        "reference_date": None,
        "inspection_date": None,
        "target_unit": "",
        "applicant": "",
        "purpose": "",
    }


def _normalize_request_spec(request_spec: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    spec = _legacy_request_spec()
    spec.update({k: v for k, v in request_spec.items() if k in spec or True})
    import_options = dict(spec.get("import_options") or {})
    import_options.setdefault("locale", "auto")
    import_options.setdefault("delimiter", None)
    import_options.setdefault("encoding", None)
    spec["import_options"] = import_options
    spec.setdefault("roles", {})
    spec.setdefault("units", {})
    spec.setdefault("schema_version", SCHEMA_VERSION)
    if spec.get("schema_version") not in (None, SCHEMA_VERSION):
        issues.append(
            make_issue(
                "schema_version_mismatch",
                "warning",
                f"schema_version {spec.get('schema_version')!r} distinto de {SCHEMA_VERSION}.",
                evidence={"schema_version": spec.get("schema_version")},
            )
        )
    missing_policy = dict(spec.get("missing_policy") or {})
    missing_policy.setdefault("target", "never_impute")
    missing_policy.setdefault("predictors", "complete_case")
    spec["missing_policy"] = missing_policy
    return spec


def _resolve_roles(
    spec: Dict[str, Any],
    column_map: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> Dict[str, str]:
    roles: Dict[str, str] = {}
    raw_roles = spec.get("roles") or {}
    if not isinstance(raw_roles, dict):
        issues.append(
            make_issue(
                "roles_invalid",
                "error",
                "roles deve ser um mapa nome→papel.",
                evidence={"field": "roles"},
            )
        )
        return roles
    valid = {"target", "predictor", "identifier", "source", "date", "excluded"}
    for name, role in raw_roles.items():
        internal = resolve_column_name(name, column_map)
        if internal is None:
            issues.append(
                make_issue(
                    "role_column_absent",
                    "error",
                    f"Papel declarado para coluna ausente: {name!r}.",
                    evidence={"field": "roles", "column": name, "role": role},
                )
            )
            continue
        if role not in valid:
            issues.append(
                make_issue(
                    "role_invalid",
                    "error",
                    f"Papel {role!r} inválido para {name!r}.",
                    evidence={"field": "roles", "column": name, "role": role},
                )
            )
            continue
        roles[internal] = role
    return roles


def _resolve_target(
    spec: Dict[str, Any],
    column_map: Dict[str, Any],
    roles: Dict[str, str],
    issues: List[Dict[str, Any]],
) -> Optional[str]:
    declared = spec.get("target_col")
    target_from_roles = [name for name, role in roles.items() if role == "target"]
    if declared in (None, ""):
        if len(target_from_roles) == 1:
            return target_from_roles[0]
        if len(target_from_roles) > 1:
            issues.append(
                make_issue(
                    "target_role_ambiguous",
                    "error",
                    "Mais de uma coluna com papel target.",
                    evidence={"columns": target_from_roles},
                )
            )
        else:
            issues.append(
                make_issue(
                    "target_not_declared",
                    "warning",
                    "Alvo não declarado; nenhum valor-alvo será imputado e nenhuma coluna será presumida.",
                    evidence={"field": "target_col"},
                )
            )
        return None

    internal = resolve_column_name(declared, column_map)
    if internal is None:
        issues.append(
            make_issue(
                "target_not_found",
                "error",
                f"Coluna alvo {declared!r} inexistente; o universo não foi ampliado.",
                evidence={
                    "field": "target_col",
                    "requested": declared,
                    "available_original": [e["original"] for e in column_map["entries"]],
                    "available_internal": [e["internal"] for e in column_map["entries"]],
                },
            )
        )
        return None
    if target_from_roles and internal not in target_from_roles:
        issues.append(
            make_issue(
                "target_role_conflict",
                "error",
                "target_col e roles['target'] discordam.",
                evidence={"target_col": internal, "roles_target": target_from_roles},
            )
        )
    roles[internal] = "target"
    return internal


def _resolve_candidates(
    spec: Dict[str, Any],
    column_map: Dict[str, Any],
    roles: Dict[str, str],
    target_internal: Optional[str],
    issues: List[Dict[str, Any]],
) -> List[str]:
    candidate_cols = spec.get("candidate_cols", None)
    internals = [entry["internal"] for entry in column_map["entries"]]

    if candidate_cols is None:
        authorized = []
        for name in internals:
            role = roles.get(name)
            if name == target_internal:
                continue
            if role in NON_QUANTITATIVE_ROLES or role == "target":
                continue
            authorized.append(name)
        issues.append(
            make_issue(
                "candidate_selection_auto",
                "info",
                "candidate_cols=null: seleção automática explícita por papel.",
                evidence={"authorized_predictors": authorized},
            )
        )
        return authorized

    if not isinstance(candidate_cols, list):
        issues.append(
            make_issue(
                "candidate_cols_invalid",
                "error",
                "candidate_cols deve ser null ou lista.",
                evidence={"field": "candidate_cols", "type": type(candidate_cols).__name__},
            )
        )
        return []

    if candidate_cols == []:
        issues.append(
            make_issue(
                "empty_candidate_selection",
                "error",
                "candidate_cols=[] não autoriza nenhuma variável (nunca 'todas').",
                evidence={"field": "candidate_cols", "requested": []},
            )
        )
        return []

    authorized: List[str] = []
    missing: List[Any] = []
    for name in candidate_cols:
        internal = resolve_column_name(name, column_map)
        if internal is None:
            missing.append(name)
            continue
        if internal == target_internal:
            issues.append(
                make_issue(
                    "candidate_is_target",
                    "warning",
                    f"Candidata {name!r} é o alvo e não entra como preditor.",
                    evidence={"column": name},
                )
            )
            continue
        if internal == ROW_ID_COLUMN:
            issues.append(
                make_issue(
                    "candidate_is_row_id",
                    "error",
                    "row_id nunca entra como preditor.",
                    evidence={"column": name},
                )
            )
            continue
        authorized.append(internal)

    if missing:
        issues.append(
            make_issue(
                "requested_column_absent",
                "error",
                "Coluna solicitada ausente; o universo de candidatas não foi ampliado.",
                evidence={
                    "field": "candidate_cols",
                    "missing": missing,
                    "authorized": authorized,
                    "available_original": [e["original"] for e in column_map["entries"]],
                },
            )
        )
    return authorized


def _should_convert_numeric(
    internal: str,
    role: Optional[str],
    series: pd.Series,
    target_internal: Optional[str],
) -> bool:
    if internal == ROW_ID_COLUMN:
        return False
    if role in NON_QUANTITATIVE_ROLES:
        return False
    if internal == target_internal or role == "target":
        return True
    if looks_like_non_quantitative(series.tolist()):
        return False
    if role == "predictor":
        return True
    return not looks_like_non_quantitative(series.tolist())


def _preserve_identifier_value(raw_value: Any) -> Any:
    if is_missing_token(raw_value):
        return None
    if isinstance(raw_value, str):
        return raw_value
    return raw_value


def _apply_numeric_parse(
    parsed,
    *,
    raw_value: Any,
    internal: str,
    original: Any,
    row_id: str,
    locale: str,
    is_target: bool,
    changes_by_row: List[List[Dict[str, Any]]],
    parse_issues_by_row: List[List[Dict[str, Any]]],
    row_index: int,
) -> Any:
    position = {"row_id": row_id, "column": internal, "original_column": original}

    if parsed.status == "missing":
        return np.nan

    if parsed.status in {"parsed", "already_numeric"}:
        if parsed.status == "parsed" or not _same_magnitude(raw_value, parsed.value):
            changes_by_row[row_index].append(
                {
                    "column": internal,
                    "original_column": original,
                    "raw": raw_value,
                    "parsed": parsed.value,
                    "action": "parse_numeric" if parsed.status == "parsed" else "already_numeric",
                    "locale": parsed.locale_applied,
                }
            )
        return parsed.value

    if parsed.status == "ambiguous":
        parse_issues_by_row[row_index].append(
            {
                "code": "ambiguous_number",
                "severity": "warning",
                "message": (
                    f"Valor {raw_value!r} na coluna {original!r} é ambíguo sem localidade "
                    "suficiente; magnitude não alterada (pontos não foram removidos)."
                ),
                "column": internal,
                "evidence": {**position, **(parsed.evidence or {}), "locale": locale},
            }
        )
        changes_by_row[row_index].append(
            {
                "column": internal,
                "original_column": original,
                "raw": raw_value,
                "parsed": raw_value,
                "action": "ambiguous_unconverted",
                "locale": locale,
            }
        )
        return raw_value

    if parsed.status == "non_finite":
        parse_issues_by_row[row_index].append(
            {
                "code": "non_finite_value",
                "severity": "error",
                "message": f"Valor não finito em {original!r} (row_id={row_id}).",
                "column": internal,
                "evidence": {**position, "raw": repr(raw_value)},
            }
        )
        changes_by_row[row_index].append(
            {
                "column": internal,
                "original_column": original,
                "raw": raw_value,
                "parsed": None,
                "action": "non_finite_rejected",
                "locale": locale,
            }
        )
        return np.nan

    if parsed.status == "malformed":
        parse_issues_by_row[row_index].append(
            {
                "code": "malformed_number",
                "severity": "error",
                "message": f"Número malformado {raw_value!r} em {original!r} (row_id={row_id}).",
                "column": internal,
                "evidence": {**position, **(parsed.evidence or {})},
            }
        )
        changes_by_row[row_index].append(
            {
                "column": internal,
                "original_column": original,
                "raw": raw_value,
                "parsed": raw_value,
                "action": "malformed_unconverted",
                "locale": locale,
            }
        )
        return raw_value

    return raw_value if not is_missing_token(raw_value) else np.nan


def _same_magnitude(raw_value: Any, parsed: Optional[float]) -> bool:
    if parsed is None:
        return False
    if isinstance(raw_value, (int, float, np.integer, np.floating)) and not isinstance(raw_value, bool):
        try:
            return float(raw_value) == float(parsed)
        except (TypeError, ValueError):
            return False
    return False


def _is_numeric_observation(value: Any) -> bool:
    if is_missing_token(value):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return bool(np.isfinite(float(value)))
    return False


def _is_non_finite_cell(value: Any) -> bool:
    if isinstance(value, (float, np.floating)):
        return not np.isfinite(float(value)) and not pd.isna(value)
    return False


def _flag_duplicate_identifiers(
    renamed_raw: pd.DataFrame,
    identifier_internals: Sequence[str],
    row_ids: Sequence[str],
    issues: List[Dict[str, Any]],
) -> None:
    for column in identifier_internals:
        if column not in renamed_raw.columns:
            continue
        seen: Dict[Any, List[str]] = {}
        for i, value in enumerate(renamed_raw[column].tolist()):
            if is_missing_token(value):
                continue
            key = value
            seen.setdefault(key, []).append(row_ids[i])
        duplicates = {str(k): ids for k, ids in seen.items() if len(ids) > 1}
        if duplicates:
            affected = [row_id for ids in duplicates.values() for row_id in ids]
            issues.append(
                make_issue(
                    "duplicate_identifier",
                    "warning",
                    f"Identificadores duplicados na coluna {column!r}; row_id gerado permanece a identidade.",
                    affected_ids=affected,
                    evidence={"column": column, "duplicates": duplicates},
                )
            )


def _make_row_id(index: int, n_rows: int) -> str:
    width = max(6, len(str(max(n_rows - 1, 0))))
    return f"R{index:0{width}d}"


def _log_read(filename: str, input_sha256: str, read: TabularRead) -> None:
    meta = read.metadata or {}
    logger.info(
        "read_tabular filename=%s sha256=%s encoding=%s delimiter=%s engine=%s "
        "bom=%s bytes=%s rows=%s cols=%s error=%s",
        filename,
        input_sha256,
        meta.get("encoding"),
        meta.get("delimiter"),
        meta.get("engine"),
        meta.get("bom"),
        meta.get("n_bytes"),
        meta.get("n_rows"),
        meta.get("n_cols"),
        None if read.error is None else read.error.get("code"),
    )
