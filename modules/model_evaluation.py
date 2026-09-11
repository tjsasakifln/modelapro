"""Independent evaluation of the full modeling procedure (C07).

The unit under evaluation is the *procedure* wrapped by
``fit_select_predictor(train_row_ids, seed)``: applicable parse, learned
preprocessing, selection, transformations, outlier policy and fit. External
partitions estimate generalization; the callback receives only training
row ids. Reserved rows are never filtered by prediction error and never
used to choose categories or imputations.

This module does not reimplement C01/C02/C04/C05. Those engines are
injected through the callback. Scores produced here are an audit of the
procedure and must not re-enter the selection loop they are auditing.

Mappings returned by this module are JSON-serializable (no DataFrame, no
model object, no non-finite numbers). They are not a normative NBR grade.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCHEMA_VERSION = "MP/1"
EVALUATION_RESULT_KIND = "evaluation_result"
DEFAULT_TEST_SIZE = 0.2
DEFAULT_N_SPLITS = 1
SMALL_SAMPLE_N = 30
RELATIVE_ABS_FLOOR = 1e-12
ORIGIN = "C07"

FitSelectPredictor = Callable[[Sequence[Any], int], Any]
ProgressCallback = Callable[..., None]
CancelRequested = Callable[[], bool]


def evaluate_procedure(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    fit_select_predictor: FitSelectPredictor,
    seed: int,
    *,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_requested: Optional[CancelRequested] = None,
    revisions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate the injected procedure on an external partition.

    ``fit_select_predictor(train_row_ids, seed)`` must learn only from the
    supplied training ids and return a predictor handle (see module
    documentation). This function never passes reserved ids to the
    callback, never drops reserved rows for large residual, and never
    retrains a previously chosen winner on the full sample to report an
    "independent" score.
    """
    started = time.perf_counter()
    executed: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    limitations: List[str] = []
    n_fit_calls = 0
    n_predict_calls = 0

    def _progress(stage: str, fraction: Optional[float], extra: Optional[Mapping[str, Any]] = None) -> None:
        if progress_callback is None:
            return
        payload = {"stage": stage, "progress": _plain(fraction)}
        if extra:
            payload["extra"] = _plain(dict(extra))
        progress_callback(payload)

    def _cancelled() -> bool:
        return bool(cancel_requested is not None and cancel_requested())

    spec_issues = _validate_request_spec(request_spec)
    issues.extend(spec_issues)

    policy = _evaluation_policy(request_spec)
    eval_seed = int(seed)
    policy_seed = policy.get("seed")
    if policy_seed is not None and int(policy_seed) != eval_seed:
        issues.append(
            make_issue(
                "c07.seed_override",
                "info",
                "evaluate_procedure seed overrides evaluation_policy.seed; both are recorded.",
                evidence={"evaluate_procedure_seed": eval_seed, "evaluation_policy_seed": int(policy_seed)},
            )
        )

    mode = _resolve_mode(policy)
    budget = _resolve_budget(policy, mode)
    nested = bool(policy.get("nested", False))

    _progress("partition", 0.0)
    partition = partition_external(input_bundle, request_spec, eval_seed)
    issues.extend(partition.get("issues") or [])
    executed.append(
        {
            "step": "partition_external",
            "method": partition.get("method"),
            "n_splits": partition.get("n_splits"),
            "seed": eval_seed,
            "mode": mode,
        }
    )

    target_col = request_spec.get("target_col")
    target_unit = request_spec.get("target_unit")
    if not target_unit:
        target_unit = None
        issues.append(
            make_issue(
                "c07.unit_pending",
                "warning",
                "target_unit is unknown; metrics stay in the numeric original scale without assuming BRL or BRL/m2.",
            )
        )
        limitations.append("Unidade do alvo pendente; métricas numéricas sem presunção de BRL.")

    folds = list(partition.get("folds") or [])
    max_folds = budget.get("max_folds")
    if isinstance(max_folds, int) and max_folds >= 1 and len(folds) > max_folds:
        folds = folds[:max_folds]
        issues.append(
            make_issue(
                "c07.budget_truncated",
                "warning",
                "n_splits reduced to budget.max_folds; executed folds are listed in provenance.",
                evidence={"requested": partition.get("n_splits"), "executed": len(folds)},
            )
        )
        limitations.append("Orçamento limitou o número de partições externas executadas.")
        executed.append({"step": "budget_truncate_folds", "executed_folds": len(folds), "max_folds": max_folds})

    if partition.get("status") != "ok" or not folds:
        elapsed = time.perf_counter() - started
        result = _empty_evaluation_result(
            partition=partition,
            issues=issues,
            limitations=limitations,
            executed=executed,
            seed=eval_seed,
            mode=mode,
            budget=budget,
            nested=nested,
            target_unit=target_unit,
            elapsed=elapsed,
            n_fit_calls=0,
            n_predict_calls=0,
            status="error",
        )
        result["procedure_provenance"]["evaluation_policy_seed"] = (
            int(policy_seed) if policy_seed is not None else None
        )
        return _plain(result)

    n_total = len(extract_row_ids(input_bundle))
    if n_total < SMALL_SAMPLE_N:
        limitations.append(
            "Amostra pequena: a instabilidade entre partições/sementes é parte do resultado, "
            "não um ruído a esconder numa média única."
        )
        issues.append(
            make_issue(
                "c07.small_sample",
                "warning",
                "Small sample: report fold/seed variability; do not treat a single mean as stable performance.",
                evidence={"n_total": n_total, "threshold": SMALL_SAMPLE_N},
            )
        )

    fold_metrics: List[Dict[str, Any]] = []
    fold_predictions: List[Dict[str, Any]] = []
    live_fits: List[Dict[str, Any]] = []
    status = "completed"

    for index, fold in enumerate(folds):
        if _cancelled():
            issues.append(make_issue("c07.cancelled", "warning", "Evaluation cancelled between folds."))
            status = "partial"
            executed.append({"step": "cancelled", "after_fold": index})
            break
        _progress("fold", (index / max(len(folds), 1)), {"fold_id": fold.get("fold_id")})

        train_ids = list(fold["train_row_ids"])
        reserved_ids = list(fold["reserved_row_ids"])
        fold_seed = int(fold.get("seed", eval_seed))

        overlap = set(train_ids) & set(reserved_ids)
        if overlap:
            issues.append(
                make_issue(
                    "c07.partition_overlap",
                    "error",
                    "Internal invariant failed: train and reserved row ids overlap.",
                    affected_ids=sorted(overlap),
                )
            )
            status = "error"
            break

        fit_handle, fit_issue = _call_fit_select(fit_select_predictor, train_ids, fold_seed)
        n_fit_calls += 1
        executed.append(
            {
                "step": "fit_select_predictor",
                "fold_id": fold.get("fold_id"),
                "n_train": len(train_ids),
                "seed": fold_seed,
                "status": "error" if fit_issue else "fitted",
            }
        )
        if fit_issue:
            issues.append(fit_issue)
            failed_entries = [
                _failed_prediction(rid, fit_issue, y_true=_target_value(input_bundle, target_col, rid))
                for rid in reserved_ids
            ]
            scored = _score_predictions(
                failed_entries,
                train_ids=train_ids,
                reserved_ids=reserved_ids,
                input_bundle=input_bundle,
                target_col=target_col,
                target_unit=target_unit,
            )
            scored["fold_id"] = fold.get("fold_id")
            scored["seed"] = fold_seed
            fold_metrics.append(scored["metrics_block"])
            fold_predictions.extend(scored["predictions"])
            continue

        used_ids = _trace_used_row_ids(fit_handle)
        leaked_used = set(used_ids) & set(reserved_ids) if used_ids else set()
        if leaked_used:
            issues.append(
                make_issue(
                    "c07.callback_used_reserved_rows",
                    "error",
                    "fit_select_predictor trace.used_row_ids includes reserved ids (holdout contamination).",
                    affected_ids=sorted(leaked_used),
                )
            )

        records = records_for_rows(input_bundle, request_spec, reserved_ids)
        predictions, predict_issue = _call_predict(fit_handle, records, reserved_ids)
        n_predict_calls += 1
        if predict_issue:
            issues.append(predict_issue)

        for item in predictions:
            item["y_true"] = _target_value(input_bundle, target_col, item.get("row_id"))
            item["fold_id"] = fold.get("fold_id")

        executed.append(
            {
                "step": "score_reserved",
                "fold_id": fold.get("fold_id"),
                "n_reserved": len(reserved_ids),
                "n_predicted": len(predictions),
                "filtered_by_residual": False,
            }
        )

        scored = _score_predictions(
            predictions,
            train_ids=train_ids,
            reserved_ids=reserved_ids,
            input_bundle=input_bundle,
            target_col=target_col,
            target_unit=target_unit,
        )
        scored["metrics_block"]["fold_id"] = fold.get("fold_id")
        scored["metrics_block"]["seed"] = fold_seed
        fold_metrics.append(scored["metrics_block"])
        fold_predictions.extend(scored["predictions"])
        live_fits.append(
            {
                "fold_id": fold.get("fold_id"),
                "seed": fold_seed,
                "predictor": fit_handle,
                "train_row_ids": train_ids,
                "reserved_row_ids": reserved_ids,
                "trace": _safe_trace(fit_handle),
            }
        )

    _progress("aggregate", 0.85)
    aggregate = _aggregate_fold_metrics(fold_metrics, target_unit)
    coverage = _aggregate_coverage(fold_predictions, folds)

    if any(fm.get("n_train", 0) < 8 or fm.get("n_reserved", 0) < 3 for fm in fold_metrics):
        limitations.append(
            "Partição com treino ou reservado muito pequeno; a variabilidade reportada "
            "prevalece sobre qualquer média pontual."
        )

    top_mae = aggregate["metrics"].get("mae")
    ref_mae = aggregate["metrics"].get("reference_mae")
    if top_mae is not None and ref_mae is not None and ref_mae > 0 and top_mae >= 0.8 * ref_mae:
        limitations.append(
            "O procedimento não superou de forma clara a referência train_mean no "
            "reservado; métricas de um seed favorável não são garantia de sinal."
        )
        issues.append(
            make_issue(
                "c07.no_better_than_reference",
                "info",
                "Holdout MAE is not clearly better than the train-mean reference.",
                evidence={"mae": top_mae, "reference_mae": ref_mae},
            )
        )

    run_stability = bool(policy.get("stability", False))
    stability_result = None
    if run_stability and status != "error" and live_fits:
        if _cancelled():
            issues.append(make_issue("c07.cancelled", "warning", "Cancelled before stability analysis."))
            status = "partial"
        else:
            from modules.model_stability import analyze_stability

            _progress("stability", 0.9)
            stability_result = analyze_stability(
                input_bundle,
                request_spec,
                fit_select_predictor,
                eval_seed,
                evaluation_result=None,
                fitted_folds=live_fits,
                mode=mode,
                budget=budget,
                revisions=revisions if revisions is not None else policy.get("revisions"),
                cancel_requested=cancel_requested,
                progress_callback=progress_callback,
            )
            executed.append(
                {
                    "step": "analyze_stability",
                    "mode": mode,
                    "analyses_executed": list((stability_result or {}).get("executed_analyses") or []),
                }
            )
            issues.extend(stability_result.get("issues") or [])

    elapsed = time.perf_counter() - started
    nested_record = None
    if nested:
        nested_record = {
            "outer_method": partition.get("method"),
            "outer_n_splits": len(folds),
            "outer_seeds": [f.get("seed") for f in folds],
            "inner": "delegated_to_fit_select_predictor",
            "budget": _plain(budget),
            "note": (
                "Inner selection/preprocessing belongs to the callback and must use "
                "only the outer training ids of each fold."
            ),
        }

    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": EVALUATION_RESULT_KIND,
        "status": status,
        "metrics": aggregate["metrics"],
        "reference": aggregate["reference"],
        "coverage": coverage,
        "partition": {
            "method": partition.get("method"),
            "seed": eval_seed,
            "test_size": partition.get("test_size"),
            "n_splits": len(folds),
            "requested_n_splits": partition.get("n_splits"),
            "group_column": partition.get("group_column"),
            "time_column": partition.get("time_column"),
            "invented_groups": False,
            "folds": [
                {
                    "fold_id": f.get("fold_id"),
                    "seed": f.get("seed"),
                    "train_row_ids": list(f.get("train_row_ids") or []),
                    "reserved_row_ids": list(f.get("reserved_row_ids") or []),
                    "group_ids_train": f.get("group_ids_train"),
                    "group_ids_reserved": f.get("group_ids_reserved"),
                    "time_cut": f.get("time_cut"),
                    "disjoint": True,
                }
                for f in folds
            ],
            "nested": nested_record,
        },
        "fold_metrics": fold_metrics,
        "fold_traces": [
            {
                "fold_id": item.get("fold_id"),
                "seed": item.get("seed"),
                "train_row_ids": list(item.get("train_row_ids") or []),
                "reserved_row_ids": list(item.get("reserved_row_ids") or []),
                "trace": _sanitize_trace(item.get("trace") or _safe_trace(item.get("predictor"))),
            }
            for item in live_fits
        ],
        "variability": aggregate["variability"],
        "predictions": fold_predictions,
        "generalization": {
            "kind": "predictive_generalization",
            "not_normative_classification": True,
            "not_interval_stability": True,
        },
        "normative_label": {
            "applied": False,
            "grau_fundamentacao": None,
            "grau_precisao": None,
            "reason": (
                "C07 reports original-scale generalization and stability. "
                "It does not assign NBR fundamentação/precisão grades (C03)."
            ),
        },
        "statistical_inference": {
            "post_selection_guarantee": False,
            "pvalues_are_post_selection_valid": False,
            "intervals_are_post_selection_valid": False,
            "note": (
                "Holdout or CV of the procedure does not make p-values or intervals "
                "of the selected model valid after selection."
            ),
        },
        "usable_for_model_selection": False,
        "winner_retrained_on_full_data": False,
        "reserved_filtered_by_error": False,
        "procedure_provenance": {
            "evaluated_unit": "full_procedure",
            "components": [
                "parse_applicable",
                "preprocessing_learned_on_train",
                "selection",
                "transformations",
                "outlier_policy",
                "fit",
            ],
            "fit_select_predictor": "callback",
            "evaluation_seed": eval_seed,
            "evaluation_policy_seed": int(policy_seed) if policy_seed is not None else None,
            "seeds": [eval_seed] + [f.get("seed") for f in folds],
            "nested": nested,
            "nested_record": nested_record,
            "inner_selection_isolated": True,
            "external_scores_fed_to_selection": False,
            "post_selection_inference_guarantee": False,
            "mode": mode,
            "budget": _plain(budget),
            "executed": executed,
            "cost": {
                "elapsed_seconds": round(elapsed, 6),
                "n_fit_select_calls": n_fit_calls,
                "n_predict_calls": n_predict_calls,
                "n_folds_executed": len(fold_metrics),
            },
            "input_sha256": input_bundle.get("input_sha256"),
            "target_column": target_col,
            "target_unit": target_unit,
            "scale": "original",
        },
        "stability": stability_result,
        "limitations": limitations,
        "issues": issues,
    }
    _progress("done", 1.0)
    return _plain(result)


