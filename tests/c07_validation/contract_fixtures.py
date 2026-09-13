"""Labeled C01/C02/C04/C05 contract simulators for C07 tests.

These stand-ins are NOT production engines and are NOT evidence of real
integration with other campaigns. They exist so evaluate_procedure can be
exercised against the MP/1 callback contract while those campaigns are
absent from this HEAD.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

CONTRACT_FIXTURE_LABEL = "contract-simulator-not-production"
SYNTHETIC_NOTE = "synthetic-identified"


def make_input_bundle(rows: Sequence[Mapping[str, Any]], *, input_sha256: str = "synthetic") -> Dict[str, Any]:
    frame = pd.DataFrame(list(rows))
    if "row_id" not in frame.columns:
        raise ValueError("synthetic bundle rows must include row_id")
    ledger = {}
    for rec in rows:
        rid = rec["row_id"]
        target = rec.get("_observed_target", rec.get("preco"))
        ledger[rid] = {
            "observed_target": target,
            "disposition": "observed" if target is not None else "missing_target",
            "missing_before": {},
            "changes": [],
            "reasons": [SYNTHETIC_NOTE],
        }
    return {
        "schema_version": "MP/1",
        "raw_frame": frame.copy(),
        "parsed_frame": frame.copy(),
        "column_map": {name: name for name in frame.columns},
        "row_ledger": ledger,
        "input_sha256": input_sha256,
        "issues": [],
        "synthetic": True,
        "label": CONTRACT_FIXTURE_LABEL,
    }


def make_request_spec(
    *,
    target_col: str = "preco",
    candidate_cols=None,
    roles=None,
    target_unit: Optional[str] = "BRL",
    evaluation_policy=None,
    search_policy=None,
    missing_policy=None,
    outlier_policy=None,
) -> Dict[str, Any]:
    return {
        "schema_version": "MP/1",
        "target_col": target_col,
        "candidate_cols": candidate_cols,
        "roles": roles
        or {
            target_col: "target",
            "area": "predictor",
            "quartos": "predictor",
            "bairro": "predictor",
            "row_id": "identifier",
        },
        "units": {target_col: target_unit} if target_unit else {},
        "import_options": {"locale": "pt-BR", "delimiter": None, "encoding": None},
        "missing_policy": missing_policy
        or {"target": "never_impute", "predictors": "train_mean"},
        "outlier_policy": outlier_policy or {"mode": "report_only"},
        "search_policy": search_policy or {"mode": "labeled_simulator", "budget": {"max_features": 4}, "objective": "train_mae", "seed": 0},
        "evaluation_policy": evaluation_policy
        or {"method": "random", "test_size": 0.25, "n_splits": 1, "mode": "fast", "stability": False},
        "reference_date": None,
        "inspection_date": None,
        "target_unit": target_unit,
        "applicant": "synthetic",
        "purpose": "c07-contract-test",
    }


def labeled_fit_select_predictor(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    *,
    leak: bool = False,
):
    """Return fit_select_predictor(train_row_ids, seed).

    leak=True learns imputations, categories and selection from every row in
    the bundle (the C07 sentinel must flag that). The correct path uses only
    the training ids passed by evaluate_procedure.
    """

    parsed = input_bundle["parsed_frame"]
    if not isinstance(parsed, pd.DataFrame):
        parsed = pd.DataFrame(list(parsed))
    target_col = request_spec["target_col"]

    def fit(train_row_ids: Sequence[Any], seed: int) -> Dict[str, Any]:
        learn_ids = list(parsed["row_id"]) if leak else list(train_row_ids)
        learn = parsed[parsed["row_id"].isin(learn_ids)].copy()
        learn = learn[learn[target_col].notna()]
        if learn.empty:
            return {
                "status": "error",
                "predict": lambda records: [],
                "trace": {"used_row_ids": list(learn_ids), "issues": ["no_train_target"]},
                "label": CONTRACT_FIXTURE_LABEL,
                "leak": leak,
            }

        feature_cols = _predictor_columns(parsed, request_spec)
        numeric_cols, categorical_cols = _split_kinds(learn, feature_cols)

        impute_values = {}
        for col in numeric_cols:
            observed = pd.to_numeric(learn[col], errors="coerce")
            impute_values[col] = float(observed.mean()) if observed.notna().any() else 0.0

        categories: Dict[str, List[Any]] = {}
        for col in categorical_cols:
            values = [v for v in learn[col].tolist() if v is not None and not (isinstance(v, float) and np.isnan(v))]
            # Preserve first-seen order for stability; drop_first reference = first unique.
            unique = []
            for v in values:
                if v not in unique:
                    unique.append(v)
            categories[col] = unique

        encoder_state = {
            "impute_values": impute_values,
            "categories": categories,
            "numeric_cols": list(numeric_cols),
            "categorical_cols": list(categorical_cols),
            "learned_from": "all_rows" if leak else "train_row_ids_only",
        }

        X, y, feature_names, design_cols = _design_matrix(learn, target_col, encoder_state, fail_unseen=False)
        selected, candidates = _select_features(X, y, feature_names, design_cols, seed)
        X_sel = X[:, selected] if selected else X
        selected_names = [feature_names[i] for i in selected] if selected else list(feature_names)

        n = X_sel.shape[0]
        xb = np.column_stack([np.ones(n), X_sel]) if n else np.ones((0, 1))
        if n == 0:
            beta = np.zeros(xb.shape[1])
        else:
            beta, *_ = np.linalg.lstsq(xb, y, rcond=None)

        intercept_only = float(np.mean(y))
        train_pred = xb @ beta
        train_mae = float(np.mean(np.abs(train_pred - y))) if n else None
        null_mae = float(np.mean(np.abs(y - intercept_only))) if n else None
        candidates = [
            {"candidate_id": "intercept_only", "features": [], "base_variables": [], "internal_score": null_mae, "train_score": null_mae},
            {"candidate_id": "selected_ols", "features": list(selected_names), "base_variables": _base_variables(selected_names, categorical_cols, numeric_cols), "internal_score": train_mae, "train_score": train_mae},
        ] + candidates

        def predict(records: Sequence[Mapping[str, Any]]):
            out = []
            for rec in records:
                rid = rec.get("row_id")
                vector, fail = _row_vector(rec, encoder_state, feature_names, selected)
                if fail is not None:
                    out.append(
                        {
                            "row_id": rid,
                            "status": "failed",
                            "value": None,
                            "code": fail["code"],
                            "message": fail["message"],
                            "evidence": fail.get("evidence") or {},
                            "issue": {
                                "code": fail["code"],
                                "severity": "error",
                                "origin": "C07-contract-simulator",
                                "message": fail["message"],
                                "affected_ids": [rid] if rid is not None else [],
                                "evidence": fail.get("evidence") or {},
                            },
                        }
                    )
                    continue
                yhat = float(np.dot(np.concatenate(([1.0], vector)), beta))
                out.append({"row_id": rid, "status": "ok", "value": yhat})
            return out

        return {
            "status": "fitted",
            "predict": predict,
            "trace": {
                "used_row_ids": list(learn["row_id"]),
                "selected_features": list(selected_names),
                "selected_base_variables": _base_variables(selected_names, categorical_cols, numeric_cols),
                "encoder_state": encoder_state,
                "impute_values": dict(impute_values),
                "categories": {k: list(v) for k, v in categories.items()},
                "candidates": candidates,
                "model_spec": {
                    "kind": "ols_contract_simulator",
                    "label": CONTRACT_FIXTURE_LABEL,
                    "leak": leak,
                    "n_train": int(n),
                    "seed": int(seed),
                },
                "issues": [],
            },
            "label": CONTRACT_FIXTURE_LABEL,
            "leak": leak,
        }

    fit.contract_fixture_label = CONTRACT_FIXTURE_LABEL
    fit.leak = leak
    return fit


def _predictor_columns(frame: pd.DataFrame, request_spec: Mapping[str, Any]) -> List[str]:
    target = request_spec["target_col"]
    skip = {target, "row_id"}
    roles = request_spec.get("roles") or {}
    for name, role in roles.items():
        if str(role).lower() in {"target", "identifier", "source", "date", "excluded"}:
            skip.add(name)
    cols = request_spec.get("candidate_cols", None)
    if isinstance(cols, list):
        return [c for c in cols if c in frame.columns and c not in skip]
    # candidate_cols is None: automatic selection by role (MP/1). Extra
    # columns without predictor role (dates, leftover fields) stay out.
    predictors = [
        name
        for name, role in roles.items()
        if str(role).lower() == "predictor" and name in frame.columns and name not in skip
    ]
    if predictors:
        return predictors
    return [c for c in frame.columns if c not in skip]


def _split_kinds(frame: pd.DataFrame, columns: Sequence[str]):
    numeric = []
    categorical = []
    for col in columns:
        if col not in frame.columns:
            continue
        if pd.api.types.is_numeric_dtype(frame[col]):
            numeric.append(col)
        else:
            categorical.append(col)
    return numeric, categorical


def _design_matrix(frame: pd.DataFrame, target_col: str, encoder: Mapping[str, Any], fail_unseen: bool):
    y = pd.to_numeric(frame[target_col], errors="coerce").to_numpy(dtype=float)
    rows = []
    names = []
    design_cols = []
    for col in encoder["numeric_cols"]:
        values = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=float)
        fill = encoder["impute_values"][col]
        values = np.where(np.isfinite(values), values, fill)
        rows.append(values)
        names.append(col)
        design_cols.append(("numeric", col, None))
    for col, uniques in encoder["categories"].items():
        reference = uniques[0] if uniques else None
        series = frame[col].tolist()
        for category in uniques[1:]:
            rows.append(np.array([1.0 if v == category else 0.0 for v in series], dtype=float))
            names.append(f"{col}={category}")
            design_cols.append(("dummy", col, category))
        _ = reference
    if not rows:
        X = np.zeros((len(frame), 0), dtype=float)
    else:
        X = np.column_stack(rows)
    return X, y, names, design_cols


def _row_vector(rec: Mapping[str, Any], encoder: Mapping[str, Any], feature_names: Sequence[str], selected: Sequence[int]):
    values = []
    for col in encoder["numeric_cols"]:
        number = rec.get(col)
        try:
            number = float(number)
            if not np.isfinite(number):
                number = encoder["impute_values"][col]
        except (TypeError, ValueError):
            number = encoder["impute_values"][col]
        values.append(float(number))
    for col, uniques in encoder["categories"].items():
        observed = rec.get(col)
        if observed is None or (isinstance(observed, float) and np.isnan(observed)):
            return None, {
                "code": "c07.prediction_failed",
                "message": f"Missing category for {col}.",
                "evidence": {"column": col},
            }
        if observed not in uniques:
            return None, {
                "code": "c07.unseen_category",
                "message": f"Category {observed!r} of {col} was not seen in training.",
                "evidence": {"column": col, "value": observed, "train_categories": list(uniques)},
            }
        for category in uniques[1:]:
            values.append(1.0 if observed == category else 0.0)
    vector = np.asarray(values, dtype=float)
    if selected:
        vector = vector[list(selected)]
    return vector, None


def _select_features(X, y, feature_names, design_cols, seed: int):
    candidates = []
    if X.size == 0 or X.shape[1] == 0:
        return [], candidates
    scores = []
    for i, name in enumerate(feature_names):
        col = X[:, i]
        if np.std(col) == 0 or np.std(y) == 0:
            corr = 0.0
        else:
            corr = float(np.corrcoef(col, y)[0, 1])
            if not np.isfinite(corr):
                corr = 0.0
        scores.append(abs(corr))
        candidates.append(
            {
                "candidate_id": f"univariate:{name}",
                "features": [name],
                "base_variables": [design_cols[i][1]],
                "internal_score": abs(corr),
                "train_score": abs(corr),
            }
        )
    order = list(np.argsort(scores)[::-1])
    rng = np.random.RandomState(int(seed))
    # Keep features with |corr| >= 0.15, else the single best. Bounded, train-only.
    selected = [i for i in order if scores[i] >= 0.15]
    if not selected:
        selected = [order[0]]
    max_features = 4
    selected = selected[:max_features]
    _ = rng.rand()  # seed is recorded as used
    return selected, candidates


def _base_variables(feature_names, categorical_cols, numeric_cols):
    bases = []
    for name in feature_names:
        if "=" in name:
            bases.append(name.split("=", 1)[0])
        else:
            bases.append(name)
    out = []
    for b in bases:
        if b not in out:
            out.append(b)
    return out


def synthetic_signal_rows(n: int = 40, seed: int = 0, *, with_category: bool = True):
    rng = np.random.RandomState(seed)
    rows = []
    bairros = ["Centro", "Norte", "Sul"]
    for i in range(n):
        area = float(50 + (i % 20) * 5 + rng.normal(0, 1))
        quartos = int(1 + (i % 4))
        preco = 1000.0 * area + 15000.0 * quartos + 80000.0 + float(rng.normal(0, 800))
        rec = {
            "row_id": f"r{i:03d}",
            "area": area,
            "quartos": quartos,
            "preco": preco,
        }
        if with_category:
            rec["bairro"] = bairros[i % len(bairros)]
        rows.append(rec)
    return rows


def synthetic_noise_rows(n: int = 40, seed: int = 0):
    rng = np.random.RandomState(seed)
    rows = []
    for i in range(n):
        rows.append(
            {
                "row_id": f"n{i:03d}",
                "area": float(rng.normal(100, 20)),
                "quartos": float(rng.normal(3, 1)),
                "preco": float(rng.normal(500000, 40000)),
                "bairro": "Centro" if i % 2 == 0 else "Norte",
            }
        )
    return rows
