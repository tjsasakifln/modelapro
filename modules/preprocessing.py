"""MP/1 dataset fit and subject transform (C02).

Public seam:
    fit_dataset(input_bundle, request_spec, train_row_ids=None) -> PreparedDataset
    transform_subject(subject_raw, feature_schema, encoder_state) -> SubjectDesign

Encoder, variance diagnostics and imputation are learned only on train_row_ids.
Validation/held-out rows never choose categories, means or columns.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from .variable_schema import (
    ISSUE_DATE_PENDING,
    ISSUE_EMPTY_CANDIDATES,
    ISSUE_HELD_OUT,
    ISSUE_IDENTIFIER_EXCLUDED,
    ISSUE_MISSING_POLICY_UNDECLARED,
    ISSUE_NO_TRAIN_ROWS,
    ISSUE_PREDICTOR_MISSING,
    ISSUE_ROLE_EXCLUDED,
    ISSUE_SCHEMA_MISMATCH,
    ISSUE_TARGET_COL_MISSING,
    ISSUE_TARGET_IMPUTE_FORBIDDEN,
    ISSUE_TARGET_MISSING,
    ISSUE_UNKNOWN_CATEGORY,
    NEVER_IMPUTE_TARGET,
    PREDICTOR_IMPUTE_METHODS,
    SCHEMA_VERSION,
    PreparedDataset,
    SubjectDesign,
    apply_encoder,
    dataset_sha256,
    diagnose_design_matrix,
    empty_prepared,
    finalize_parameter_accounting,
    fit_encoder,
    is_missing,
    json_safe,
    lookup_subject_value,
    make_issue,
    parse_numeric,
)


def _as_mapping(obj: Any, what: str) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    raise TypeError(f"{what} must be a mapping, got {type(obj).__name__}")


def _frame(bundle: Mapping[str, Any], key: str) -> pd.DataFrame:
    value = bundle.get(key)
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(value)


def _candidate_cols_explicit(spec: Mapping[str, Any]) -> Tuple[bool, Optional[List[str]]]:
    """Distinguish missing key, JSON null, and [].

    null/missing → automatic selection by role.
    [] → no variable authorized (explicit error, never 'all').
    list → exactly those names.
    """
    if "candidate_cols" not in spec:
        return False, None
    value = spec.get("candidate_cols")
    if value is None:
        return False, None
    if isinstance(value, (list, tuple)):
        return True, [str(c) for c in value]
    raise TypeError("candidate_cols must be null or a list of column names")


def _resolve_candidates(
    spec: Mapping[str, Any],
    columns: Sequence[str],
    target_col: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    roles = spec.get("roles") or {}
    explicit, names = _candidate_cols_explicit(spec)
    skip = {"row_id", target_col}

    if explicit:
        resolved = []
        for name in names:
            if name in skip:
                continue
            resolved.append(name)
        return resolved, issues

    predictors = [c for c in columns if c not in skip and roles.get(c) == "predictor"]
    if predictors:
        return predictors, issues

    reserved = {"target", "identifier", "source", "date", "excluded"}
    inferred = []
    for col in columns:
        if col in skip:
            continue
        role = roles.get(col)
        if role in reserved:
            continue
        inferred.append(col)
    return inferred, issues


def _validate_missing_policy(
    spec: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    policy = spec.get("missing_policy")
    if not isinstance(policy, Mapping):
        issues.append(
            make_issue(
                ISSUE_MISSING_POLICY_UNDECLARED,
                "error",
                "c02.fit_dataset",
                (
                    "missing_policy deve ser declarada antes do ajuste e distinguir "
                    "target (nunca imputar) de predictors (complete_case ou método "
                    "explícito ajustado só no treino)."
                ),
            )
        )
        return None, issues

    target_pol = policy.get("target")
    pred_pol = policy.get("predictors")
    if target_pol not in NEVER_IMPUTE_TARGET:
        issues.append(
            make_issue(
                ISSUE_TARGET_IMPUTE_FORBIDDEN,
                "error",
                "c02.fit_dataset",
                (
                    f"Política de target {target_pol!r} é inválida: valor-alvo ausente "
                    "nunca é imputado."
                ),
                evidence={"target_policy": target_pol},
            )
        )
        return None, issues
    if pred_pol not in PREDICTOR_IMPUTE_METHODS:
        issues.append(
            make_issue(
                ISSUE_MISSING_POLICY_UNDECLARED,
                "error",
                "c02.fit_dataset",
                (
                    "missing_policy.predictors deve ser 'complete_case', 'mean' ou "
                    "'median' (ajustado somente no treino); não é escolhido por R²."
                ),
                evidence={"predictors_policy": pred_pol},
            )
        )
        return None, issues
    normalized = {
        "target": "never_impute",
        "predictors": pred_pol,
        "unknown_category": policy.get("unknown_category") or "unsupported",
    }
    return normalized, issues


def _ensure_row_id(parsed: pd.DataFrame, ledger: Any) -> pd.DataFrame:
    frame = parsed.copy()
    if "row_id" in frame.columns:
        frame["row_id"] = frame["row_id"].map(lambda v: str(v))
        return frame
    ids: List[str] = []
    if isinstance(ledger, list) and ledger and isinstance(ledger[0], Mapping) and "row_id" in ledger[0]:
        for i, entry in enumerate(ledger):
            if isinstance(entry, Mapping) and entry.get("row_id") is not None:
                ids.append(str(entry["row_id"]))
            else:
                ids.append(str(i))
        if len(ids) == len(frame):
            frame.insert(0, "row_id", ids)
            return frame
    frame.insert(0, "row_id", [str(i) for i in frame.index])
    return frame


def _parse_target_series(series: pd.Series, locale: str) -> pd.Series:
    values: List[Any] = []
    for raw in series.tolist():
        if is_missing(raw):
            values.append(pd.NA)
            continue
        number = parse_numeric(raw, locale)
        values.append(number if number is not None else pd.NA)
    out = pd.Series(values, index=series.index, dtype="Float64")
    return out


def fit_dataset(
    input_bundle: Any,
    request_spec: Any,
    train_row_ids: Optional[Iterable[Any]] = None,
) -> PreparedDataset:
    """Fit schema, encoder and optional imputer on train rows only."""
    spec = _as_mapping(request_spec, "request_spec")
    bundle = _as_mapping(input_bundle, "input_bundle")
    origin = "c02.fit_dataset"
    issues: List[Dict[str, Any]] = []

    target_col = spec.get("target_col")
    target_unit = spec.get("target_unit")
    if not target_col:
        issues.append(
            make_issue(
                ISSUE_TARGET_COL_MISSING,
                "error",
                origin,
                "request_spec.target_col é obrigatório.",
            )
        )
        return empty_prepared(issues=issues, target_col="", target_unit=target_unit)

    missing_policy, policy_issues = _validate_missing_policy(spec)
    issues.extend(policy_issues)
    if missing_policy is None:
        return empty_prepared(
            issues=issues, target_col=target_col, target_unit=target_unit
        )

    # Work on a copy so the caller's spec is not mutated.
    spec = dict(spec)
    spec["missing_policy"] = missing_policy
    spec["_column_map"] = bundle.get("column_map") or {}

    explicit, candidate_names = _candidate_cols_explicit(spec)
    if explicit and candidate_names == []:
        issues.append(
            make_issue(
                ISSUE_EMPTY_CANDIDATES,
                "error",
                origin,
                (
                    "candidate_cols=[] não autoriza nenhuma variável (nunca é expandido "
                    "para todas). Use null para seleção automática por papel."
                ),
            )
        )
        ledger = {
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
        return empty_prepared(
            issues=issues,
            sample_ledger=ledger,
            target_col=target_col,
            target_unit=target_unit,
        )

    parsed = _ensure_row_id(_frame(bundle, "parsed_frame"), bundle.get("row_ledger"))
    received_ids = [str(v) for v in parsed["row_id"].tolist()]
    received = len(received_ids)

    if train_row_ids is None:
        train_set = None
        in_train = pd.Series(True, index=parsed.index)
    else:
        train_set = {str(v) for v in train_row_ids}
        in_train = parsed["row_id"].isin(train_set)

    locale = (spec.get("import_options") or {}).get("locale") or "auto"
    if target_col not in parsed.columns:
        issues.append(
            make_issue(
                ISSUE_TARGET_COL_MISSING,
                "error",
                origin,
                f"Coluna-alvo '{target_col}' ausente do parsed_frame.",
                affected_ids=[target_col],
            )
        )
        ledger = {
            "received": received,
            "observed_target": 0,
            "prepared": 0,
            "used": 0,
            "excluded": received,
            "used_row_ids": [],
            "excluded_row_ids": received_ids,
            "exclusions": [
                {"row_id": rid, "reasons": ["target_col_missing"]} for rid in received_ids
            ],
            "n_effective": 0,
        }
        return empty_prepared(
            issues=issues,
            sample_ledger=ledger,
            target_col=target_col,
            target_unit=target_unit,
        )

    y_parsed = _parse_target_series(parsed[target_col], locale)
    observed_target = y_parsed.notna()
    n_observed = int(observed_target.sum())

    # Encoder sample: train partition FIRST, then observed target only.
    # Held-out rows never contribute categories, means or column decisions.
    eligible = in_train & observed_target
    exclusions: List[Dict[str, Any]] = []
    excluded_ids: List[str] = []
    for idx in parsed.index:
        rid = str(parsed.at[idx, "row_id"])
        reasons: List[str] = []
        if train_set is not None and not bool(in_train.at[idx]):
            reasons.append("not_in_train")
        if not bool(observed_target.at[idx]):
            reasons.append("target_missing")
            issues.append(
                make_issue(
                    ISSUE_TARGET_MISSING,
                    "warning",
                    origin,
                    f"Linha {rid} sem target observado; o alvo nunca é imputado.",
                    affected_ids=[rid, target_col],
                )
            )
        if reasons:
            exclusions.append({"row_id": rid, "reasons": reasons})
            excluded_ids.append(rid)

    if train_set is not None:
        n_held = int((~in_train).sum())
        if n_held:
            issues.append(
                make_issue(
                    ISSUE_HELD_OUT,
                    "info",
                    origin,
                    (
                        f"{n_held} linha(s) fora de train_row_ids não entram no encoder, "
                        "nas categorias nem na imputação."
                    ),
                    affected_ids=parsed.loc[~in_train, "row_id"].astype(str).tolist(),
                    evidence={"n_held_out": n_held},
                )
            )

    train_df = parsed.loc[eligible].copy()
    if train_df.empty:
        issues.append(
            make_issue(
                ISSUE_NO_TRAIN_ROWS,
                "error",
                origin,
                "Nenhuma linha de treino com target observado para ajustar o esquema.",
            )
        )
        ledger = {
            "received": received,
            "observed_target": n_observed,
            "prepared": 0,
            "used": 0,
            "excluded": len(excluded_ids),
            "used_row_ids": [],
            "excluded_row_ids": excluded_ids,
            "exclusions": exclusions,
            "n_effective": 0,
        }
        return empty_prepared(
            issues=issues,
            sample_ledger=ledger,
            target_col=target_col,
            target_unit=target_unit,
        )

    candidates, cand_issues = _resolve_candidates(spec, list(parsed.columns), target_col)
    issues.extend(cand_issues)

    roles = spec.get("roles") or {}
    date_interp = spec.get("date_interpretations") or {}
    for col in parsed.columns:
        if col == target_col:
            continue
        role = roles.get(col)
        if col == "row_id" or role == "identifier":
            issues.append(
                make_issue(
                    ISSUE_IDENTIFIER_EXCLUDED,
                    "info",
                    origin,
                    f"Identificador '{col}' não entra em X.",
                    affected_ids=[col],
                    evidence={"role": role or "identifier"},
                )
            )
        elif role == "date" and col not in date_interp:
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
        elif role in {"source", "excluded"}:
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

    feature_schema, encoder_state, enc_issues = fit_encoder(
        train_df, candidates, spec, target_col, origin=origin
    )
    issues.extend(enc_issues)

    pred_method = missing_policy["predictors"]
    base_names = [bv["original_name"] for bv in encoder_state.get("base_variables") or []]

    used_index = []
    for idx in train_df.index:
        rid = str(train_df.at[idx, "row_id"])
        row = train_df.loc[idx]
        missing_preds: List[str] = []
        for bv in encoder_state.get("base_variables") or []:
            name = bv["original_name"]
            raw = row[name] if name in train_df.columns else None
            if bv["kind"] == "numeric":
                if is_missing(raw) or parse_numeric(raw, encoder_state.get("locale") or locale) is None:
                    if pred_method == "complete_case":
                        missing_preds.append(name)
                    elif bv.get("impute_value") is None:
                        missing_preds.append(name)
            else:
                if is_missing(raw) or (isinstance(raw, str) and not str(raw).strip()):
                    missing_preds.append(name)
        if missing_preds:
            exclusions.append(
                {"row_id": rid, "reasons": [f"predictor_missing:{p}" for p in missing_preds]}
            )
            excluded_ids.append(rid)
            issues.append(
                make_issue(
                    ISSUE_PREDICTOR_MISSING,
                    "warning",
                    origin,
                    (
                        f"Linha {rid} excluída por preditor(es) ausente(s) "
                        f"{missing_preds} (política {pred_method})."
                    ),
                    affected_ids=[rid, *missing_preds],
                    evidence={"predictors": missing_preds, "policy": pred_method},
                )
            )
            continue
        used_index.append(idx)

    used_df = train_df.loc[used_index].copy()
    used_ids = [str(v) for v in used_df["row_id"].tolist()] if not used_df.empty else []

    if used_df.empty:
        issues.append(
            make_issue(
                ISSUE_NO_TRAIN_ROWS,
                "error",
                origin,
                "Após a política de ausência, nenhuma linha de treino permanece.",
            )
        )
        X = pd.DataFrame(columns=list(encoder_state.get("column_order") or []))
        y = pd.Series(dtype=float, name=target_col)
        base_frame = pd.DataFrame(columns=base_names)
        finalize_parameter_accounting(feature_schema, X, 0)
        ledger = {
            "received": received,
            "observed_target": n_observed,
            "prepared": 0,
            "used": 0,
            "excluded": len(set(excluded_ids)),
            "used_row_ids": [],
            "excluded_row_ids": list(dict.fromkeys(excluded_ids)),
            "exclusions": exclusions,
            "n_effective": 0,
        }
        return PreparedDataset(
            X=X,
            y=y,
            row_ids=[],
            feature_schema=feature_schema,
            encoder_state=encoder_state,
            sample_ledger=ledger,
            issues=issues,
            dataset_sha256=dataset_sha256(feature_schema, encoder_state, []),
            base_frame=base_frame,
        )

    X, encode_issues, _flags = apply_encoder(
        used_df,
        encoder_state,
        origin=origin,
        row_ids=used_ids,
        allow_imputation=pred_method in {"mean", "median"},
    )
    issues.extend(encode_issues)
    issues.extend(diagnose_design_matrix(X, encoder_state, origin=origin))

    y = y_parsed.loc[used_index].astype(float)
    y.index = pd.Index(used_ids, name="row_id")
    y.name = target_col

    keep_base = [c for c in base_names if c in used_df.columns]
    base_frame = used_df[keep_base].copy()
    base_frame.index = pd.Index(used_ids, name="row_id")

    n_effective = int(len(used_ids))
    accounting = finalize_parameter_accounting(feature_schema, X, n_effective)
    sample_ledger = {
        "received": received,
        "observed_target": n_observed,
        "prepared": n_effective,
        "used": n_effective,
        "excluded": received - n_effective,
        "used_row_ids": used_ids,
        "excluded_row_ids": [rid for rid in received_ids if rid not in set(used_ids)],
        "exclusions": exclusions,
        "n_effective": n_effective,
        "n_free_slopes": accounting.get("n_free_slopes"),
        "n_free_with_intercept": accounting.get("n_free_with_intercept"),
        "rank_with_intercept": accounting.get("rank_with_intercept"),
        "schema_version": SCHEMA_VERSION,
    }

    return PreparedDataset(
        X=X,
        y=y,
        row_ids=used_ids,
        feature_schema=feature_schema,
        encoder_state=encoder_state,
        sample_ledger=json_safe(sample_ledger),
        issues=issues,
        dataset_sha256=dataset_sha256(feature_schema, encoder_state, used_ids),
        base_frame=base_frame,
    )


def transform_subject(
    subject_raw: Any,
    feature_schema: Any,
    encoder_state: Any,
) -> SubjectDesign:
    """Encode one subject with a frozen schema. Original values, not dummy names."""
    origin = "c02.transform_subject"
    issues: List[Dict[str, Any]] = []
    schema = _as_mapping(feature_schema, "feature_schema")
    state = _as_mapping(encoder_state, "encoder_state")
    raw = subject_raw if isinstance(subject_raw, Mapping) else {}
    raw_values = dict(raw)

    column_order = list(state.get("column_order") or schema.get("column_order") or [])
    schema_order = list(schema.get("column_order") or [])
    if schema_order and column_order and schema_order != column_order:
        issues.append(
            make_issue(
                ISSUE_SCHEMA_MISMATCH,
                "warning",
                origin,
                "feature_schema.column_order e encoder_state.column_order divergem; usa-se o encoder_state.",
                evidence={"schema_columns": schema_order, "encoder_columns": column_order},
            )
        )

    row: Dict[str, Any] = {}
    for bv in state.get("base_variables") or []:
        name = bv["original_name"]
        row[name] = lookup_subject_value(raw, name, state)

    frame = pd.DataFrame([row])
    X, enc_issues, flags = apply_encoder(
        frame,
        state,
        origin=origin,
        row_ids=["subject"],
        allow_imputation=(state.get("missing_policy") or {}).get("predictors") in {"mean", "median"},
    )
    issues.extend(enc_issues)

    if column_order:
        for col in column_order:
            if col not in X.columns:
                X[col] = pd.NA
        X = X.reindex(columns=column_order)

    blocking = {
        ISSUE_UNKNOWN_CATEGORY,
        ISSUE_PREDICTOR_MISSING,
        ISSUE_TARGET_COL_MISSING,
    }
    unsupported_flag = bool(flags and flags[0].get("unsupported"))
    blocking_issue = any(item.get("code") in blocking for item in issues)
    supported = not (unsupported_flag or blocking_issue)

    return SubjectDesign(
        X=X,
        raw_values=raw_values,
        issues=issues,
        supported=supported,
    )