def partition_external(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    seed: int,
) -> Dict[str, Any]:
    """Build external train/reserved partition(s) from declared metadata only.

    Group or temporal splits run only when the corresponding column exists
    in the bundle / request. This function never invents property groups or
    dates. The same seed reproduces the same partition.
    """
    issues: List[Dict[str, Any]] = []
    policy = _evaluation_policy(request_spec)
    method = str(policy.get("method") or "random").strip().lower()
    if method in {"holdout", "random_holdout"}:
        method = "random"
    test_size = policy.get("test_size", DEFAULT_TEST_SIZE)
    try:
        test_size = float(test_size)
    except (TypeError, ValueError):
        issues.append(
            make_issue(
                "c07.invalid_test_size",
                "warning",
                "evaluation_policy.test_size is invalid; using the documented default.",
                evidence={"default": DEFAULT_TEST_SIZE},
            )
        )
        test_size = DEFAULT_TEST_SIZE
    if not (0.0 < test_size < 1.0):
        issues.append(
            make_issue(
                "c07.invalid_test_size",
                "warning",
                "evaluation_policy.test_size outside (0, 1); using the documented default.",
                evidence={"requested": test_size, "default": DEFAULT_TEST_SIZE},
            )
        )
        test_size = DEFAULT_TEST_SIZE

    n_splits = policy.get("n_splits", DEFAULT_N_SPLITS)
    try:
        n_splits = int(n_splits)
    except (TypeError, ValueError):
        n_splits = DEFAULT_N_SPLITS
        issues.append(make_issue("c07.invalid_n_splits", "warning", "n_splits invalid; using 1."))
    if n_splits < 1:
        n_splits = 1

    row_ids = extract_row_ids(input_bundle)
    if not row_ids:
        return {
            "status": "error",
            "method": method,
            "seed": int(seed),
            "test_size": test_size,
            "n_splits": n_splits,
            "group_column": None,
            "time_column": None,
            "invented_groups": False,
            "folds": [],
            "issues": issues
            + [
                make_issue(
                    "c07.no_row_ids",
                    "error",
                    "InputBundle has no row_id values; C07 refuses to invent identifiers.",
                )
            ],
        }

    group_column, group_issue = _resolve_group_column(input_bundle, request_spec, method)
    time_column, time_issue = _resolve_time_column(input_bundle, request_spec, method)
    if group_issue:
        issues.append(group_issue)
    if time_issue:
        issues.append(time_issue)

    if method == "group" and not group_column:
        return _partition_error(
            method, seed, test_size, n_splits, issues,
            "Group split requested but no group column metadata is available; groups were not invented.",
            code="c07.no_group_metadata",
        )
    if method == "temporal" and not time_column:
        return _partition_error(
            method, seed, test_size, n_splits, issues,
            "Temporal split requested but no date column metadata is available; dates were not invented.",
            code="c07.no_time_metadata",
        )

    try:
        if method == "group":
            folds, extra_issues = _group_folds(row_ids, input_bundle, group_column, n_splits, test_size, int(seed))
        elif method == "temporal":
            folds, extra_issues = _temporal_folds(row_ids, input_bundle, time_column, n_splits, test_size, int(seed))
        elif method in {"random", "kfold"}:
            if method == "kfold" and n_splits == 1:
                n_splits = 5
            folds, extra_issues = _random_folds(row_ids, n_splits, test_size, int(seed))
        else:
            return _partition_error(
                method, seed, test_size, n_splits, issues,
                f"Unknown evaluation_policy.method {method!r}; supported: random, group, temporal, kfold.",
                code="c07.unknown_method",
            )
    except _PartitionBuildError as exc:
        issues.append(make_issue(exc.code, "error", exc.message, evidence=exc.evidence))
        return {
            "status": "error",
            "method": method,
            "seed": int(seed),
            "test_size": test_size,
            "n_splits": n_splits,
            "group_column": group_column,
            "time_column": time_column,
            "invented_groups": False,
            "folds": [],
            "issues": issues,
        }

    issues.extend(extra_issues)
    for fold in folds:
        train_set = set(fold["train_row_ids"])
        reserved_set = set(fold["reserved_row_ids"])
        if train_set & reserved_set:
            issues.append(
                make_issue(
                    "c07.partition_overlap",
                    "error",
                    "Constructed partition overlaps train and reserved.",
                    affected_ids=sorted(train_set & reserved_set),
                )
            )
            return {
                "status": "error",
                "method": method,
                "seed": int(seed),
                "test_size": test_size,
                "n_splits": n_splits,
                "group_column": group_column,
                "time_column": time_column,
                "invented_groups": False,
                "folds": [],
                "issues": issues,
            }
        fold["disjoint"] = True

    return {
        "status": "ok",
        "method": "random" if method == "kfold" else method,
        "seed": int(seed),
        "test_size": test_size,
        "n_splits": len(folds),
        "group_column": group_column,
        "time_column": time_column,
        "invented_groups": False,
        "folds": folds,
        "issues": issues,
    }


