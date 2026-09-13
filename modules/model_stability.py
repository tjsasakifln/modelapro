"""Stability analyses for the evaluation procedure (C07).

Names are intentional and distinct:

- ``pipeline_bootstrap``: resample training ids and re-run
  ``fit_select_predictor`` (the full procedure). Not a confidence interval
  and not a p-value repair after selection.
- ``fixed_model_sensitivity``: keep the fitted predictor fixed; perturb
  numeric features of reserved rows. This is not pipeline bootstrap.
- ``variable_selection_frequency``: how often each variable is selected
  across procedure resamples.
- ``candidate_dispersion``: spread among *internal* candidate traces from
  one fit (not an external ranking signal).
- ``justified_revision_sensitivity``: refit after declared, identified
  exclusions/revisions.

Enablement is budgeted. Fast mode records exactly which analyses ran.
Results are JSON-serializable mappings, not plots without underlying data.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

from modules.model_evaluation import (
    SCHEMA_VERSION,
    _as_float,
    _call_fit_select,
    _call_predict,
    _evaluation_policy,
    _finite_or_none,
    _plain,
    _resolve_budget,
    _resolve_mode,
    _safe_trace,
    _target_value,
    make_issue,
    original_scale_metrics,
    records_for_rows,
)

STABILITY_RESULT_KIND = "stability_result"
PIPELINE_BOOTSTRAP = "pipeline_bootstrap"
FIXED_MODEL_SENSITIVITY = "fixed_model_sensitivity"
VARIABLE_SELECTION_FREQUENCY = "variable_selection_frequency"
CANDIDATE_DISPERSION = "candidate_dispersion"
JUSTIFIED_REVISION_SENSITIVITY = "justified_revision_sensitivity"

ORIGIN = "C07"


def analyze_stability(
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    fit_select_predictor: Callable[[Sequence[Any], int], Any],
    seed: int,
    *,
    evaluation_result: Optional[Mapping[str, Any]] = None,
    fitted_folds: Optional[Sequence[Mapping[str, Any]]] = None,
    mode: Optional[str] = None,
    budget: Optional[Mapping[str, Any]] = None,
    revisions: Optional[Sequence[Mapping[str, Any]]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """Run named stability analyses under an explicit budget/mode."""
    started = time.perf_counter()
    policy = _evaluation_policy(request_spec)
    resolved_mode = mode or _resolve_mode(policy)
    resolved_budget = dict(budget or _resolve_budget(policy, resolved_mode))
    issues: List[Dict[str, Any]] = []
    executed_analyses: List[str] = []
    skipped: List[Dict[str, Any]] = []
    n_fit_calls = 0
    n_predict_calls = 0

    def _cancelled() -> bool:
        return bool(cancel_requested is not None and cancel_requested())

    def _progress(stage: str, fraction: Optional[float]) -> None:
        if progress_callback is None:
            return
        progress_callback({"stage": f"stability:{stage}", "progress": _plain(fraction)})

    folds = _resolve_folds(evaluation_result, fitted_folds)
    if not folds:
        issues.append(
            make_issue(
                "c07.stability_no_folds",
                "warning",
                "Stability analysis skipped: no fitted folds were provided.",
            )
        )
        elapsed = time.perf_counter() - started
        return _plain(
            _empty_stability(
                seed=int(seed),
                mode=resolved_mode,
                budget=resolved_budget,
                issues=issues,
                executed_analyses=executed_analyses,
                skipped=skipped,
                elapsed=elapsed,
                n_fit_calls=0,
                n_predict_calls=0,
            )
        )

    # Analyses requested: full runs all named analyses; fast still runs them
    # with smaller replicate counts so the names stay present and honest.
    requested = policy.get("stability_analyses")
    if requested is None:
        requested = [
            PIPELINE_BOOTSTRAP,
            FIXED_MODEL_SENSITIVITY,
            VARIABLE_SELECTION_FREQUENCY,
            CANDIDATE_DISPERSION,
            JUSTIFIED_REVISION_SENSITIVITY,
        ]
    requested = [str(name) for name in requested]

    primary = folds[0]
    train_ids = list(primary.get("train_row_ids") or [])
    reserved_ids = list(primary.get("reserved_row_ids") or [])
    predictor = primary.get("predictor")
    fold_seed = int(primary.get("seed", seed))
    target_col = request_spec.get("target_col")
    target_unit = request_spec.get("target_unit") or None

    pipeline_block: Dict[str, Any]
    selection_block: Dict[str, Any]

    if PIPELINE_BOOTSTRAP in requested and not _cancelled():
        _progress(PIPELINE_BOOTSTRAP, 0.2)
        pipeline_block, extra_fits, extra_predicts = _pipeline_bootstrap(
            input_bundle=input_bundle,
            request_spec=request_spec,
            fit_select_predictor=fit_select_predictor,
            train_ids=train_ids,
            reserved_ids=reserved_ids,
            seed=int(seed),
            n_replicates=int(resolved_budget.get("pipeline_bootstrap_replicates") or 0),
            target_col=target_col,
            target_unit=target_unit,
            cancel_requested=cancel_requested,
        )
        n_fit_calls += extra_fits
        n_predict_calls += extra_predicts
        executed_analyses.append(PIPELINE_BOOTSTRAP)
        issues.extend(pipeline_block.pop("issues", []))
    else:
        pipeline_block = _not_executed(
            PIPELINE_BOOTSTRAP,
            "Not requested or cancelled." if PIPELINE_BOOTSTRAP in requested else "Not in stability_analyses.",
        )
        skipped.append({"analysis": PIPELINE_BOOTSTRAP, "reason": pipeline_block["reason"]})

    if VARIABLE_SELECTION_FREQUENCY in requested:
        selection_block = _selection_frequency_from_pipeline(pipeline_block)
        executed_analyses.append(VARIABLE_SELECTION_FREQUENCY)
    else:
        selection_block = _not_executed(VARIABLE_SELECTION_FREQUENCY, "Not in stability_analyses.")
        skipped.append({"analysis": VARIABLE_SELECTION_FREQUENCY, "reason": selection_block["reason"]})

    if FIXED_MODEL_SENSITIVITY in requested and predictor is not None and not _cancelled():
        _progress(FIXED_MODEL_SENSITIVITY, 0.55)
        fixed_block, extra_predicts = _fixed_model_sensitivity(
            input_bundle=input_bundle,
            request_spec=request_spec,
            predictor=predictor,
            reserved_ids=reserved_ids,
            seed=int(seed) + 23,
            n_perturbations=int(resolved_budget.get("fixed_model_perturbations") or 0),
            relative_scale=float(resolved_budget.get("perturbation_relative_scale") or 0.01),
            target_unit=target_unit,
        )
        n_predict_calls += extra_predicts
        executed_analyses.append(FIXED_MODEL_SENSITIVITY)
        issues.extend(fixed_block.pop("issues", []))
    else:
        reason = "No fitted predictor" if predictor is None else "Not requested or cancelled."
        fixed_block = _not_executed(FIXED_MODEL_SENSITIVITY, reason)
        skipped.append({"analysis": FIXED_MODEL_SENSITIVITY, "reason": reason})

    if CANDIDATE_DISPERSION in requested:
        _progress(CANDIDATE_DISPERSION, 0.7)
        candidate_block = _candidate_dispersion(_safe_trace(predictor) if predictor is not None else primary.get("trace") or {})
        executed_analyses.append(CANDIDATE_DISPERSION)
    else:
        candidate_block = _not_executed(CANDIDATE_DISPERSION, "Not in stability_analyses.")
        skipped.append({"analysis": CANDIDATE_DISPERSION, "reason": candidate_block["reason"]})

    revision_list = list(revisions or policy.get("revisions") or [])
    if JUSTIFIED_REVISION_SENSITIVITY in requested and revision_list and not _cancelled():
        _progress(JUSTIFIED_REVISION_SENSITIVITY, 0.85)
        revision_block, extra_fits, extra_predicts = _revision_sensitivity(
            input_bundle=input_bundle,
            request_spec=request_spec,
            fit_select_predictor=fit_select_predictor,
            train_ids=train_ids,
            reserved_ids=reserved_ids,
            seed=fold_seed,
            revisions=revision_list,
            baseline_predictor=predictor,
            target_col=target_col,
            target_unit=target_unit,
        )
        n_fit_calls += extra_fits
        n_predict_calls += extra_predicts
        executed_analyses.append(JUSTIFIED_REVISION_SENSITIVITY)
        issues.extend(revision_block.pop("issues", []))
    else:
        if JUSTIFIED_REVISION_SENSITIVITY not in requested:
            reason = "Not in stability_analyses."
        elif not revision_list:
            reason = "No justified revisions supplied; analysis not invented."
        else:
            reason = "Cancelled."
        revision_block = _not_executed(JUSTIFIED_REVISION_SENSITIVITY, reason)
        skipped.append({"analysis": JUSTIFIED_REVISION_SENSITIVITY, "reason": reason})

    elapsed = time.perf_counter() - started
    _progress("done", 1.0)
    return _plain(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": STABILITY_RESULT_KIND,
            "status": "completed",
            "mode": resolved_mode,
            "budget": dict(resolved_budget),
            "seed": int(seed),
            PIPELINE_BOOTSTRAP: pipeline_block,
            FIXED_MODEL_SENSITIVITY: fixed_block,
            VARIABLE_SELECTION_FREQUENCY: selection_block,
            CANDIDATE_DISPERSION: candidate_block,
            JUSTIFIED_REVISION_SENSITIVITY: revision_block,
            "executed_analyses": executed_analyses,
            "skipped_analyses": skipped,
            "names_are_distinct": True,
            "pipeline_bootstrap_is_not_fixed_model_sensitivity": True,
            "not_normative_grade": True,
            "not_post_selection_confidence_interval": True,
            "usable_for_model_selection": False,
            "cost": {
                "elapsed_seconds": round(elapsed, 6),
                "n_fit_select_calls": n_fit_calls,
                "n_predict_calls": n_predict_calls,
                "n_folds_used": len(folds),
                "limits": {
                    "pipeline_bootstrap_replicates": resolved_budget.get("pipeline_bootstrap_replicates"),
                    "fixed_model_perturbations": resolved_budget.get("fixed_model_perturbations"),
                    "mode": resolved_mode,
                },
            },
            "limitations": _stability_limitations(resolved_mode, pipeline_block, folds),
            "issues": issues,
            "underlying_data": {
                PIPELINE_BOOTSTRAP: pipeline_block.get("replicates"),
                FIXED_MODEL_SENSITIVITY: fixed_block.get("perturbations"),
                JUSTIFIED_REVISION_SENSITIVITY: revision_block.get("revisions"),
            },
        }
    )


def _resolve_folds(
    evaluation_result: Optional[Mapping[str, Any]],
    fitted_folds: Optional[Sequence[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    if fitted_folds:
        return [dict(item) for item in fitted_folds]
    if not evaluation_result:
        return []
    partition = evaluation_result.get("partition") or {}
    folds = []
    for fold in partition.get("folds") or []:
        folds.append(
            {
                "fold_id": fold.get("fold_id"),
                "seed": fold.get("seed"),
                "train_row_ids": list(fold.get("train_row_ids") or []),
                "reserved_row_ids": list(fold.get("reserved_row_ids") or []),
                "predictor": None,
                "trace": {},
            }
        )
    return folds


def _pipeline_bootstrap(
    *,
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    fit_select_predictor: Callable,
    train_ids: Sequence[Any],
    reserved_ids: Sequence[Any],
    seed: int,
    n_replicates: int,
    target_col: Any,
    target_unit: Optional[str],
    cancel_requested: Optional[Callable[[], bool]],
) -> tuple:
    issues: List[Dict[str, Any]] = []
    n_fit = 0
    n_predict = 0
    if n_replicates < 1 or len(train_ids) < 2:
        return (
            {
                "executed": False,
                "reason": "Insufficient replicates or training rows.",
                "n_replicates": 0,
                "name": PIPELINE_BOOTSTRAP,
                "not_a_confidence_interval": True,
                "issues": issues,
            },
            0,
            0,
        )

    rng = np.random.RandomState(int(seed) + 17)
    train_list = list(train_ids)
    reserved_list = list(reserved_ids)
    replicates: List[Dict[str, Any]] = []
    per_row: Dict[Any, List[float]] = {rid: [] for rid in reserved_list}
    selected_counts: Dict[str, int] = {}
    mae_values: List[float] = []

    for r in range(int(n_replicates)):
        if cancel_requested is not None and cancel_requested():
            issues.append(make_issue("c07.cancelled", "warning", "Pipeline bootstrap cancelled."))
            break
        draws = rng.randint(0, len(train_list), size=len(train_list))
        boot_ids = [train_list[int(i)] for i in draws]
        handle, fit_issue = _call_fit_select(fit_select_predictor, boot_ids, int(seed) + 1000 + r)
        n_fit += 1
        if fit_issue:
            replicates.append(
                {
                    "replicate": r,
                    "status": "error",
                    "n_train_draws": len(boot_ids),
                    "issue": fit_issue,
                    "selected_base_variables": [],
                    "mae": None,
                }
            )
            continue
        records = records_for_rows(input_bundle, request_spec, reserved_list)
        predictions, _pred_issue = _call_predict(handle, records, reserved_list)
        n_predict += 1
        y_true = []
        y_pred = []
        for pred in predictions:
            rid = pred.get("row_id")
            observed = _as_float(_target_value(input_bundle, target_col, rid))
            value = pred.get("value") if pred.get("status") == "ok" else None
            if observed is not None and value is not None:
                y_true.append(observed)
                y_pred.append(float(value))
                per_row[rid].append(float(value))
        metrics = original_scale_metrics(y_true, y_pred, unit=target_unit)
        if metrics.get("mae") is not None:
            mae_values.append(float(metrics["mae"]))
        trace = _safe_trace(handle)
        selected = [
            str(name)
            for name in (trace.get("selected_base_variables") or trace.get("selected_features") or [])
        ]
        for name in selected:
            selected_counts[name] = selected_counts.get(name, 0) + 1
        replicates.append(
            {
                "replicate": r,
                "status": "ok",
                "n_train_draws": len(boot_ids),
                "unique_train_ids": len(set(boot_ids)),
                "selected_base_variables": selected,
                "mae": metrics.get("mae"),
                "rmse": metrics.get("rmse"),
                "n_covered": metrics.get("n"),
            }
        )

    row_dispersion = []
    for rid, values in per_row.items():
        if len(values) < 2:
            row_dispersion.append({"row_id": rid, "n": len(values), "std": None, "mean": _finite_or_none(values[0]) if values else None})
            continue
        row_dispersion.append(
            {
                "row_id": rid,
                "n": len(values),
                "mean": _finite_or_none(float(np.mean(values))),
                "std": _finite_or_none(float(np.std(values, ddof=1))),
                "min": _finite_or_none(float(np.min(values))),
                "max": _finite_or_none(float(np.max(values))),
                "values": [_finite_or_none(float(v)) for v in values],
            }
        )

    n_ok = sum(1 for item in replicates if item.get("status") == "ok")
    block = {
        "executed": True,
        "name": PIPELINE_BOOTSTRAP,
        "not_a_confidence_interval": True,
        "not_fixed_model_sensitivity": True,
        "n_replicates_requested": int(n_replicates),
        "n_replicates_ok": n_ok,
        "mae_across_replicates": {
            "mean": _finite_or_none(float(np.mean(mae_values))) if mae_values else None,
            "std": _finite_or_none(float(np.std(mae_values, ddof=1))) if len(mae_values) > 1 else (0.0 if mae_values else None),
            "values": [_finite_or_none(v) for v in mae_values],
        },
        "prediction_dispersion_by_row": row_dispersion,
        "selection_counts": selected_counts,
        "replicates": replicates,
        "reserved_row_ids": list(reserved_list),
        "issues": issues,
    }
    return block, n_fit, n_predict


def _selection_frequency_from_pipeline(pipeline_block: Mapping[str, Any]) -> Dict[str, Any]:
    if not pipeline_block.get("executed"):
        return {
            "executed": False,
            "name": VARIABLE_SELECTION_FREQUENCY,
            "reason": "pipeline_bootstrap did not execute; frequencies are not invented.",
            "frequencies": {},
        }
    counts = dict(pipeline_block.get("selection_counts") or {})
    n_ok = int(pipeline_block.get("n_replicates_ok") or 0)
    frequencies = {}
    for name, count in counts.items():
        frequencies[name] = {
            "count": int(count),
            "n_replicates_ok": n_ok,
            "frequency": _finite_or_none(float(count) / float(n_ok)) if n_ok else None,
        }
    return {
        "executed": True,
        "name": VARIABLE_SELECTION_FREQUENCY,
        "source": PIPELINE_BOOTSTRAP,
        "frequencies": frequencies,
        "n_replicates_ok": n_ok,
    }


def _fixed_model_sensitivity(
    *,
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    predictor: Any,
    reserved_ids: Sequence[Any],
    seed: int,
    n_perturbations: int,
    relative_scale: float,
    target_unit: Optional[str],
) -> tuple:
    issues: List[Dict[str, Any]] = []
    n_predict = 0
    if n_perturbations < 1:
        return (
            {
                "executed": False,
                "name": FIXED_MODEL_SENSITIVITY,
                "reason": "n_perturbations < 1",
                "not_pipeline_bootstrap": True,
                "issues": issues,
            },
            0,
        )

    records = records_for_rows(input_bundle, request_spec, reserved_ids)
    baseline, _ = _call_predict(predictor, records, reserved_ids)
    n_predict += 1
    baseline_by_id = {item.get("row_id"): item.get("value") for item in baseline if item.get("status") == "ok"}

    rng = np.random.RandomState(int(seed))
    numeric_keys = _numeric_feature_keys(records)
    perturbations: List[Dict[str, Any]] = []
    per_row: Dict[Any, List[float]] = {rid: [] for rid in reserved_ids}

    for p in range(int(n_perturbations)):
        perturbed = [_perturb_record(rec, numeric_keys, rng, relative_scale) for rec in records]
        preds, _ = _call_predict(predictor, perturbed, reserved_ids)
        n_predict += 1
        row_values = {}
        for item in preds:
            rid = item.get("row_id")
            value = item.get("value") if item.get("status") == "ok" else None
            row_values[rid] = value
            if value is not None:
                per_row[rid].append(float(value))
        perturbations.append(
            {
                "perturbation": p,
                "relative_scale": relative_scale,
                "values": row_values,
            }
        )

    dispersion = []
    for rid, values in per_row.items():
        base = baseline_by_id.get(rid)
        if len(values) < 2:
            std = None
        else:
            std = _finite_or_none(float(np.std(values, ddof=1)))
        dispersion.append(
            {
                "row_id": rid,
                "baseline": _finite_or_none(float(base)) if base is not None else None,
                "n": len(values),
                "mean": _finite_or_none(float(np.mean(values))) if values else None,
                "std": std,
                "values": [_finite_or_none(float(v)) for v in values],
            }
        )

    block = {
        "executed": True,
        "name": FIXED_MODEL_SENSITIVITY,
        "not_pipeline_bootstrap": True,
        "model_refit": False,
        "n_perturbations": int(n_perturbations),
        "relative_scale": float(relative_scale),
        "numeric_features_perturbed": numeric_keys,
        "prediction_dispersion_by_row": dispersion,
        "perturbations": perturbations,
        "unit": target_unit,
        "issues": issues,
    }
    return block, n_predict


def _candidate_dispersion(trace: Mapping[str, Any]) -> Dict[str, Any]:
    candidates = trace.get("candidates") if isinstance(trace, Mapping) else None
    if not isinstance(candidates, list) or not candidates:
        return {
            "executed": False,
            "name": CANDIDATE_DISPERSION,
            "reason": "Callback trace has no candidates list; dispersion was not invented.",
            "used_for_selection": False,
            "n_candidates": 0,
        }
    scores = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        score = item.get("internal_score")
        if score is None:
            score = item.get("train_score")
        number = _as_float(score)
        if number is not None:
            scores.append(number)
    std = _finite_or_none(float(np.std(scores, ddof=1))) if len(scores) > 1 else (0.0 if scores else None)
    return {
        "executed": True,
        "name": CANDIDATE_DISPERSION,
        "used_for_selection": False,
        "source": "callback_trace.candidates.internal_score",
        "n_candidates": len(candidates),
        "n_with_internal_score": len(scores),
        "internal_score_mean": _finite_or_none(float(np.mean(scores))) if scores else None,
        "internal_score_std": std,
        "internal_score_min": _finite_or_none(float(np.min(scores))) if scores else None,
        "internal_score_max": _finite_or_none(float(np.max(scores))) if scores else None,
        "internal_scores": [_finite_or_none(s) for s in scores],
        "note": "External reserved scores are not used to rank these candidates.",
    }


def _revision_sensitivity(
    *,
    input_bundle: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    fit_select_predictor: Callable,
    train_ids: Sequence[Any],
    reserved_ids: Sequence[Any],
    seed: int,
    revisions: Sequence[Mapping[str, Any]],
    baseline_predictor: Any,
    target_col: Any,
    target_unit: Optional[str],
) -> tuple:
    issues: List[Dict[str, Any]] = []
    n_fit = 0
    n_predict = 0
    train_set = list(train_ids)
    reserved_list = list(reserved_ids)

    baseline_values = {}
    if baseline_predictor is not None:
        records = records_for_rows(input_bundle, request_spec, reserved_list)
        preds, _ = _call_predict(baseline_predictor, records, reserved_list)
        n_predict += 1
        for item in preds:
            if item.get("status") == "ok":
                baseline_values[item.get("row_id")] = item.get("value")

    rows: List[Dict[str, Any]] = []
    for index, revision in enumerate(revisions):
        revision_id = revision.get("revision_id") or revision.get("id") or f"revision_{index}"
        exclude = list(revision.get("exclude_row_ids") or revision.get("excluded_row_ids") or [])
        reason = revision.get("reason")
        revised_train = [rid for rid in train_set if rid not in set(exclude)]
        reserved_overlap = [rid for rid in reserved_list if rid in set(exclude)]
        if reserved_overlap:
            issues.append(
                make_issue(
                    "c07.revision_touches_reserved",
                    "warning",
                    "Justified revision lists reserved ids; those ids are not dropped from the original evaluation coverage.",
                    affected_ids=reserved_overlap,
                    evidence={"revision_id": revision_id},
                )
            )
        if len(revised_train) < 2:
            rows.append(
                {
                    "revision_id": revision_id,
                    "reason": reason,
                    "status": "error",
                    "n_train": len(revised_train),
                    "exclude_row_ids": exclude,
                    "mae": None,
                }
            )
            continue
        handle, fit_issue = _call_fit_select(fit_select_predictor, revised_train, int(seed) + 3000 + index)
        n_fit += 1
        if fit_issue:
            rows.append(
                {
                    "revision_id": revision_id,
                    "reason": reason,
                    "status": "error",
                    "issue": fit_issue,
                    "exclude_row_ids": exclude,
                    "n_train": len(revised_train),
                }
            )
            continue
        records = records_for_rows(input_bundle, request_spec, reserved_list)
        preds, _ = _call_predict(handle, records, reserved_list)
        n_predict += 1
        y_true = []
        y_pred = []
        deltas = []
        for item in preds:
            rid = item.get("row_id")
            observed = _as_float(_target_value(input_bundle, target_col, rid))
            value = item.get("value") if item.get("status") == "ok" else None
            if observed is not None and value is not None:
                y_true.append(observed)
                y_pred.append(float(value))
            if value is not None and rid in baseline_values and baseline_values[rid] is not None:
                deltas.append(float(value) - float(baseline_values[rid]))
        metrics = original_scale_metrics(y_true, y_pred, unit=target_unit)
        rows.append(
            {
                "revision_id": revision_id,
                "reason": reason,
                "status": "ok",
                "exclude_row_ids": exclude,
                "n_train": len(revised_train),
                "mae": metrics.get("mae"),
                "rmse": metrics.get("rmse"),
                "mean_prediction_delta_vs_baseline": _finite_or_none(float(np.mean(deltas))) if deltas else None,
                "max_abs_prediction_delta_vs_baseline": _finite_or_none(float(np.max(np.abs(deltas)))) if deltas else None,
                "n_compared": len(deltas),
            }
        )

    block = {
        "executed": True,
        "name": JUSTIFIED_REVISION_SENSITIVITY,
        "n_revisions": len(rows),
        "revisions": rows,
        "issues": issues,
        "reserved_not_silently_dropped": True,
    }
    return block, n_fit, n_predict


def _numeric_feature_keys(records: Sequence[Mapping[str, Any]]) -> List[str]:
    keys = []
    if not records:
        return keys
    skip = {"row_id"}
    for key, value in records[0].items():
        if key in skip:
            continue
        if _as_float(value) is not None:
            keys.append(str(key))
    return keys


def _perturb_record(
    record: Mapping[str, Any],
    numeric_keys: Sequence[str],
    rng: np.random.RandomState,
    relative_scale: float,
) -> Dict[str, Any]:
    out = dict(record)
    for key in numeric_keys:
        current = _as_float(out.get(key))
        if current is None:
            continue
        scale = relative_scale * (abs(current) if abs(current) > 0 else 1.0)
        out[key] = float(current + rng.normal(0.0, scale))
    return out


def _not_executed(name: str, reason: str) -> Dict[str, Any]:
    return {
        "executed": False,
        "name": name,
        "reason": reason,
    }


def _stability_limitations(
    mode: str,
    pipeline_block: Mapping[str, Any],
    folds: Sequence[Mapping[str, Any]],
) -> List[str]:
    notes = [
        "Pipeline bootstrap and fixed-model sensitivity are different analyses; neither is a post-selection CI.",
        "Stability figures are not NBR fundamentação/precisão grades.",
    ]
    if mode == "fast":
        notes.append("Fast mode used a reduced replicate budget; executed_analyses lists what actually ran.")
    n_ok = pipeline_block.get("n_replicates_ok") if pipeline_block.get("executed") else 0
    if pipeline_block.get("executed") and int(n_ok or 0) < 5:
        notes.append("Few pipeline-bootstrap replicates: dispersion is indicative, not a stable distributional estimate.")
    if len(folds) == 1:
        notes.append("Stability used the primary external fold; it does not replace multi-fold generalization.")
    return notes


def _empty_stability(*, seed, mode, budget, issues, executed_analyses, skipped, elapsed, n_fit_calls, n_predict_calls):
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": STABILITY_RESULT_KIND,
        "status": "error",
        "mode": mode,
        "budget": dict(budget),
        "seed": int(seed),
        PIPELINE_BOOTSTRAP: _not_executed(PIPELINE_BOOTSTRAP, "No fitted folds."),
        FIXED_MODEL_SENSITIVITY: _not_executed(FIXED_MODEL_SENSITIVITY, "No fitted folds."),
        VARIABLE_SELECTION_FREQUENCY: _not_executed(VARIABLE_SELECTION_FREQUENCY, "No fitted folds."),
        CANDIDATE_DISPERSION: _not_executed(CANDIDATE_DISPERSION, "No fitted folds."),
        JUSTIFIED_REVISION_SENSITIVITY: _not_executed(JUSTIFIED_REVISION_SENSITIVITY, "No fitted folds."),
        "executed_analyses": executed_analyses,
        "skipped_analyses": skipped,
        "names_are_distinct": True,
        "pipeline_bootstrap_is_not_fixed_model_sensitivity": True,
        "not_normative_grade": True,
        "not_post_selection_confidence_interval": True,
        "usable_for_model_selection": False,
        "cost": {
            "elapsed_seconds": round(elapsed, 6),
            "n_fit_select_calls": n_fit_calls,
            "n_predict_calls": n_predict_calls,
        },
        "limitations": ["Stability was not executed because no fitted procedure was available."],
        "issues": list(issues),
        "underlying_data": {},
    }


__all__ = [
    "STABILITY_RESULT_KIND",
    "PIPELINE_BOOTSTRAP",
    "FIXED_MODEL_SENSITIVITY",
    "VARIABLE_SELECTION_FREQUENCY",
    "CANDIDATE_DISPERSION",
    "JUSTIFIED_REVISION_SENSITIVITY",
    "analyze_stability",
]