def extract_row_ids(input_bundle: Mapping[str, Any]) -> List[Any]:
    """Stable row ids from parsed_frame order, falling back to row_ledger keys."""
    records = _parsed_records(input_bundle)
    if records is not None:
        ids = [rec.get("row_id") for rec in records if rec.get("row_id") is not None]
        if ids:
            return ids
    ledger = input_bundle.get("row_ledger")
    if isinstance(ledger, Mapping) and ledger:
        return list(ledger.keys())
    if isinstance(ledger, list):
        ids = []
        for item in ledger:
            if isinstance(item, Mapping) and item.get("row_id") is not None:
                ids.append(item.get("row_id"))
        if ids:
            return ids
    return []


def records_for_rows(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    row_ids: Sequence[Any],
) -> List[Dict[str, Any]]:
    """Feature records for ``row_ids`` without the target column."""
    target_col = request_spec.get("target_col")
    by_id = _records_by_id(input_bundle)
    out: List[Dict[str, Any]] = []
    for rid in row_ids:
        rec = dict(by_id.get(rid) or {"row_id": rid})
        rec["row_id"] = rid
        if target_col and target_col in rec:
            rec = {k: v for k, v in rec.items() if k != target_col}
            rec["row_id"] = rid
        out.append(rec)
    return out


def original_scale_metrics(
    y_true: Sequence[Any],
    y_pred: Sequence[Any],
    *,
    unit: Optional[str],
    relative_min_abs: Optional[float] = None,
) -> Dict[str, Any]:
    """MAE/RMSE on the original scale; relative error only where the denominator allows."""
    yt = np.asarray(list(y_true), dtype=float)
    yp = np.asarray(list(y_pred), dtype=float)
    n = int(yt.size)
    if n == 0 or yp.size != n:
        return {
            "unit": unit,
            "scale": "original",
            "mae": None,
            "rmse": None,
            "relative_mae": None,
            "relative_rmse": None,
            "n_relative": 0,
            "n": 0 if yp.size != n else n,
            "metrics_scope": "covered_cases_only",
            "primary_metrics": ["mae", "rmse"],
            "relative_denominator_rule": _relative_rule_text(),
        }
    err = yp - yt
    mae = _finite_or_none(float(np.mean(np.abs(err))))
    rmse = _finite_or_none(float(np.sqrt(np.mean(np.square(err)))))
    threshold = relative_min_abs
    if threshold is None:
        finite = yt[np.isfinite(yt)]
        median_abs = float(np.median(np.abs(finite))) if finite.size else 0.0
        threshold = max(RELATIVE_ABS_FLOOR, 1e-6 * median_abs)
    mask = np.isfinite(yt) & (np.abs(yt) >= float(threshold))
    n_rel = int(np.count_nonzero(mask))
    if n_rel:
        rel = np.abs(err[mask]) / np.abs(yt[mask])
        relative_mae = _finite_or_none(float(np.mean(rel)))
        relative_rmse = _finite_or_none(float(np.sqrt(np.mean(np.square(rel)))))
    else:
        relative_mae = None
        relative_rmse = None
    return {
        "unit": unit,
        "scale": "original",
        "mae": mae,
        "rmse": rmse,
        "relative_mae": relative_mae,
        "relative_rmse": relative_rmse,
        "n_relative": n_rel,
        "n": n,
        "metrics_scope": "covered_cases_only",
        "primary_metrics": ["mae", "rmse"],
        "relative_denominator_rule": _relative_rule_text(),
        "relative_min_abs": _finite_or_none(float(threshold)),
    }


def detect_preprocessing_leak(
    trace: Optional[Mapping[str, Any]],
    *,
    reserved_row_ids: Sequence[Any],
    holdout_only_categories: Optional[Mapping[str, Sequence[Any]]] = None,
    train_only_impute: Optional[Mapping[str, float]] = None,
    used_row_ids: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Sentinel: detect encoder/imputer/selection traces that touched the holdout."""
    leaks: List[Dict[str, Any]] = []
    trace = trace or {}
    used = list(trace.get("used_row_ids") or used_row_ids or [])
    overlap = [rid for rid in used if rid in set(reserved_row_ids)]
    if overlap:
        leaks.append({"kind": "used_reserved_rows", "ids": list(overlap)})

    encoder = trace.get("encoder_state") if isinstance(trace.get("encoder_state"), Mapping) else {}
    categories = encoder.get("categories") if isinstance(encoder, Mapping) else None
    if not isinstance(categories, Mapping):
        categories = trace.get("categories") if isinstance(trace.get("categories"), Mapping) else {}
    if holdout_only_categories:
        for column, values in holdout_only_categories.items():
            seen = set(categories.get(column) or [])
            leaked_vals = [v for v in values if v in seen]
            if leaked_vals:
                leaks.append(
                    {
                        "kind": "holdout_category_in_encoder",
                        "column": column,
                        "values": leaked_vals,
                    }
                )

    impute = encoder.get("impute_values") if isinstance(encoder, Mapping) else None
    if not isinstance(impute, Mapping):
        impute = trace.get("impute_values") if isinstance(trace.get("impute_values"), Mapping) else {}
    if train_only_impute:
        for column, train_val in train_only_impute.items():
            if column not in impute or train_val is None or impute.get(column) is None:
                continue
            try:
                left = float(impute[column])
                right = float(train_val)
            except (TypeError, ValueError):
                leaks.append(
                    {
                        "kind": "impute_not_train_only",
                        "column": column,
                        "trace_value": impute.get(column),
                        "train_value": train_val,
                    }
                )
                continue
            if not math.isfinite(left) or abs(left - right) > 1e-9:
                leaks.append(
                    {
                        "kind": "impute_not_train_only",
                        "column": column,
                        "trace_value": left,
                        "train_value": right,
                    }
                )

    selected = list(trace.get("selected_features") or [])
    if holdout_only_categories:
        for column, values in holdout_only_categories.items():
            for value in values:
                token = f"{column}={value}"
                dummy = f"{column}_{value}"
                if token in selected or dummy in selected:
                    leaks.append(
                        {
                            "kind": "holdout_category_selected",
                            "column": column,
                            "feature": dummy,
                        }
                    )

    return {
        "leaked": bool(leaks),
        "leaks": leaks,
        "reserved_row_ids": list(reserved_row_ids),
    }


def make_issue(
    code: str,
    severity: str,
    message: str,
    *,
    affected_ids: Optional[Sequence[Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": ORIGIN,
        "message": message,
        "affected_ids": list(affected_ids or []),
        "evidence": dict(evidence or {}),
    }


# ---------------------------------------------------------------------------
# Partition internals
# ---------------------------------------------------------------------------


class _PartitionBuildError(Exception):
    def __init__(self, code: str, message: str, evidence: Optional[Mapping[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.evidence = dict(evidence or {})


def _partition_error(method, seed, test_size, n_splits, issues, message, code):
    issues = list(issues) + [make_issue(code, "error", message)]
    return {
        "status": "error",
        "method": method,
        "seed": int(seed),
        "test_size": test_size,
        "n_splits": n_splits,
        "group_column": None,
        "time_column": None,
        "invented_groups": False,
        "folds": [],
        "issues": issues,
    }


def _random_folds(
    row_ids: Sequence[Any],
    n_splits: int,
    test_size: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    ids = list(row_ids)
    n = len(ids)
    if n < 2:
        raise _PartitionBuildError("c07.empty_partition", "Need at least 2 rows for an external split.")

    if n_splits == 1:
        rng = np.random.RandomState(seed)
        order = list(ids)
        rng.shuffle(order)
        n_test = int(round(n * test_size))
        n_test = min(max(n_test, 1), n - 1)
        reserved = order[:n_test]
        train = order[n_test:]
        return [
            _fold_record(0, seed, train, reserved)
        ], issues

    k = min(n_splits, n)
    if k < n_splits:
        issues.append(
            make_issue(
                "c07.n_splits_reduced",
                "warning",
                "n_splits reduced because there are fewer rows than folds.",
                evidence={"requested": n_splits, "used": k},
            )
        )
    rng = np.random.RandomState(seed)
    order = list(ids)
    rng.shuffle(order)
    chunks = _even_chunks(order, k)
    folds = []
    for i, reserved in enumerate(chunks):
        train = [rid for j, chunk in enumerate(chunks) if j != i for rid in chunk]
        if not train or not reserved:
            continue
        folds.append(_fold_record(i, seed + i * 1009, train, reserved))
    if not folds:
        raise _PartitionBuildError("c07.empty_partition", "k-fold produced no usable partitions.")
    return folds, issues


def _group_folds(
    row_ids: Sequence[Any],
    input_bundle: Mapping[str, Any],
    group_column: str,
    n_splits: int,
    test_size: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    group_of: Dict[Any, Any] = {}
    missing = []
    by_id = _records_by_id(input_bundle)
    for rid in row_ids:
        rec = by_id.get(rid) or {}
        g = rec.get(group_column)
        if g is None or (isinstance(g, float) and not math.isfinite(g)):
            missing.append(rid)
            continue
        group_of[rid] = g
    if missing:
        issues.append(
            make_issue(
                "c07.missing_group_value",
                "warning",
                "Rows without a group value were left out of the group split (values were not invented).",
                affected_ids=missing,
            )
        )
    usable = [rid for rid in row_ids if rid in group_of]
    groups: List[Any] = []
    seen = set()
    for rid in usable:
        g = group_of[rid]
        if g not in seen:
            seen.add(g)
            groups.append(g)
    if len(groups) < 2:
        raise _PartitionBuildError(
            "c07.insufficient_groups",
            "Need at least two groups to split without mixing the same property across train/test.",
            evidence={"n_groups": len(groups), "column": group_column},
        )

    if n_splits == 1:
        rng = np.random.RandomState(seed)
        shuffled = list(groups)
        rng.shuffle(shuffled)
        n_test = int(round(len(shuffled) * test_size))
        n_test = min(max(n_test, 1), len(shuffled) - 1)
        reserved_g = set(shuffled[:n_test])
        train_g = set(shuffled[n_test:])
        train = [rid for rid in usable if group_of[rid] in train_g]
        reserved = [rid for rid in usable if group_of[rid] in reserved_g]
        if not train or not reserved:
            raise _PartitionBuildError("c07.empty_partition", "Group holdout left one side empty.")
        fold = _fold_record(0, seed, train, reserved)
        fold["group_ids_train"] = _plain(sorted(train_g, key=_sort_key))
        fold["group_ids_reserved"] = _plain(sorted(reserved_g, key=_sort_key))
        return [fold], issues

    k = min(n_splits, len(groups))
    if k < n_splits:
        issues.append(
            make_issue(
                "c07.n_splits_reduced",
                "warning",
                "n_splits reduced because there are fewer groups than folds.",
                evidence={"requested": n_splits, "used": k},
            )
        )
    rng = np.random.RandomState(seed)
    shuffled = list(groups)
    rng.shuffle(shuffled)
    chunks = _even_chunks(shuffled, k)
    folds = []
    for i, reserved_groups in enumerate(chunks):
        reserved_g = set(reserved_groups)
        train_g = set(g for j, chunk in enumerate(chunks) if j != i for g in chunk)
        train = [rid for rid in usable if group_of[rid] in train_g]
        reserved = [rid for rid in usable if group_of[rid] in reserved_g]
        if not train or not reserved:
            continue
        fold = _fold_record(i, seed + i * 1009, train, reserved)
        fold["group_ids_train"] = _plain(sorted(train_g, key=_sort_key))
        fold["group_ids_reserved"] = _plain(sorted(reserved_g, key=_sort_key))
        folds.append(fold)
    if not folds:
        raise _PartitionBuildError("c07.empty_partition", "Group k-fold produced no usable partitions.")
    return folds, issues


def _temporal_folds(
    row_ids: Sequence[Any],
    input_bundle: Mapping[str, Any],
    time_column: str,
    n_splits: int,
    test_size: float,
    seed: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    issues: List[Dict[str, Any]] = []
    by_id = _records_by_id(input_bundle)
    dated: List[Tuple[Any, Any]] = []
    missing = []
    for rid in row_ids:
        rec = by_id.get(rid) or {}
        ts = _parse_time(rec.get(time_column))
        if ts is None:
            missing.append(rid)
            continue
        dated.append((ts, rid))
    if missing:
        issues.append(
            make_issue(
                "c07.missing_time_value",
                "warning",
                "Rows without a parseable date were left out of the temporal split (dates were not invented).",
                affected_ids=missing,
            )
        )
    if len(dated) < 2:
        raise _PartitionBuildError(
            "c07.insufficient_dates",
            "Need at least two dated rows for a temporal split.",
            evidence={"n_dated": len(dated), "column": time_column},
        )

    dated.sort(key=lambda item: (item[0], _sort_key(item[1])))
    # Whole timestamps stay on one side so contemporaneous rows do not cross.
    buckets: List[Tuple[Any, List[Any]]] = []
    for ts, rid in dated:
        if not buckets or buckets[-1][0] != ts:
            buckets.append((ts, [rid]))
        else:
            buckets[-1][1].append(rid)
    if len(buckets) < 2:
        raise _PartitionBuildError(
            "c07.temporal_no_cut",
            "All dated rows share one timestamp; a temporal cut would mix train and test.",
            evidence={"n_timestamps": len(buckets)},
        )

    rng = np.random.RandomState(seed)  # recorded for reproducibility; cut is chronological.
    _ = int(rng.randint(0, 2**31 - 1))

    if n_splits == 1:
        n_dated = sum(len(ids) for _, ids in buckets)
        n_test = int(round(n_dated * test_size))
        n_test = min(max(n_test, 1), n_dated - 1)
        reserved: List[Any] = []
        reserved_buckets = []
        for ts, ids in reversed(buckets):
            if len(reserved) >= n_test and reserved_buckets:
                break
            reserved_buckets.append((ts, ids))
            reserved.extend(ids)
        reserved_set = set(reserved)
        train = [rid for _, ids in buckets for rid in ids if rid not in reserved_set]
        reserved = [rid for _, ids in buckets for rid in ids if rid in reserved_set]
        if not train or not reserved:
            raise _PartitionBuildError("c07.empty_partition", "Temporal holdout left one side empty.")
        cut = reserved_buckets[-1][0] if reserved_buckets else None
        fold = _fold_record(0, seed, train, reserved)
        fold["time_cut"] = _time_to_text(cut)
        return [fold], issues

    k = min(n_splits, len(buckets) - 1)
    if k < 1:
        raise _PartitionBuildError("c07.temporal_no_cut", "Not enough distinct timestamps for temporal folds.")
    if k < n_splits:
        issues.append(
            make_issue(
                "c07.n_splits_reduced",
                "warning",
                "Temporal n_splits reduced to the number of expanding windows the timestamps allow.",
                evidence={"requested": n_splits, "used": k},
            )
        )
    chunks = _even_chunks(buckets, k + 1)
    folds = []
    for i in range(1, len(chunks)):
        train_buckets = [b for chunk in chunks[:i] for b in chunk]
        test_buckets = list(chunks[i])
        train = [rid for _, ids in train_buckets for rid in ids]
        reserved = [rid for _, ids in test_buckets for rid in ids]
        if not train or not reserved:
            continue
        fold = _fold_record(i - 1, seed + (i - 1) * 1009, train, reserved)
        fold["time_cut"] = _time_to_text(test_buckets[0][0]) if test_buckets else None
        folds.append(fold)
    if not folds:
        raise _PartitionBuildError("c07.empty_partition", "Temporal expanding window produced no usable partitions.")
    return folds, issues


def _fold_record(fold_id: int, seed: int, train: Sequence[Any], reserved: Sequence[Any]) -> Dict[str, Any]:
    return {
        "fold_id": int(fold_id),
        "seed": int(seed),
        "train_row_ids": list(train),
        "reserved_row_ids": list(reserved),
        "group_ids_train": None,
        "group_ids_reserved": None,
        "time_cut": None,
        "disjoint": True,
    }


def _even_chunks(items: Sequence[Any], k: int) -> List[List[Any]]:
    seq = list(items)
    k = max(int(k), 1)
    if k > len(seq):
        k = len(seq)
    sizes = [len(seq) // k] * k
    for i in range(len(seq) % k):
        sizes[i] += 1
    out: List[List[Any]] = []
    idx = 0
    for size in sizes:
        out.append(seq[idx: idx + size])
        idx += size
    return [chunk for chunk in out if chunk]


# ---------------------------------------------------------------------------
# Fit / predict / score
# ---------------------------------------------------------------------------


def _call_fit_select(
    fit_select_predictor: FitSelectPredictor,
    train_row_ids: Sequence[Any],
    seed: int,
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    try:
        handle = fit_select_predictor(list(train_row_ids), int(seed))
    except Exception as exc:
        return None, make_issue(
            "c07.fit_select_failed",
            "error",
            f"fit_select_predictor raised: {exc}",
            evidence={"type": type(exc).__name__},
        )
    if handle is None:
        return None, make_issue("c07.fit_select_failed", "error", "fit_select_predictor returned None.")
    status = _handle_status(handle)
    if status in {"error", "rejected"}:
        return handle, make_issue(
            "c07.fit_select_failed",
            "error",
            "fit_select_predictor returned a non-fitted handle.",
            evidence={"status": status},
        )
    return handle, None


def _call_predict(
    handle: Any,
    records: Sequence[Mapping[str, Any]],
    reserved_ids: Sequence[Any],
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    predict = _handle_predict(handle)
    if predict is None:
        issue = make_issue(
            "c07.predictor_missing",
            "error",
            "Fitted handle has no predict callable.",
        )
        return [_failed_prediction(rid, issue) for rid in reserved_ids], issue
    try:
        raw = predict(list(records))
    except Exception as exc:
        issue = make_issue(
            "c07.predictor_raised",
            "error",
            f"predict raised: {exc}",
            evidence={"type": type(exc).__name__},
        )
        return [_failed_prediction(rid, issue) for rid in reserved_ids], issue
    return _normalize_predictions(raw, reserved_ids), None


def _normalize_predictions(raw: Any, reserved_ids: Sequence[Any]) -> List[Dict[str, Any]]:
    if raw is None:
        issue = make_issue("c07.prediction_failed", "error", "predict returned None.")
        return [_failed_prediction(rid, issue) for rid in reserved_ids]
    if isinstance(raw, Mapping) and "predictions" in raw:
        raw = raw.get("predictions")
    items = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    by_id: Dict[Any, Dict[str, Any]] = {}
    positional: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        parsed = _parse_prediction_item(item, reserved_ids[idx] if idx < len(reserved_ids) else None)
        positional.append(parsed)
        if parsed.get("row_id") is not None:
            by_id[parsed["row_id"]] = parsed

    out: List[Dict[str, Any]] = []
    for idx, rid in enumerate(reserved_ids):
        if rid in by_id:
            pred = dict(by_id[rid])
        elif idx < len(positional) and positional[idx].get("row_id") in {None, rid}:
            pred = dict(positional[idx])
            pred["row_id"] = rid
        else:
            pred = _failed_prediction(
                rid,
                make_issue("c07.prediction_failed", "error", "No prediction returned for reserved row."),
            )
        pred["row_id"] = rid
        # Large residual is NOT a reason to drop or zero the value.
        if pred.get("status") == "ok":
            value = pred.get("value")
            number = _as_float(value)
            if number is None:
                pred = _failed_prediction(
                    rid,
                    pred.get("issue")
                    or make_issue(
                        "c07.prediction_failed",
                        "error",
                        "Prediction status=ok but value is not a finite number.",
                    ),
                )
            else:
                pred["value"] = number
        else:
            if pred.get("value") == 0 and pred.get("issue") is None:
                # Out-of-support must not become a silent zero.
                pred["value"] = None
                pred["issue"] = make_issue(
                    "c07.prediction_failed",
                    "error",
                    "Non-ok prediction must not be reported as zero.",
                )
            elif pred.get("status") != "ok":
                pred["value"] = None if pred.get("value") is None else _as_float(pred.get("value"))
                if pred.get("value") is not None:
                    # Keep numeric only if the callback explicitly failed after producing a number;
                    # coverage still treats it as failed, so it does not enter MAE.
                    pred["value"] = None
        out.append(pred)
    return out


def _parse_prediction_item(item: Any, default_id: Any) -> Dict[str, Any]:
    if isinstance(item, Mapping):
        status = str(item.get("status") or "ok")
        issue = item.get("issue")
        if status != "ok" and not issue:
            issue = make_issue(
                str(item.get("code") or "c07.prediction_failed"),
                "error",
                str(item.get("message") or "Prediction failed."),
                affected_ids=[item.get("row_id", default_id)] if item.get("row_id", default_id) is not None else [],
                evidence=dict(item.get("evidence") or {}),
            )
        return {
            "row_id": item.get("row_id", default_id),
            "status": status,
            "value": item.get("value"),
            "issue": issue,
        }
    number = _as_float(item)
    if number is None:
        return _failed_prediction(
            default_id,
            make_issue("c07.prediction_failed", "error", "Prediction is not a finite number."),
        )
    return {"row_id": default_id, "status": "ok", "value": number, "issue": None}


def _failed_prediction(row_id: Any, issue: Optional[Dict[str, Any]], y_true: Any = None) -> Dict[str, Any]:
    return {
        "row_id": row_id,
        "status": "failed",
        "value": None,
        "issue": issue,
        "y_true": y_true,
        "residual": None,
    }


def _score_predictions(
    predictions: Sequence[Mapping[str, Any]],
    *,
    train_ids: Sequence[Any],
    reserved_ids: Sequence[Any],
    input_bundle: Mapping[str, Any],
    target_col: Any,
    target_unit: Optional[str],
) -> Dict[str, Any]:
    reserved_list = list(reserved_ids)
    covered: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    missing_target: List[Any] = []
    rows: List[Dict[str, Any]] = []

    for pred in predictions:
        rid = pred.get("row_id")
        y_true = pred.get("y_true")
        if y_true is None:
            y_true = _target_value(input_bundle, target_col, rid)
        y_true_f = _as_float(y_true)
        status = pred.get("status")
        value = pred.get("value") if status == "ok" else None
        residual = None
        if status == "ok" and value is not None and y_true_f is not None:
            residual = float(value) - float(y_true_f)
        row = {
            "row_id": rid,
            "status": "ok" if status == "ok" and y_true_f is not None else "failed" if status != "ok" else "unscored_missing_target",
            "y_true": y_true_f,
            "y_pred": float(value) if status == "ok" and value is not None else None,
            "residual": _finite_or_none(residual) if residual is not None else None,
            "issue": pred.get("issue"),
        }
        rows.append(row)
        if y_true_f is None:
            missing_target.append(rid)
            continue
        if status == "ok" and value is not None:
            covered.append(row)
        else:
            failed.append(row)

    y_true_cov = [r["y_true"] for r in covered]
    y_pred_cov = [r["y_pred"] for r in covered]
    metrics = original_scale_metrics(y_true_cov, y_pred_cov, unit=target_unit)

    train_y = [_as_float(_target_value(input_bundle, target_col, rid)) for rid in train_ids]
    train_obs = [v for v in train_y if v is not None]
    train_mean = _finite_or_none(float(np.mean(train_obs))) if train_obs else None
    if train_mean is not None and y_true_cov:
        ref_pred = [train_mean] * len(y_true_cov)
        reference_metrics = original_scale_metrics(y_true_cov, ref_pred, unit=target_unit)
    else:
        reference_metrics = original_scale_metrics([], [], unit=target_unit)
    reference = {
        "method": "train_mean",
        "train_mean": train_mean,
        "mae": reference_metrics.get("mae"),
        "rmse": reference_metrics.get("rmse"),
        "relative_mae": reference_metrics.get("relative_mae"),
        "unit": target_unit,
        "scale": "original",
        "metrics_scope": "covered_cases_only",
        "same_covered_rows_as_metrics": True,
    }

    n_reserved = len(reserved_list)
    n_with_target = n_reserved - len(missing_target)
    n_covered = len(covered)
    n_failed = len(failed)
    denominator = n_with_target
    coverage_rate = (float(n_covered) / float(denominator)) if denominator else None

    metrics_block = {
        **metrics,
        "n_covered": n_covered,
        "n_reserved": n_reserved,
        "n_failed": n_failed,
        "n_missing_target": len(missing_target),
        "n_with_target": n_with_target,
        "coverage": _finite_or_none(coverage_rate) if coverage_rate is not None else None,
        "coverage_denominator": "n_reserved_with_observed_target",
        "coverage_denominator_n": denominator,
        "failed_remain_in_denominator": True,
        "n_train": len(list(train_ids)),
        "unit": target_unit,
        "scale": "original",
        "reference_mae": reference.get("mae"),
        "reference_rmse": reference.get("rmse"),
        "reference_method": "train_mean",
    }
    return {
        "metrics_block": metrics_block,
        "reference": reference,
        "predictions": rows,
        "covered_row_ids": [r["row_id"] for r in covered],
        "failed_row_ids": [r["row_id"] for r in failed],
        "missing_target_row_ids": missing_target,
    }


def _aggregate_fold_metrics(fold_metrics: Sequence[Mapping[str, Any]], unit: Optional[str]) -> Dict[str, Any]:
    mae_values = [m["mae"] for m in fold_metrics if m.get("mae") is not None]
    rmse_values = [m["rmse"] for m in fold_metrics if m.get("rmse") is not None]
    rel_values = [m["relative_mae"] for m in fold_metrics if m.get("relative_mae") is not None]
    coverage_values = [m["coverage"] for m in fold_metrics if m.get("coverage") is not None]
    ref_mae_values = [m["reference_mae"] for m in fold_metrics if m.get("reference_mae") is not None]

    def _stat(vals: Sequence[float]) -> Dict[str, Any]:
        arr = [float(v) for v in vals]
        if not arr:
            return {"mean": None, "std": None, "min": None, "max": None, "values": []}
        return {
            "mean": _finite_or_none(float(np.mean(arr))),
            "std": _finite_or_none(float(np.std(arr, ddof=1))) if len(arr) > 1 else 0.0,
            "min": _finite_or_none(float(np.min(arr))),
            "max": _finite_or_none(float(np.max(arr))),
            "values": [_finite_or_none(float(v)) for v in arr],
        }

    mae_stat = _stat(mae_values)
    rmse_stat = _stat(rmse_values)
    # Top-level metrics: if one fold, that fold; if many, mean PLUS the list (never only the mean).
    top_mae = fold_metrics[0].get("mae") if len(fold_metrics) == 1 else mae_stat["mean"]
    top_rmse = fold_metrics[0].get("rmse") if len(fold_metrics) == 1 else rmse_stat["mean"]
    top_rel = fold_metrics[0].get("relative_mae") if len(fold_metrics) == 1 else _stat(rel_values)["mean"]
    n_covered = int(sum(m.get("n_covered") or 0 for m in fold_metrics))
    n_reserved = int(sum(m.get("n_reserved") or 0 for m in fold_metrics))
    n_failed = int(sum(m.get("n_failed") or 0 for m in fold_metrics))
    n_with_target = int(sum(m.get("n_with_target") or 0 for m in fold_metrics))
    n_relative = int(sum(m.get("n_relative") or 0 for m in fold_metrics))
    coverage = (float(n_covered) / float(n_with_target)) if n_with_target else None

    metrics = {
        "unit": unit,
        "scale": "original",
        "mae": top_mae,
        "rmse": top_rmse,
        "relative_mae": top_rel,
        "relative_rmse": fold_metrics[0].get("relative_rmse") if len(fold_metrics) == 1 else _stat(
            [m["relative_rmse"] for m in fold_metrics if m.get("relative_rmse") is not None]
        )["mean"],
        "n_relative": n_relative,
        "n_covered": n_covered,
        "n_reserved": n_reserved,
        "n_failed": n_failed,
        "n_with_target": n_with_target,
        "coverage": _finite_or_none(coverage) if coverage is not None else None,
        "coverage_denominator": "n_reserved_with_observed_target",
        "coverage_denominator_n": n_with_target,
        "failed_remain_in_denominator": True,
        "metrics_scope": "covered_cases_only",
        "primary_metrics": ["mae", "rmse"],
        "relative_denominator_rule": _relative_rule_text(),
        "aggregate": "single_fold" if len(fold_metrics) == 1 else "mean_across_folds_see_variability",
        "reference_mae": fold_metrics[0].get("reference_mae") if len(fold_metrics) == 1 else _stat(ref_mae_values)["mean"],
        "reference_rmse": fold_metrics[0].get("reference_rmse") if len(fold_metrics) == 1 else None,
        "reference_method": "train_mean",
    }
    variability = {
        "n_folds": len(fold_metrics),
        "mae": mae_stat,
        "rmse": rmse_stat,
        "relative_mae": _stat(rel_values),
        "coverage": _stat(coverage_values),
        "reference_mae": _stat(ref_mae_values),
        "hidden_in_single_mean": False,
        "small_sample": bool(n_reserved < SMALL_SAMPLE_N),
    }
    reference = {
        "method": "train_mean",
        "mae": metrics["reference_mae"],
        "rmse": metrics["reference_rmse"],
        "unit": unit,
        "scale": "original",
        "metrics_scope": "covered_cases_only",
    }
    return {"metrics": metrics, "variability": variability, "reference": reference}


def _aggregate_coverage(
    predictions: Sequence[Mapping[str, Any]],
    folds: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    reserved = []
    for fold in folds:
        reserved.extend(list(fold.get("reserved_row_ids") or []))
    covered = [p["row_id"] for p in predictions if p.get("status") == "ok"]
    failed = [p["row_id"] for p in predictions if p.get("status") == "failed"]
    missing = [p["row_id"] for p in predictions if p.get("status") == "unscored_missing_target"]
    failures = []
    for p in predictions:
        if p.get("status") != "failed":
            continue
        issue = p.get("issue") or {}
        failures.append(
            {
                "row_id": p.get("row_id"),
                "code": issue.get("code") if isinstance(issue, Mapping) else "c07.prediction_failed",
                "message": issue.get("message") if isinstance(issue, Mapping) else "Prediction failed.",
                "evidence": issue.get("evidence") if isinstance(issue, Mapping) else {},
                "fold_id": p.get("fold_id"),
            }
        )
    n_with_target = len(reserved) - len(missing)
    n_covered = len(covered)
    return {
        "reserved_row_ids": list(reserved),
        "covered_row_ids": covered,
        "failed_row_ids": failed,
        "missing_target_row_ids": missing,
        "failures": failures,
        "n_reserved": len(reserved),
        "n_covered": n_covered,
        "n_failed": len(failed),
        "denominator": "n_reserved_with_observed_target",
        "denominator_n": n_with_target,
        "coverage": _finite_or_none(float(n_covered) / float(n_with_target)) if n_with_target else None,
        "failed_remain_in_denominator": True,
        "silent_drop": False,
    }


def _empty_evaluation_result(
    *,
    partition: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    limitations: Sequence[str],
    executed: Sequence[Mapping[str, Any]],
    seed: int,
    mode: str,
    budget: Mapping[str, Any],
    nested: bool,
    target_unit: Optional[str],
    elapsed: float,
    n_fit_calls: int,
    n_predict_calls: int,
    status: str,
) -> Dict[str, Any]:
    empty_metrics = original_scale_metrics([], [], unit=target_unit)
    empty_metrics.update(
        {
            "n_covered": 0,
            "n_reserved": 0,
            "n_failed": 0,
            "n_with_target": 0,
            "coverage": None,
            "coverage_denominator": "n_reserved_with_observed_target",
            "coverage_denominator_n": 0,
            "failed_remain_in_denominator": True,
            "reference_mae": None,
            "reference_rmse": None,
            "reference_method": "train_mean",
            "aggregate": "none",
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": EVALUATION_RESULT_KIND,
        "status": status,
        "metrics": empty_metrics,
        "reference": {
            "method": "train_mean",
            "mae": None,
            "rmse": None,
            "unit": target_unit,
            "scale": "original",
            "metrics_scope": "covered_cases_only",
        },
        "coverage": {
            "reserved_row_ids": [],
            "covered_row_ids": [],
            "failed_row_ids": [],
            "missing_target_row_ids": [],
            "failures": [],
            "n_reserved": 0,
            "n_covered": 0,
            "n_failed": 0,
            "denominator": "n_reserved_with_observed_target",
            "denominator_n": 0,
            "coverage": None,
            "failed_remain_in_denominator": True,
            "silent_drop": False,
        },
        "partition": {
            "method": partition.get("method"),
            "seed": int(seed),
            "test_size": partition.get("test_size"),
            "n_splits": partition.get("n_splits"),
            "group_column": partition.get("group_column"),
            "time_column": partition.get("time_column"),
            "invented_groups": False,
            "folds": partition.get("folds") or [],
            "nested": None,
        },
        "fold_metrics": [],
        "fold_traces": [],
        "variability": {
            "n_folds": 0,
            "mae": {"mean": None, "std": None, "values": []},
            "rmse": {"mean": None, "std": None, "values": []},
            "hidden_in_single_mean": False,
            "small_sample": True,
        },
        "predictions": [],
        "generalization": {
            "kind": "predictive_generalization",
            "not_normative_classification": True,
            "not_interval_stability": True,
        },
        "normative_label": {
            "applied": False,
            "grau_fundamentacao": None,
            "grau_precisao": None,
            "reason": "C07 does not assign NBR grades.",
        },
        "statistical_inference": {
            "post_selection_guarantee": False,
            "pvalues_are_post_selection_valid": False,
            "intervals_are_post_selection_valid": False,
            "note": "No post-selection inference guarantee.",
        },
        "usable_for_model_selection": False,
        "winner_retrained_on_full_data": False,
        "reserved_filtered_by_error": False,
        "procedure_provenance": {
            "evaluated_unit": "full_procedure",
            "evaluation_seed": int(seed),
            "seeds": [int(seed)],
            "nested": nested,
            "external_scores_fed_to_selection": False,
            "mode": mode,
            "budget": dict(budget),
            "executed": list(executed),
            "cost": {
                "elapsed_seconds": round(elapsed, 6),
                "n_fit_select_calls": n_fit_calls,
                "n_predict_calls": n_predict_calls,
                "n_folds_executed": 0,
            },
            "scale": "original",
            "target_unit": target_unit,
        },
        "stability": None,
        "limitations": list(limitations),
        "issues": list(issues),
    }


# ---------------------------------------------------------------------------
# Bundle / spec helpers
# ---------------------------------------------------------------------------


def _evaluation_policy(request_spec: Mapping[str, Any]) -> Dict[str, Any]:
    policy = request_spec.get("evaluation_policy")
    if policy is None:
        return {}
    if not isinstance(policy, Mapping):
        return {}
    return dict(policy)


def _validate_request_spec(request_spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if not isinstance(request_spec, Mapping):
        return [make_issue("c07.invalid_request_spec", "error", "request_spec must be a mapping.")]
    if not request_spec.get("target_col"):
        issues.append(make_issue("c07.missing_target_col", "error", "request_spec.target_col is required."))
    cols = request_spec.get("candidate_cols", None)
    if isinstance(cols, list) and len(cols) == 0:
        issues.append(
            make_issue(
                "c07.empty_candidate_cols",
                "error",
                "candidate_cols=[] authorizes no predictors (it does not mean 'all').",
            )
        )
    return issues


def _resolve_mode(policy: Mapping[str, Any]) -> str:
    mode = str(policy.get("mode") or "full").strip().lower()
    if mode in {"fast", "full"}:
        return mode
    return "full"


def _resolve_budget(policy: Mapping[str, Any], mode: str) -> Dict[str, Any]:
    raw = policy.get("budget") if isinstance(policy.get("budget"), Mapping) else {}
    budget = dict(raw)
    if mode == "fast":
        budget.setdefault("max_folds", 2)
        budget.setdefault("pipeline_bootstrap_replicates", 3)
        budget.setdefault("fixed_model_perturbations", 3)
    else:
        budget.setdefault("pipeline_bootstrap_replicates", 10)
        budget.setdefault("fixed_model_perturbations", 5)
    budget.setdefault("perturbation_relative_scale", 0.01)
    budget["mode"] = mode
    return budget


def _resolve_group_column(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    method: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    policy = _evaluation_policy(request_spec)
    requested = policy.get("group_column")
    if requested:
        if _column_exists(input_bundle, requested):
            return str(requested), None
        return None, make_issue(
            "c07.no_group_metadata",
            "error" if method == "group" else "warning",
            f"evaluation_policy.group_column={requested!r} is not present in the bundle.",
            evidence={"requested": requested},
        )
    # Do not treat role=identifier as a grouping key: that role is the row id, not a property group.
    return None, None


def _resolve_time_column(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    method: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    policy = _evaluation_policy(request_spec)
    requested = policy.get("time_column")
    if requested:
        if _column_exists(input_bundle, requested):
            return str(requested), None
        return None, make_issue(
            "c07.no_time_metadata",
            "error" if method == "temporal" else "warning",
            f"evaluation_policy.time_column={requested!r} is not present in the bundle.",
            evidence={"requested": requested},
        )
    roles = request_spec.get("roles") if isinstance(request_spec.get("roles"), Mapping) else {}
    date_cols = [name for name, role in roles.items() if str(role).lower() == "date"]
    for name in date_cols:
        if _column_exists(input_bundle, name):
            return str(name), None
    if method == "temporal":
        return None, make_issue(
            "c07.no_time_metadata",
            "error",
            "Temporal split requested but no date role/column is available; dates were not invented.",
        )
    return None, None


def _column_exists(input_bundle: Mapping[str, Any], name: str) -> bool:
    records = _parsed_records(input_bundle)
    if records:
        return name in records[0]
    frame = input_bundle.get("parsed_frame")
    if isinstance(frame, pd.DataFrame):
        return name in frame.columns
    return False


def _parsed_records(input_bundle: Mapping[str, Any]) -> Optional[List[Dict[str, Any]]]:
    parsed = input_bundle.get("parsed_frame")
    if parsed is None:
        return None
    if isinstance(parsed, pd.DataFrame):
        df = parsed
        if "row_id" not in df.columns:
            return None
        return df.to_dict(orient="records")
    if isinstance(parsed, list):
        return [dict(item) for item in parsed if isinstance(item, Mapping)]
    if isinstance(parsed, Mapping):
        out = []
        for rid, rec in parsed.items():
            if isinstance(rec, Mapping):
                item = dict(rec)
                item.setdefault("row_id", rid)
                out.append(item)
        return out
    return None


def _records_by_id(input_bundle: Mapping[str, Any]) -> Dict[Any, Dict[str, Any]]:
    records = _parsed_records(input_bundle) or []
    return {rec.get("row_id"): rec for rec in records if rec.get("row_id") is not None}


def _target_value(input_bundle: Mapping[str, Any], target_col: Any, row_id: Any) -> Any:
    if not target_col:
        return None
    rec = _records_by_id(input_bundle).get(row_id) or {}
    if target_col in rec:
        return rec.get(target_col)
    ledger = input_bundle.get("row_ledger")
    if isinstance(ledger, Mapping):
        entry = ledger.get(row_id) or {}
        if isinstance(entry, Mapping) and "observed_target" in entry:
            return entry.get("observed_target")
    return None


def _parse_time(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def _time_to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.isoformat()
    except Exception:
        return str(value)


def _handle_status(handle: Any) -> str:
    if isinstance(handle, Mapping):
        return str(handle.get("status") or "fitted")
    return str(getattr(handle, "status", "fitted") or "fitted")


def _handle_predict(handle: Any) -> Optional[Callable]:
    if callable(handle) and not isinstance(handle, Mapping):
        predict = getattr(handle, "predict", None)
        if callable(predict):
            return predict
        return handle
    if isinstance(handle, Mapping):
        predict = handle.get("predict")
        return predict if callable(predict) else None
    predict = getattr(handle, "predict", None)
    return predict if callable(predict) else None


def _safe_trace(handle: Any) -> Dict[str, Any]:
    if isinstance(handle, Mapping):
        trace = handle.get("trace")
        return dict(trace) if isinstance(trace, Mapping) else {}
    trace = getattr(handle, "trace", None)
    return dict(trace) if isinstance(trace, Mapping) else {}


def _sanitize_trace(trace: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep encoder/selection provenance; drop callables, frames, model objects."""
    if not isinstance(trace, Mapping):
        return {}
    allowed = (
        "used_row_ids",
        "selected_features",
        "selected_base_variables",
        "encoder_state",
        "impute_values",
        "categories",
        "candidates",
        "model_spec",
        "issues",
        "status",
        "search_audit",
    )
    out: Dict[str, Any] = {}
    for key in allowed:
        if key not in trace:
            continue
        value = trace[key]
        if key == "candidates" and isinstance(value, list):
            cleaned = []
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                cleaned.append(
                    {
                        k: item.get(k)
                        for k in (
                            "candidate_id",
                            "features",
                            "base_variables",
                            "internal_score",
                            "train_score",
                            "status",
                        )
                        if k in item
                    }
                )
            out[key] = cleaned
            continue
        if callable(value):
            continue
        if isinstance(value, pd.DataFrame):
            continue
        out[key] = value
    return out


def _trace_used_row_ids(handle: Any) -> List[Any]:
    trace = _safe_trace(handle)
    used = trace.get("used_row_ids")
    if isinstance(used, list):
        return list(used)
    if isinstance(handle, Mapping):
        used = handle.get("used_row_ids")
        if isinstance(used, list):
            return list(used)
    return []


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _relative_rule_text() -> str:
    return "abs(y_true) >= max(1e-12, 1e-6 * median(|y_true|)); undefined otherwise, never a silent zero."


def _sort_key(value: Any) -> Tuple[int, str]:
    return (0, str(value))


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


__all__ = [
    "SCHEMA_VERSION",
    "EVALUATION_RESULT_KIND",
    "evaluate_procedure",
    "partition_external",
    "extract_row_ids",
    "records_for_rows",
    "original_scale_metrics",
    "detect_preprocessing_leak",
    "make_issue",
]
