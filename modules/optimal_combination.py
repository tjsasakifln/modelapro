"""C05: transparent model search, ranking, and measurable efficiency.

``search_models`` is the MP/1 entry point. ``OptimalCombinationFinder.find_best_model``
is a compatibility adapter over the same search — it does not run a second algorithm.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .config_manager import config
from .logging_manager import logger
from .model_builder import ModelBuilder
from .results import ModelResult, OptimalCombinationResult
from .search_space import (
    GROUP_OPTION,
    LINEAR_OPTION,
    SCHEMA_VERSION,
    Y_IDENTITY,
    SearchUnit,
    canonical_transform_name,
    count_exhaustive_candidates,
    derived_max_vars,
    domain_valid_include_options,
    feature_column_name,
    iter_search_candidates,
    parse_feature_name,
    possible_count_for_units,
    resolve_authorized_base_variables,
    search_units_from_prepared,
    y_transformations_from_policy,
)
from .transformations import Transformer


ProgressCallback = Callable[[Mapping[str, Any]], None]
CancelRequested = Callable[[], bool]

MAX_EXHAUSTIVE_CANDIDATES = 200_000
DEFAULT_EVALUATION_BUDGET = 512
HISTORY_SAMPLE_LIMIT = 5000
DEFAULT_ALTERNATIVES = 5
CODE_VERSION = "C05/MP1"

_SEARCH_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_SEARCH_CACHE_LIMIT = 32


def clear_search_cache() -> None:
    """Drop the in-process search cache (tests and C14 reuse isolation)."""
    _SEARCH_CACHE.clear()


def evaluate_search_candidate(
    prepared_dataset: Mapping[str, Any],
    candidate_spec: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    subject_design: Optional[Mapping[str, Any]] = None,
    column_store: Optional["_ColumnStore"] = None,
    hooks: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Fit and score one CandidateSpec with the same path ``search_models`` uses."""
    evaluation_policy = dict(request_spec.get("evaluation_policy") or {})
    hooks = dict(hooks or _resolve_hooks(request_spec))
    if column_store is None:
        column_store = _ColumnStore(_frame_for_columns(prepared_dataset))
    record = _fit_and_score(
        prepared_dataset,
        candidate_spec,
        request_spec,
        subject_design,
        column_store,
        hooks,
        evaluation_policy,
        retain_legacy=bool((request_spec.get("search_policy") or {}).get("retain_legacy_model")),
    )
    record["_rank_tuple"] = ranking_tuple(
        record, _objective_descriptor(request_spec.get("search_policy") or {}, evaluation_policy)
    )
    return record


def search_models(
    prepared_dataset: Mapping[str, Any],
    subject_design: Optional[Mapping[str, Any]],
    request_spec: Mapping[str, Any],
    progress_callback: Optional[ProgressCallback] = None,
    cancel_requested: Optional[CancelRequested] = None,
) -> Dict[str, Any]:
    """Search candidate models and return ``{winner, alternatives, search_audit, issues}``.

    Callbacks are synchronous and light. ``cancel_requested()`` returns bool.
    C07 ``evaluate_procedure`` is never invoked here (no validation recursion).
    """
    _configure_local_threads((request_spec.get("search_policy") or {}).get("n_jobs", 1))
    t0 = time.perf_counter()
    rss0 = _rss_bytes()
    issues: List[Dict[str, Any]] = []
    search_policy = dict(request_spec.get("search_policy") or {})
    evaluation_policy = dict(request_spec.get("evaluation_policy") or {})

    cache_digest, cache_components = build_search_cache_key(
        prepared_dataset, subject_design, request_spec
    )
    use_cache = bool(search_policy.get("use_cache", True))
    if use_cache and cache_digest in _SEARCH_CACHE:
        cached = _SEARCH_CACHE[cache_digest]
        _SEARCH_CACHE.move_to_end(cache_digest)
        hit = _deepcopy_search_result(cached)
        hit["search_audit"] = dict(hit.get("search_audit") or {})
        hit["search_audit"]["cache_hit"] = True
        _emit_progress(
            progress_callback,
            {"progress": 1.0, "evaluated": hit["search_audit"].get("evaluated"), "cache_hit": True},
        )
        return hit

    authorized, auth_issues = resolve_authorized_base_variables(
        request_spec,
        _available_predictor_names(prepared_dataset, request_spec),
        target_col=request_spec.get("target_col"),
    )
    issues.extend(auth_issues)
    if any(i.get("code") == "no_authorized_variables" and i.get("severity") == "error" for i in auth_issues):
        audit = _empty_audit(
            objective=_objective_descriptor(search_policy, evaluation_policy),
            cache_components=cache_components,
            cancelled=False,
        )
        audit["coverage"]["exact_optimum_guaranteed"] = False
        return _search_result(None, [], audit, issues, t0, rss0)

    subject_raw = None
    if subject_design:
        subject_raw = subject_design.get("raw_values") or subject_design.get("subject_raw")

    units, unit_issues = search_units_from_prepared(
        prepared_dataset, authorized, subject_raw=subject_raw
    )
    issues.extend(unit_issues)

    if subject_raw is not None:
        missing_bases = [
            u.base_variable
            for u in units
            if u.base_variable not in subject_raw
        ]
        if missing_bases:
            issues.append(
                _issue(
                    "subject_missing_base",
                    "warning",
                    "Base variables without a subject value were excluded so ranking "
                    "criteria that depend on the subject stay symmetric.",
                    affected_ids=missing_bases,
                )
            )
            units = [u for u in units if u.base_variable in subject_raw]

    if not units:
        issues.append(
            _issue(
                "empty_search_space",
                "error",
                "No search units remain after authorization, grouping, and domain filters.",
            )
        )
        audit = _empty_audit(
            objective=_objective_descriptor(search_policy, evaluation_policy),
            cache_components=cache_components,
            cancelled=False,
        )
        return _search_result(None, [], audit, issues, t0, rss0)

    n_rows = _n_rows(prepared_dataset)
    max_vars = derived_max_vars(n_rows, len(units), search_policy, evaluation_policy)
    possible = possible_count_for_units(units, max_vars)
    y_list = y_transformations_from_policy(search_policy)
    if len(y_list) > 1:
        possible *= len(y_list)

    budget = search_policy.get("budget", DEFAULT_EVALUATION_BUDGET)
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        budget = DEFAULT_EVALUATION_BUDGET
    budget = max(0, budget)
    threshold = search_policy.get("exact_count_threshold", MAX_EXHAUSTIVE_CANDIDATES)
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        threshold = MAX_EXHAUSTIVE_CANDIDATES

    requested_mode = (search_policy.get("mode") or "auto").lower()
    mode, mode_issue = _resolve_mode(requested_mode, possible, budget, threshold)
    if mode_issue:
        issues.append(mode_issue)

    seed = int(search_policy.get("seed") or 0)
    intercept = bool(search_policy.get("intercept", True))
    enumerator_budget = budget if mode == "approximate" else possible
    candidate_iter = iter_search_candidates(
        units,
        max_vars=max_vars,
        mode=mode,
        budget=max(enumerator_budget, 1),
        seed=seed,
        y_transformations=y_list,
        intercept=intercept,
    )

    hooks = _resolve_hooks(request_spec)
    column_store = _ColumnStore(_frame_for_columns(prepared_dataset))
    objective = _objective_descriptor(search_policy, evaluation_policy)
    extra_objective = evaluation_policy.get("extra_objective")
    shortlist_size = evaluation_policy.get("shortlist_size")
    try:
        shortlist_size = int(shortlist_size) if shortlist_size is not None else None
    except (TypeError, ValueError):
        shortlist_size = None
    using_shortlist = bool(shortlist_size and callable(extra_objective))

    n_alternatives = int(search_policy.get("max_alternatives") or DEFAULT_ALTERNATIVES)
    retain_limit = max(n_alternatives + 1, 8)
    retain_legacy = bool(search_policy.get("retain_legacy_model"))

    generated = 0
    evaluated = 0
    rejected = 0
    rejection_reasons: Dict[str, int] = {}
    cancelled = False
    compact_history: List[Dict[str, Any]] = []
    scored: List[Dict[str, Any]] = []
    last_progress = 0.0
    denom = float(budget) if mode == "approximate" or budget < possible else float(max(possible, 1))
    best_so_far_id = None
    best_so_far_key = None

    def consider_progress():
        nonlocal last_progress
        raw = evaluated / denom if denom else None
        if raw is None:
            payload_progress = None
        else:
            payload_progress = min(1.0, max(last_progress, max(0.0, raw)))
            last_progress = payload_progress
        _emit_progress(
            progress_callback,
            {
                "progress": payload_progress,
                "generated": generated,
                "evaluated": evaluated,
                "rejected": rejected,
                "cancelled": cancelled,
                "best_candidate_id": best_so_far_id,
            },
        )

    consider_progress()

    for spec in candidate_iter:
        if _cancelled(cancel_requested):
            cancelled = True
            break
        if budget and evaluated >= budget:
            break
        generated += 1
        record = _fit_and_score(
            prepared_dataset,
            spec,
            request_spec,
            subject_design,
            column_store,
            hooks,
            evaluation_policy,
            retain_legacy=retain_legacy,
        )
        evaluated += 1
        if not record["admissibility"]["numeric_technical"]:
            rejected += 1
            reason = record.get("discard_reason") or "not_admissible"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        record["_rank_tuple"] = ranking_tuple(record, objective)
        scored.append(record)
        compact_history.append(_compact_history_entry(record))
        if best_so_far_key is None or _is_better(record["_rank_tuple"], best_so_far_key):
            best_so_far_key = record["_rank_tuple"]
            best_so_far_id = record["candidate_id"]
        _trim_retained_models(scored, retain_limit)
        if evaluated % 5 == 0 or evaluated == 1:
            consider_progress()
        if budget and evaluated >= budget:
            break

    if _cancelled(cancel_requested):
        cancelled = True

    full_objective_on = "all_evaluated"
    if using_shortlist and scored:
        cheap_sorted = _sorted_records(scored, objective)
        shortlist = cheap_sorted[: max(1, shortlist_size)]
        shortlist_ids = {r["candidate_id"] for r in shortlist}
        for rec in scored:
            if rec["candidate_id"] not in shortlist_ids:
                rec["metrics"]["full_objective"] = False
                rec["criteria_omitted"] = list(
                    dict.fromkeys(list(rec.get("criteria_omitted") or []) + ["extra_objective"])
                )
                continue
            try:
                extra = extra_objective(rec) or {}
            except Exception as exc:
                rec["issues"].append(
                    _issue("extra_objective_failed", "warning", str(exc), affected_ids=[rec["candidate_id"]])
                )
                extra = {}
            rec["metrics"].update({k: v for k, v in extra.items() if v is not None})
            rec["metrics"]["full_objective"] = True
            rec["_rank_tuple"] = ranking_tuple(rec, objective)
        full_objective_on = "shortlist"
        issues.append(
            _issue(
                "full_objective_shortlist_only",
                "info",
                "The complete ranking objective was evaluated only on the shortlist; "
                "other generated candidates were scored with the cheap objective only.",
                evidence={"shortlist_size": shortlist_size, "shortlist_ids": sorted(shortlist_ids)},
            )
        )

    enumeration_exhaustive = (
        mode == "exact"
        and not cancelled
        and generated == possible
        and (budget <= 0 or evaluated <= budget)
        and evaluated == possible
    )
    ranking_full = full_objective_on == "all_evaluated" and not cancelled and enumeration_exhaustive
    exact_optimum = bool(enumeration_exhaustive and ranking_full and mode == "exact")

    if cancelled:
        ranking_objective = "partial"
        issues.append(
            _issue(
                "search_cancelled",
                "warning",
                "Search stopped because cancel_requested() returned true before global completion.",
                evidence={"generated": generated, "evaluated": evaluated, "possible": possible},
            )
        )
    elif full_objective_on == "shortlist":
        ranking_objective = "shortlist_only"
    elif mode == "approximate" or generated < possible or evaluated < possible:
        ranking_objective = "partial"
    else:
        ranking_objective = "full"

    ordered = _sorted_records(scored, objective)
    winner_rec = None
    alternatives: List[Dict[str, Any]] = []
    for rec in ordered:
        label = rec["admissibility"].get("label")
        if winner_rec is None and label == "admissible":
            winner_rec = rec
            continue
        if winner_rec is None and label != "admissible":
            # Keep looking for an admissible winner; exploratories go to alternatives.
            if len(alternatives) < n_alternatives:
                rec = dict(rec)
                rec["discard_reason"] = rec.get("discard_reason") or "exploratory_not_admissible"
                alternatives.append(rec)
            continue
        if len(alternatives) < n_alternatives:
            if rec["admissibility"].get("label") != "admissible":
                rec = dict(rec)
                rec["discard_reason"] = rec.get("discard_reason") or "exploratory_not_admissible"
            else:
                rec = dict(rec)
                rec["discard_reason"] = rec.get("discard_reason") or "dominated_by_winner"
            alternatives.append(rec)

    if winner_rec is None and ordered:
        issues.append(
            _issue(
                "no_admissible_winner",
                "warning",
                "No candidate met numeric/technical admissibility and required framing. "
                "Exploratory models may be listed in alternatives; none is implicitly admissible.",
            )
        )

    if len(compact_history) > HISTORY_SAMPLE_LIMIT:
        step = len(compact_history) / HISTORY_SAMPLE_LIMIT
        sampled = [compact_history[int(i * step)] for i in range(HISTORY_SAMPLE_LIMIT)]
        omitted = len(compact_history) - len(sampled)
        issues.append(
            _issue(
                "history_sampled",
                "info",
                "History is sampled to bound result size; counters still reflect every candidate.",
                evidence={"kept": len(sampled), "total": len(compact_history), "omitted": omitted},
            )
        )
        history_out = sampled
    else:
        history_out = compact_history

    last_progress = 1.0 if not cancelled else last_progress
    consider_progress()
    if not cancelled:
        _emit_progress(
            progress_callback,
            {
                "progress": 1.0,
                "generated": generated,
                "evaluated": evaluated,
                "rejected": rejected,
                "cancelled": False,
                "best_candidate_id": winner_rec["candidate_id"] if winner_rec else best_so_far_id,
            },
        )

    audit = {
        "possible": possible,
        "generated": generated,
        "evaluated": evaluated,
        "rejected": rejected,
        "rejection_reasons": rejection_reasons,
        "coverage": {
            "enumeration": "exhaustive" if enumeration_exhaustive else "partial",
            "ranking_objective": ranking_objective,
            "exact_optimum_guaranteed": exact_optimum,
            "pruning_proof": None,
        },
        "budget": {"max_evaluations": budget, "used": evaluated},
        "objective": {
            **objective,
            "full_objective_evaluated_on": full_objective_on if not cancelled else "partial",
        },
        "mode": mode,
        "requested_mode": requested_mode,
        "cancelled": cancelled,
        "progress": None if cancelled and last_progress == 0 else (1.0 if not cancelled else last_progress),
        "cache_key_components": cache_components,
        "cache_hit": False,
        "best_so_far_candidate_id": winner_rec["candidate_id"] if winner_rec else best_so_far_id,
        "max_vars": max_vars,
        "n_units": len(units),
        "unit_ids": [u.unit_id for u in units],
        "history": history_out,
        "history_complete": len(compact_history) <= HISTORY_SAMPLE_LIMIT,
        "history_total": len(compact_history),
        "seed": seed,
        "code_version": CODE_VERSION,
        "hooks": hooks.get("labeled"),
    }
    if not exact_optimum:
        audit["coverage"]["optimum_disclaimer"] = (
            "Partial coverage or an unproven prune is not a global optimum. "
            "exact_optimum_guaranteed is true only for exact enumeration of the "
            "space with the full ranking objective on every candidate."
        )

    include_legacy = retain_legacy
    winner_out = _public_record(winner_rec, include_legacy) if winner_rec else None
    alt_out = [_public_record(a, include_legacy) for a in alternatives]
    result = _search_result(winner_out, alt_out, audit, issues, t0, rss0)
    if use_cache and not cancelled:
        _cache_put(cache_digest, result)
    return result


def ranking_tuple(
    record: Mapping[str, Any],
    objective: Optional[Mapping[str, Any]] = None,
) -> Tuple:
    """Documented ranking key. Higher is better.

    Order:
    1. numeric/technical admissibility
    2. required framing
    3. original-scale error (missing is worst when the objective requires it;
       never compare R² across transformed vs original target scales)
    4. optional precision amplitude, if required by policy and present
    5. optional stability, if required and present
    6. lower complexity (feature count)
    Tie-break is applied separately: ``candidate_id`` lexicographic ascending.
    Automatic sample-row removal is not a ranking criterion.
    Grau de fundamentação is framing, not preference.
    """
    objective = objective or _objective_descriptor({}, {})
    adm = record.get("admissibility") or {}
    metrics = record.get("metrics") or {}
    numeric = 1 if adm.get("numeric_technical") else 0
    framing = 1 if adm.get("framing") else 0
    required = list(objective.get("required_criteria") or ["original_rmse"])
    rmse = metrics.get("original_rmse")
    if "original_rmse" in required:
        rmse_key = -float(rmse) if _finite_number(rmse) else float("-inf")
    else:
        rmse_key = -float(rmse) if _finite_number(rmse) else 0.0
    amp_key = 0.0
    if "precision_amplitude_pct" in required:
        amp = metrics.get("precision_amplitude_pct")
        amp_key = -float(amp) if _finite_number(amp) else float("-inf")
    elif _finite_number(metrics.get("precision_amplitude_pct")):
        amp_key = -float(metrics["precision_amplitude_pct"])
    stab_key = 0.0
    if "stability" in required:
        stab = metrics.get("stability")
        stab_key = float(stab) if _finite_number(stab) else float("-inf")
    elif _finite_number(metrics.get("stability")):
        stab_key = float(metrics["stability"])
    complexity = metrics.get("complexity")
    if complexity is None:
        spec = record.get("candidate_spec") or {}
        complexity = len(spec.get("features") or [])
    complexity_key = -int(complexity)
    extra_key = 0.0
    if _finite_number(metrics.get("extra_objective_score")):
        extra_key = float(metrics["extra_objective_score"])
    return (
        numeric,
        framing,
        rmse_key,
        extra_key,
        amp_key,
        stab_key,
        complexity_key,
    )


def classify_admissibility(
    record: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
) -> Dict[str, Any]:
    """Separate numeric/technical admissibility, required framing, and label.

    A higher fundamentação grade does not waive required diagnostics/precision.
    Missing metrics are omitted, never fabricated. Insufficient models are
    exploratory, never implicitly admissible.
    """
    reasons: List[str] = []
    status_fit = record.get("status")
    metrics = record.get("metrics") or {}
    numeric = status_fit == "fitted" and _finite_number(metrics.get("original_rmse"))
    if status_fit != "fitted":
        reasons.append("fit_not_successful")
        numeric = False
    coeffs = record.get("coefficients") or {}
    if coeffs and not all(_finite_number(v) for v in coeffs.values() if v is not None):
        numeric = False
        reasons.append("non_finite_coefficients")
    if metrics.get("original_rmse") is None and status_fit == "fitted":
        # Fitted but original-scale error could not be computed (e.g. missing inverse).
        numeric = False
        reasons.append("original_scale_error_unavailable")

    framing_ok = numeric
    min_grade = evaluation_policy.get("min_fundamentacao_grade")
    grau = metrics.get("grau_fundamentacao")
    if min_grade is not None:
        try:
            if grau is None or int(grau) < int(min_grade):
                framing_ok = False
                reasons.append("min_fundamentacao_grade_not_met")
        except (TypeError, ValueError):
            framing_ok = False
            reasons.append("min_fundamentacao_grade_not_met")
    required_diagnostics = evaluation_policy.get("required_diagnostics") or []
    diagnostics = record.get("diagnostics") or {}
    for name in required_diagnostics:
        if diagnostics.get(name) is None and metrics.get(name) is None:
            framing_ok = False
            reasons.append(f"missing_required_diagnostic:{name}")
    if evaluation_policy.get("require_precision") and metrics.get("precision_amplitude_pct") is None:
        framing_ok = False
        reasons.append("missing_required_precision")
    # Higher grade must not skip the checks above; they already ran.

    label = "admissible" if numeric and framing_ok else "exploratory"
    eligibility_status = "eligible" if label == "admissible" else "exploratory"
    if status_fit == "error":
        eligibility_status = "error"
    elif status_fit == "rejected":
        eligibility_status = "unsupported"
    return {
        "numeric_technical": bool(numeric),
        "framing": bool(framing_ok),
        "label": label,
        "reasons": reasons,
        "eligibility_status": eligibility_status,
    }


def build_search_cache_key(
    prepared_dataset: Mapping[str, Any],
    subject_design: Optional[Mapping[str, Any]],
    request_spec: Mapping[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Cache identity: base, sample/policies, schema, transforms, objective, versions, subject."""
    search_policy = dict(request_spec.get("search_policy") or {})
    evaluation_policy = dict(request_spec.get("evaluation_policy") or {})
    search_policy.pop("peer_hooks", None)
    evaluation_policy.pop("extra_objective", None)
    search_policy.pop("progress_callback", None)
    components = {
        "dataset_sha256": prepared_dataset.get("dataset_sha256"),
        "sample_fingerprint": _sample_fingerprint(prepared_dataset),
        "row_ids": list(prepared_dataset.get("row_ids") or []),
        "feature_schema": prepared_dataset.get("feature_schema"),
        "missing_policy": request_spec.get("missing_policy"),
        "outlier_policy": request_spec.get("outlier_policy"),
        "search_policy": search_policy,
        "evaluation_policy": evaluation_policy,
        "target_col": request_spec.get("target_col"),
        "candidate_cols": request_spec.get("candidate_cols") if "candidate_cols" in request_spec else None,
        "roles": request_spec.get("roles"),
        "code_version": CODE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "y_transformations": y_transformations_from_policy(search_policy),
        "subject": None,
    }
    if subject_design is not None:
        components["subject"] = subject_design.get("raw_values") or subject_design.get("subject_raw")
    blob = json.dumps(components, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return digest, components


class OptimalCombinationFinder:
    """Legacy finder. ``find_best_model`` adapts DataFrame calls onto ``search_models``."""

    MAX_EXHAUSTIVE_CANDIDATES = MAX_EXHAUSTIVE_CANDIDATES
    FALLBACK_TOP_N = 15
    FALLBACK_MAX_VARS = 5
    HISTORY_SAMPLE_LIMIT = HISTORY_SAMPLE_LIMIT
    NON_LINEAR_TRANSFORMATIONS = [
        "ln",
        "sqrt",
        "inverse",
        "sqr",
        "inv_sqr",
        "inv_sqrt",
    ]

    def __init__(self):
        self.model_builder = ModelBuilder()
        self.transformer = Transformer()

    @staticmethod
    def _score_key(result: ModelResult) -> Tuple:
        """Deprecated adapter helper. Ranking is ``ranking_tuple`` in search_models."""
        grau = None
        if result.validation_result is not None:
            grau = result.validation_result.grau_fundamentacao
        grau_key = grau if grau is not None else -1
        r2_adj = result.model_metrics.r2_adjusted if result.model_metrics else -float("inf")
        return (grau_key, r2_adj)

    @staticmethod
    def _base_name(col: str) -> str:
        _, base = parse_feature_name(col)
        return base

    def _build_variable_options(
        self,
        df: pd.DataFrame,
        X_cols: List[str],
        avaliando_raw: Optional[Dict[str, float]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        transformed_df = df.copy()
        vars_options: Dict[str, List[str]] = {}
        for col in X_cols:
            subject_value = None
            if avaliando_raw is not None and col in avaliando_raw:
                subject_value = avaliando_raw[col]
            options, dropped = domain_valid_include_options(
                df[col], subject_value=subject_value
            )
            col_names: List[str] = []
            for opt in options:
                if opt == LINEAR_OPTION:
                    col_names.append(col)
                else:
                    name = feature_column_name(col, opt)
                    series, ok = Transformer.apply_transformation(df[col], opt)
                    if not ok:
                        continue
                    transformed_df[name] = series
                    col_names.append(name)
            if dropped:
                logger.warning(
                    f"Variável '{col}': transformação(ões) {list(dropped)} válida(s) "
                    f"para a coluna de treino mas indefinida(s) para o valor do avaliando "
                    f"({avaliando_raw.get(col)!r}); excluída(s) do espaço de busca para manter "
                    f"o item 4 (extrapolação) simétrico entre candidatos."
                )
            vars_options[col] = col_names
        return transformed_df, vars_options

    @staticmethod
    def _count_exhaustive_candidates(option_counts: List[int], max_vars: int) -> int:
        return count_exhaustive_candidates(option_counts, max_vars)

    def _iter_candidates_exhaustive(self, vars_options: Dict[str, List[str]], max_vars: int):
        units = []
        option_map = {}
        for base, cols in vars_options.items():
            transforms = []
            for col in cols:
                trans, _ = parse_feature_name(col)
                transforms.append(trans)
            unit = SearchUnit(
                unit_id=base,
                kind="quantitative",
                base_variable=base,
                columns=(base,),
                options=tuple(transforms),
            )
            units.append(unit)
            option_map[base] = {parse_feature_name(c)[0]: c for c in cols}
        for spec in iter_search_candidates(units, max_vars, "exact", budget=10**18, seed=0):
            names = []
            for base, trans in spec["x_transformations"].items():
                names.append(option_map[base].get(trans, feature_column_name(base, trans)))
            yield names

    def _iter_candidates_fallback(
        self,
        transformed_df: pd.DataFrame,
        y: pd.Series,
        vars_options: Dict[str, List[str]],
        max_vars: int,
    ):
        """Legacy correlation prune. Not used by search_models (replaced by diverse approximate)."""
        import itertools as _it

        flat_cols = [c for opts in vars_options.values() for c in opts]
        correlations = []
        for col in flat_cols:
            try:
                corr = transformed_df[col].corr(y)
                if pd.notna(corr):
                    correlations.append((col, abs(corr)))
            except Exception:
                pass
        correlations.sort(key=lambda x: x[1], reverse=True)
        top_vars = [x[0] for x in correlations[: self.FALLBACK_TOP_N]]
        max_vars_in_model = min(len(top_vars), self.FALLBACK_MAX_VARS, max_vars)
        for k in range(1, max_vars_in_model + 1):
            for combo in _it.combinations(top_vars, k):
                base_names = set()
                conflict = False
                for var in combo:
                    base = self._base_name(var)
                    if base in base_names:
                        conflict = True
                        break
                    base_names.add(base)
                if conflict:
                    continue
                yield list(combo)

    def find_best_model(
        self,
        df: pd.DataFrame,
        target_col: str,
        degree: int = 1,
        avaliando_raw: Optional[Dict[str, float]] = None,
        grau_item1: int = 1,
        grau_item3: int = 1,
        candidate_cols: Optional[List[str]] = None,
    ) -> OptimalCombinationResult:
        """Adapter: map the legacy DataFrame call onto ``search_models`` and back."""
        try:
            prepared, request_spec, subject = self._legacy_to_mp1(
                df,
                target_col,
                degree=degree,
                avaliando_raw=avaliando_raw,
                grau_item1=grau_item1,
                grau_item3=grau_item3,
                candidate_cols=candidate_cols,
            )
            result = search_models(prepared, subject, request_spec)
            return self._to_legacy_result(result, degree=degree)
        except Exception as e:
            logger.error(f"Error finding optimal combination: {str(e)}")
            return OptimalCombinationResult(
                success=False, message=f"Error: {str(e)}", error=str(e)
            )

    def _legacy_to_mp1(
        self,
        df: pd.DataFrame,
        target_col: str,
        degree: int,
        avaliando_raw: Optional[Dict[str, float]],
        grau_item1: int,
        grau_item3: int,
        candidate_cols: Optional[List[str]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
        if target_col not in df.columns:
            raise ValueError(f"target_col {target_col!r} not in DataFrame")
        X = df.drop(columns=[target_col])
        y = df[target_col]
        columns = {}
        for c in X.columns:
            columns[c] = {
                "original_name": c,
                "role": "predictor",
                "kind": "quantitative",
                "unit": None,
                "group_id": None,
                "categories": None,
                "reference_category": None,
            }
        prepared = {
            "schema_version": SCHEMA_VERSION,
            "X": X,
            "y": y,
            "row_ids": [str(i) for i in df.index],
            "feature_schema": {
                "version": 1,
                "columns": columns,
                "groups": {},
                "target": {"column": target_col, "unit": None},
            },
            "encoder_state": {},
            "sample_ledger": {},
            "issues": [],
            "dataset_sha256": None,
            "base_frame": X.copy(),
            "_legacy_df": df,
        }
        request_spec: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "target_col": target_col,
            "roles": {c: "predictor" for c in X.columns},
            "units": {},
            "search_policy": {
                "mode": "auto",
                "budget": DEFAULT_EVALUATION_BUDGET,
                "exact_count_threshold": self.MAX_EXHAUSTIVE_CANDIDATES,
                "objective": "original_scale_error",
                "seed": 0,
                "retain_legacy_model": True,
                "max_alternatives": DEFAULT_ALTERNATIVES,
                "n_jobs": 1,
            },
            "evaluation_policy": {
                "sample_size_rule": "nbr_item2_grau1",
                "min_fundamentacao_grade": degree if avaliando_raw else None,
                "remove_outliers": False,
                "outlier_action": "report_only",
                "grau_item1": grau_item1,
                "grau_item3": grau_item3,
                "seed": 0,
            },
            "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
            "outlier_policy": {"action": "report_only"},
        }
        if candidate_cols is None:
            request_spec["candidate_cols"] = None
        else:
            request_spec["candidate_cols"] = list(candidate_cols)
        subject = None
        if avaliando_raw:
            subject = {
                "X": None,
                "raw_values": dict(avaliando_raw),
                "issues": [],
                "supported": True,
            }
        return prepared, request_spec, subject

    def _to_legacy_result(
        self, search: Mapping[str, Any], degree: int = 1
    ) -> OptimalCombinationResult:
        issues = list(search.get("issues") or [])
        error_issues = [i for i in issues if i.get("severity") == "error"]
        audit = search.get("search_audit") or {}
        winner = search.get("winner")
        if error_issues and winner is None:
            code = error_issues[0].get("code") or "search_error"
            return OptimalCombinationResult(
                success=False,
                message=error_issues[0].get("message") or "",
                error=code,
                combinations_tested=int(audit.get("evaluated") or 0),
                exhaustive=False,
            )
        best_model = None
        if winner is not None:
            best_model = winner.get("_legacy_model_result")
        if best_model is None:
            for alt in search.get("alternatives") or []:
                if alt.get("_legacy_model_result") is not None:
                    best_model = alt["_legacy_model_result"]
                    break
        grau = None
        if best_model is not None and best_model.validation_result is not None:
            grau = best_model.validation_result.grau_fundamentacao
        target_achieved = grau is not None and grau >= degree
        message_parts = [i.get("message") for i in issues if i.get("message")]
        if audit.get("coverage", {}).get("enumeration") != "exhaustive":
            possible = audit.get("possible")
            budget = (audit.get("budget") or {}).get("max_evaluations")
            message_parts.append(
                f"Busca exaustiva exigiria {possible} combinações, acima do "
                f"limite de segurança combinatória / orçamento de {budget}. "
                f"Aplicando busca aproximada (diversidade de variáveis-base/grupos) "
                f"como fallback documentado. A garantia de ótimo global sobre TODO "
                f"o espaço de busca NÃO se aplica a este resultado "
                f"(OptimalCombinationResult.exhaustive=False)."
            )
        history = []
        for entry in audit.get("history") or []:
            history.append(
                {
                    "variables": list(entry.get("variables") or []),
                    "r2_adj": entry.get("r2_adj"),
                    "grau_fundamentacao": entry.get("grau_fundamentacao"),
                    "valid": entry.get("valid", False),
                }
            )
        profile = (search.get("search_audit") or {}).get("profile") or {}
        return OptimalCombinationResult(
            success=True,
            message=" ".join(p for p in message_parts if p),
            best_model=best_model,
            combinations_tested=int(audit.get("evaluated") or 0),
            time_elapsed=float(profile.get("elapsed_s") or 0.0),
            history=history,
            target_achieved=target_achieved,
            best_grau_reached=grau,
            exhaustive=bool(audit.get("coverage", {}).get("exact_optimum_guaranteed")),
        )


def _configure_local_threads(n_jobs: Any) -> int:
    try:
        n = max(1, int(n_jobs or 1))
    except (TypeError, ValueError):
        n = 1
    n = min(n, 1)  # local single-user default: never oversubscribe BLAS + workers
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ.setdefault(var, str(n))
    return n


def _rss_bytes() -> Optional[int]:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    try:
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return rss * 1024
    except Exception:
        return None


def _emit_progress(cb: Optional[ProgressCallback], payload: Mapping[str, Any]) -> None:
    if cb is None:
        return
    try:
        cb(payload)
    except Exception:
        logger.warning("progress_callback raised; search continues", exc_info=True)


def _cancelled(fn: Optional[CancelRequested]) -> bool:
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        logger.warning("cancel_requested raised; treating as not cancelled", exc_info=True)
        return False


def _issue(
    code: str,
    severity: str,
    message: str,
    affected_ids: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": "C05",
        "message": message,
        "affected_ids": list(affected_ids or []),
        "evidence": dict(evidence or {}),
    }


def _empty_audit(objective: Mapping[str, Any], cache_components: Mapping[str, Any], cancelled: bool) -> Dict[str, Any]:
    return {
        "possible": 0,
        "generated": 0,
        "evaluated": 0,
        "rejected": 0,
        "rejection_reasons": {},
        "coverage": {
            "enumeration": "partial",
            "ranking_objective": "partial",
            "exact_optimum_guaranteed": False,
            "pruning_proof": None,
        },
        "budget": {"max_evaluations": 0, "used": 0},
        "objective": dict(objective),
        "mode": "exact",
        "cancelled": cancelled,
        "progress": None,
        "cache_key_components": dict(cache_components),
        "cache_hit": False,
        "history": [],
        "history_complete": True,
        "history_total": 0,
        "code_version": CODE_VERSION,
    }


def _search_result(
    winner,
    alternatives,
    audit: Dict[str, Any],
    issues: List[Dict[str, Any]],
    t0: float,
    rss0: Optional[int],
) -> Dict[str, Any]:
    rss1 = _rss_bytes()
    audit = dict(audit)
    audit["profile"] = {
        "elapsed_s": time.perf_counter() - t0,
        "rss_bytes_before": rss0,
        "rss_bytes_after": rss1,
        "host": "this_process_only",
        "disclaimer": "Measurements for this local run only; not a speed claim for other machines.",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "winner": winner,
        "alternatives": list(alternatives or []),
        "search_audit": audit,
        "issues": list(issues or []),
    }


def _deepcopy_search_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": result.get("schema_version"),
        "winner": dict(result["winner"]) if result.get("winner") else None,
        "alternatives": [dict(a) for a in result.get("alternatives") or []],
        "search_audit": dict(result.get("search_audit") or {}),
        "issues": list(result.get("issues") or []),
    }


def _cache_put(digest: str, result: Dict[str, Any]) -> None:
    _SEARCH_CACHE[digest] = _deepcopy_search_result(result)
    _SEARCH_CACHE.move_to_end(digest)
    while len(_SEARCH_CACHE) > _SEARCH_CACHE_LIMIT:
        _SEARCH_CACHE.popitem(last=False)


def _sample_fingerprint(prepared_dataset: Mapping[str, Any]) -> Dict[str, Any]:
    """Cheap identity of the numeric sample so cache hits cannot mix different y/X."""
    y = prepared_dataset.get("y")
    X = prepared_dataset.get("X")
    if X is None:
        X = prepared_dataset.get("base_frame")
    parts: Dict[str, Any] = {}
    try:
        if y is not None:
            arr = np.asarray(y, dtype=float).reshape(-1)
            parts["y"] = {
                "n": int(arr.size),
                "sum": float(np.nansum(arr)) if arr.size else 0.0,
                "mean": float(np.nanmean(arr)) if arr.size else 0.0,
                "std": float(np.nanstd(arr)) if arr.size else 0.0,
                "head": float(arr[0]) if arr.size else None,
                "tail": float(arr[-1]) if arr.size else None,
            }
        if X is not None and hasattr(X, "columns"):
            col_fp = {}
            for c in list(X.columns)[:32]:
                arr = np.asarray(X[c], dtype=float).reshape(-1)
                col_fp[str(c)] = {
                    "n": int(arr.size),
                    "sum": float(np.nansum(arr)) if arr.size else 0.0,
                    "std": float(np.nanstd(arr)) if arr.size else 0.0,
                }
            parts["X"] = col_fp
    except Exception:
        parts["fallback"] = str(type(y)) + str(type(X))
    return parts


def _available_predictor_names(
    prepared_dataset: Mapping[str, Any], request_spec: Mapping[str, Any]
) -> List[str]:
    schema = prepared_dataset.get("feature_schema") or {}
    columns = schema.get("columns") or {}
    if columns:
        names = list(columns.keys())
        groups = schema.get("groups") or {}
        for g in groups.values():
            base = g.get("base_variable")
            if base and base not in names:
                names.append(base)
        return names
    frame = prepared_dataset.get("base_frame")
    if frame is None:
        frame = prepared_dataset.get("X")
    if frame is not None:
        target = request_spec.get("target_col")
        return [c for c in list(frame.columns) if c != target]
    return []


def _n_rows(prepared_dataset: Mapping[str, Any]) -> int:
    y = prepared_dataset.get("y")
    if y is not None:
        try:
            return int(len(y))
        except TypeError:
            pass
    row_ids = prepared_dataset.get("row_ids")
    if row_ids is not None:
        return int(len(row_ids))
    X = prepared_dataset.get("X")
    if X is not None:
        return int(len(X))
    return 0


def _frame_for_columns(prepared_dataset: Mapping[str, Any]):
    base = prepared_dataset.get("base_frame")
    X = prepared_dataset.get("X")
    if base is not None and X is not None:
        # Prefer base variables; overlay numeric X columns (dummies).
        frame = base.copy()
        for c in X.columns:
            if c not in frame.columns:
                frame[c] = X[c]
        return frame
    if base is not None:
        return base
    return X


def _resolve_mode(
    requested_mode: str, possible: int, budget: int, threshold: int
) -> Tuple[str, Optional[Dict[str, Any]]]:
    if requested_mode == "exact":
        if possible <= budget:
            return "exact", None
        return (
            "approximate",
            _issue(
                "exact_budget_insufficient",
                "warning",
                "mode=exact was requested but the possible candidate count exceeds the "
                "evaluation budget. Running approximate search; this is not a proven optimum.",
                evidence={"possible": possible, "budget": budget},
            ),
        )
    if requested_mode == "approximate":
        return "approximate", None
    if possible <= min(budget, threshold):
        return "exact", None
    return (
        "approximate",
        _issue(
            "approximate_due_to_budget",
            "warning",
            "Possible candidate count exceeds the exact-mode budget/threshold. "
            "Approximate diverse search is used; exact_optimum_guaranteed remains false.",
            evidence={"possible": possible, "budget": budget, "threshold": threshold},
        ),
    )


def _objective_descriptor(
    search_policy: Mapping[str, Any], evaluation_policy: Mapping[str, Any]
) -> Dict[str, Any]:
    name = search_policy.get("objective") or "original_scale_error"
    required = list(search_policy.get("required_criteria") or ["original_rmse"])
    if evaluation_policy.get("require_precision") and "precision_amplitude_pct" not in required:
        required.append("precision_amplitude_pct")
    return {
        "name": name,
        "scale": "original",
        "required_criteria": required,
        "optional_criteria": ["precision_amplitude_pct", "stability", "complexity"],
        "tie_break": "candidate_id_lexicographic_asc",
        "does_not_use": [
            "r2_across_transformed_vs_original_scales",
            "automatic_sample_row_removal",
        ],
    }


def _resolve_hooks(request_spec: Mapping[str, Any]) -> Dict[str, Any]:
    policy = request_spec.get("search_policy") or {}
    hooks = policy.get("peer_hooks")
    if isinstance(hooks, dict) and hooks.get("labeled") == "CONTRACT_FIXTURE":
        return hooks
    fit = None
    evaluate = None
    inverse = None
    try:
        from . import model_builder as mb

        fit = getattr(mb, "fit_candidate", None)
        evaluate = getattr(mb, "evaluate_fitted", None)
    except Exception:
        fit = None
        evaluate = None
    try:
        from . import target_transform as tt

        inverse = getattr(tt, "inverse_target_prediction", None)
    except Exception:
        inverse = None
    if callable(fit) and callable(evaluate):
        return {
            "fit_candidate": fit,
            "evaluate_fitted": evaluate,
            "inverse_target": inverse,
            "labeled": "C04",
        }
    return {
        "fit_candidate": None,
        "evaluate_fitted": None,
        "inverse_target": inverse,
        "labeled": "legacy_model_builder",
    }


def _finite_number(value: Any) -> bool:
    try:
        return value is not None and bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _is_better(key_a: Tuple, key_b: Tuple) -> bool:
    return key_a > key_b


def _sorted_records(records: Sequence[Mapping[str, Any]], objective: Mapping[str, Any]) -> List[Dict[str, Any]]:
    recs = [dict(r) for r in records]
    recs.sort(key=lambda r: str(r.get("candidate_id") or ""))
    recs.sort(key=lambda r: r.get("_rank_tuple") or ranking_tuple(r, objective), reverse=True)
    return recs


def _trim_retained_models(scored: List[Dict[str, Any]], retain_limit: int) -> None:
    if len(scored) <= retain_limit:
        return
    ranked = _sorted_records(scored, _objective_descriptor({}, {}))
    keep_ids = {r["candidate_id"] for r in ranked[:retain_limit]}
    for rec in scored:
        if rec["candidate_id"] in keep_ids:
            continue
        rec["_legacy_model_result"] = None
        rec["model_object"] = None


def _compact_history_entry(record: Mapping[str, Any]) -> Dict[str, Any]:
    spec = record.get("candidate_spec") or {}
    metrics = record.get("metrics") or {}
    return {
        "candidate_id": record.get("candidate_id"),
        "variables": list(spec.get("features") or []),
        "r2_adj": metrics.get("r2_adjusted"),
        "original_rmse": metrics.get("original_rmse"),
        "grau_fundamentacao": metrics.get("grau_fundamentacao"),
        "valid": bool((record.get("admissibility") or {}).get("label") == "admissible"),
        "label": (record.get("admissibility") or {}).get("label"),
        "discard_reason": record.get("discard_reason"),
        "status": record.get("status"),
    }


def _public_record(record: Optional[Mapping[str, Any]], include_legacy: bool) -> Optional[Dict[str, Any]]:
    if record is None:
        return None
    adm = record.get("admissibility") or {}
    out = {
        "candidate_id": record.get("candidate_id"),
        "candidate_spec": record.get("candidate_spec"),
        "status": record.get("status"),
        "model_eligibility": {
            "status": adm.get("eligibility_status") or "exploratory",
            "reasons": list(adm.get("reasons") or []),
        },
        "value": record.get("value"),
        "admissibility": {
            "numeric_technical": bool(adm.get("numeric_technical")),
            "framing": bool(adm.get("framing")),
            "label": adm.get("label"),
            "reasons": list(adm.get("reasons") or []),
        },
        "ranking": {
            "criteria_used": list(record.get("criteria_used") or []),
            "criteria_omitted": list(record.get("criteria_omitted") or []),
            "tie_break": "candidate_id_lexicographic_asc",
        },
        "metrics": dict(record.get("metrics") or {}),
        "used_row_ids": record.get("used_row_ids"),
        "issues": list(record.get("issues") or []),
        "discard_reason": record.get("discard_reason"),
        "statistical": record.get("statistical"),
        "normative": record.get("normative"),
    }
    if include_legacy:
        out["_legacy_model_result"] = record.get("_legacy_model_result")
    return out


class _ColumnStore:
    def __init__(self, frame):
        self.frame = frame
        self._cache: Dict[Tuple[str, str], Any] = {}

    def get(self, base: str, transform: str):
        key = (base, canonical_transform_name(transform))
        if key in self._cache:
            return self._cache[key]
        if self.frame is None or base not in getattr(self.frame, "columns", []):
            self._cache[key] = None
            return None
        if key[1] in (LINEAR_OPTION, GROUP_OPTION):
            self._cache[key] = self.frame[base]
            return self._cache[key]
        series, ok = Transformer.apply_transformation(self.frame[base], key[1])
        self._cache[key] = series if ok else None
        return self._cache[key]


def _design_from_spec(store: _ColumnStore, spec: Mapping[str, Any], X_fallback) -> Optional[pd.DataFrame]:
    data: Dict[str, Any] = {}
    for cols in (spec.get("feature_groups") or {}).values():
        for c in cols:
            series = store.get(c, LINEAR_OPTION)
            if series is None and X_fallback is not None and c in X_fallback.columns:
                series = X_fallback[c]
            if series is None:
                return None
            data[c] = series
    for base, trans in (spec.get("x_transformations") or {}).items():
        if trans == GROUP_OPTION:
            continue
        col_name = feature_column_name(base, trans)
        series = store.get(base, trans)
        if series is None:
            return None
        data[col_name] = series
    if not data:
        return None
    frame = pd.DataFrame(data)
    return frame


def _y_and_state(
    prepared_dataset: Mapping[str, Any],
    spec: Mapping[str, Any],
    hooks: Mapping[str, Any],
):
    y = prepared_dataset.get("y")
    y_name = (spec.get("y_transformation") or {}).get("name") or Y_IDENTITY
    y_name = canonical_transform_name(y_name)
    if y_name in (LINEAR_OPTION, Y_IDENTITY):
        return y, {"name": Y_IDENTITY}, np.asarray(y, dtype=float)
    y_original = np.asarray(prepared_dataset.get("y_original", y), dtype=float)
    apply_t = None
    try:
        from . import target_transform as tt

        apply_t = getattr(tt, "transform_target", None)
        fit_t = getattr(tt, "fit_target_transform", None)
    except Exception:
        apply_t = None
        fit_t = None
    if callable(fit_t) and callable(apply_t):
        state = fit_t(y, y_name, None)
        y_t = apply_t(y, state)
        return y_t, state, y_original
    # Labeled fixture may supply inverse only; apply numpy transforms for tests.
    if y_name == "ln":
        arr = np.asarray(y, dtype=float)
        if np.any(arr <= 0):
            return None, {"name": y_name}, y_original
        return np.log(arr), {"name": "ln"}, y_original
    return None, {"name": y_name}, y_original


def _inverse_prediction(pred, y_state, hooks):
    name = (y_state or {}).get("name") or Y_IDENTITY
    if name in (Y_IDENTITY, LINEAR_OPTION, None):
        return np.asarray(pred, dtype=float)
    inverse = hooks.get("inverse_target")
    if callable(inverse):
        out = inverse(pred, y_state)
        if isinstance(out, tuple):
            out = out[0]
        if isinstance(out, dict):
            out = out.get("values", out.get("prediction"))
        return np.asarray(out, dtype=float)
    if name == "ln":
        return np.exp(np.asarray(pred, dtype=float))
    return None


def _original_rmse_from_model(
    model,
    X_design: pd.DataFrame,
    y_original,
    y_state,
    hooks,
    intercept: bool,
) -> Optional[float]:
    if model is None or X_design is None:
        return None
    Xc = sm.add_constant(X_design, has_constant="add") if intercept else X_design
    try:
        params_index = list(model.params.index)
        for col in params_index:
            if col not in Xc.columns:
                return None
        Xc = Xc[params_index]
        pred = model.predict(Xc)
    except Exception:
        return None
    pred_orig = _inverse_prediction(pred, y_state, hooks)
    if pred_orig is None:
        return None
    yv = np.asarray(y_original, dtype=float).reshape(-1)
    pv = np.asarray(pred_orig, dtype=float).reshape(-1)
    if yv.shape != pv.shape:
        return None
    if not np.all(np.isfinite(yv)) or not np.all(np.isfinite(pv)):
        return None
    return float(np.sqrt(np.mean((yv - pv) ** 2)))


def _value_from_prediction(model, X_row: pd.DataFrame, intercept: bool) -> Optional[Dict[str, Any]]:
    if model is None or X_row is None or len(X_row) == 0:
        return None
    try:
        Xc = sm.add_constant(X_row, has_constant="add") if intercept else X_row
        params_index = list(model.params.index)
        for col in params_index:
            if col not in Xc.columns:
                return None
        Xc = Xc[params_index]
        prediction = model.get_prediction(Xc)
        summary = prediction.summary_frame(alpha=1 - config.CONFIDENCE_LEVEL_PRECISION)
        point = float(summary["mean"].iloc[0])
        lo = float(summary["mean_ci_lower"].iloc[0])
        hi = float(summary["mean_ci_upper"].iloc[0])
        if not all(_finite_number(v) for v in (point, lo, hi)):
            return {
                "point": point if _finite_number(point) else None,
                "mean_ci80": None,
                "prediction_interval": None,
                "arbitration_interval": None,
                "admissible_interval": None,
            }
        return {
            "point": point,
            "mean_ci80": {"lower": lo, "upper": hi},
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        }
    except Exception:
        return None


def _empty_value() -> Dict[str, Any]:
    return {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }


def _fit_and_score(
    prepared_dataset: Mapping[str, Any],
    spec: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    subject_design: Optional[Mapping[str, Any]],
    column_store: _ColumnStore,
    hooks: Mapping[str, Any],
    evaluation_policy: Mapping[str, Any],
    retain_legacy: bool,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    criteria_used: List[str] = []
    criteria_omitted: List[str] = []
    X_fallback = prepared_dataset.get("X")
    X_design = _design_from_spec(column_store, spec, X_fallback)
    y_fit, y_state, y_original = _y_and_state(prepared_dataset, spec, hooks)
    record: Dict[str, Any] = {
        "candidate_id": spec["candidate_id"],
        "candidate_spec": spec,
        "status": "error",
        "metrics": {},
        "diagnostics": {},
        "coefficients": {},
        "issues": issues,
        "criteria_used": criteria_used,
        "criteria_omitted": criteria_omitted,
        "used_row_ids": list(prepared_dataset.get("row_ids") or []),
        "value": _empty_value(),
        "discard_reason": None,
        "_legacy_model_result": None,
        "model_object": None,
    }
    if X_design is None or y_fit is None:
        record["status"] = "rejected"
        record["discard_reason"] = "design_or_target_unavailable"
        record["admissibility"] = classify_admissibility(record, evaluation_policy)
        record["model_eligibility"] = {
            "status": record["admissibility"]["eligibility_status"],
            "reasons": record["admissibility"]["reasons"],
        }
        return record

    y_name = (y_state or {}).get("name") or Y_IDENTITY
    if y_name not in (Y_IDENTITY, LINEAR_OPTION) and not callable(hooks.get("inverse_target")) and y_name != "ln":
        # Cannot recover original-scale error; do not rank on transformed R².
        record["status"] = "rejected"
        record["discard_reason"] = "y_inverse_unavailable"
        criteria_omitted.append("original_rmse")
        record["admissibility"] = classify_admissibility(record, evaluation_policy)
        return record

    fit_candidate = hooks.get("fit_candidate")
    evaluate_fitted = hooks.get("evaluate_fitted")
    model_result = None
    model_obj = None
    coefficients = {}
    r2_adj = None
    grau = None
    amplitude = None
    used_row_ids = list(prepared_dataset.get("row_ids") or [])
    outliers_removed: List[Any] = []

    if callable(fit_candidate):
        try:
            candidate_fit = fit_candidate(prepared_dataset, spec, request_spec)
        except Exception as exc:
            record["status"] = "error"
            record["discard_reason"] = "fit_candidate_error"
            issues.append(_issue("fit_candidate_error", "error", str(exc), [spec["candidate_id"]]))
            record["admissibility"] = classify_admissibility(record, evaluation_policy)
            return record
        status = (candidate_fit or {}).get("status") if isinstance(candidate_fit, dict) else getattr(candidate_fit, "status", None)
        if status != "fitted":
            record["status"] = status or "rejected"
            record["discard_reason"] = "peer_fit_not_fitted"
            record["admissibility"] = classify_admissibility(record, evaluation_policy)
            return record
        model_obj = candidate_fit.get("model_object") if isinstance(candidate_fit, dict) else getattr(candidate_fit, "model_object", None)
        coefficients = candidate_fit.get("coefficients") if isinstance(candidate_fit, dict) else getattr(candidate_fit, "coefficients", {}) or {}
        used_row_ids = list(
            (candidate_fit.get("used_row_ids") if isinstance(candidate_fit, dict) else getattr(candidate_fit, "used_row_ids", None))
            or used_row_ids
        )
        diagnostics = candidate_fit.get("diagnostics") if isinstance(candidate_fit, dict) else getattr(candidate_fit, "diagnostics", {}) or {}
        record["diagnostics"] = diagnostics or {}
        if callable(evaluate_fitted) and subject_design is not None:
            try:
                assessment = evaluate_fitted(candidate_fit, subject_design, request_spec)
            except Exception as exc:
                issues.append(_issue("evaluate_fitted_error", "warning", str(exc), [spec["candidate_id"]]))
                assessment = None
            if isinstance(assessment, dict):
                record["value"] = assessment.get("value") or record["value"]
                record["statistical"] = assessment.get("statistical")
                record["normative"] = assessment.get("normative")
                rec_metrics = (assessment.get("statistical") or {})
                amplitude = rec_metrics.get("precision_amplitude_pct") or rec_metrics.get("amplitude_pct")
        rmse = _original_rmse_from_model(
            model_obj, X_design, y_original, y_state, hooks, spec.get("intercept", True)
        )
    else:
        builder = ModelBuilder()
        degree = int(evaluation_policy.get("min_fundamentacao_grade") or evaluation_policy.get("target_degree") or 1)
        remove_outliers = bool(evaluation_policy.get("remove_outliers", False))
        y_series = y_fit if isinstance(y_fit, pd.Series) else pd.Series(np.asarray(y_fit), index=X_design.index)
        if len(y_series) != len(X_design):
            y_series = pd.Series(np.asarray(prepared_dataset.get("y")), index=X_design.index)
        model_result = builder.build_model(
            X_design,
            y_series,
            degree=degree,
            remove_outliers=remove_outliers,
            grau_item1=int(evaluation_policy.get("grau_item1") or 1),
            grau_item3=int(evaluation_policy.get("grau_item3") or 1),
        )
        if not model_result.success or model_result.model_metrics is None:
            record["status"] = "rejected"
            record["discard_reason"] = "ols_fit_failed"
            record["admissibility"] = classify_admissibility(record, evaluation_policy)
            return record
        model_obj = model_result.model_object
        coefficients = dict(model_result.coefficients or {})
        r2_adj = model_result.model_metrics.r2_adjusted
        outliers_removed = list(model_result.outliers_removed or [])
        if model_result.validation_result is not None:
            grau = model_result.validation_result.grau_fundamentacao
            amplitude = model_result.validation_result.precisao_amplitude_pct
        subject_raw = None
        if subject_design:
            subject_raw = subject_design.get("raw_values") or subject_design.get("subject_raw")
        if subject_raw and model_result.success:
            original_df = prepared_dataset.get("_legacy_df")
            if original_df is None:
                base = prepared_dataset.get("base_frame")
                y_col = request_spec.get("target_col") or "y"
                if base is not None:
                    original_df = base.copy()
                    original_df[y_col] = prepared_dataset.get("y")
            if original_df is not None:
                model_result = builder.add_precision_and_extrapolation(
                    model_result, dict(subject_raw), original_df, degree=degree
                )
                if model_result.validation_result is not None:
                    grau = model_result.validation_result.grau_fundamentacao
                    amplitude = model_result.validation_result.precisao_amplitude_pct
        rmse = _original_rmse_from_model(
            model_obj, X_design, y_original, y_state, hooks, spec.get("intercept", True)
        )
        record["_legacy_model_result"] = model_result if retain_legacy else None
        if subject_design is not None:
            raw = subject_design.get("raw_values") or {}
            row = {}
            for base, trans in spec.get("x_transformations", {}).items():
                if trans == GROUP_OPTION:
                    continue
                if base not in raw:
                    row = None
                    break
                series, ok = Transformer.apply_transformation(pd.Series([raw[base]]), trans)
                if not ok:
                    row = None
                    break
                row[feature_column_name(base, trans)] = series.iloc[0]
            if row is not None:
                X_row = pd.DataFrame([row])
                for cols in (spec.get("feature_groups") or {}).values():
                    for c in cols:
                        if c in (subject_design.get("X").columns if subject_design.get("X") is not None else []):
                            X_row[c] = subject_design["X"][c].iloc[0]
                record["value"] = _value_from_prediction(model_obj, X_row, spec.get("intercept", True)) or _empty_value()
                if y_name not in (Y_IDENTITY, LINEAR_OPTION) and record["value"].get("point") is not None:
                    inv = _inverse_prediction([record["value"]["point"]], y_state, hooks)
                    if inv is None:
                        record["value"] = _empty_value()
                        criteria_omitted.append("subject_value_original_scale")
                    else:
                        record["value"]["point"] = float(np.asarray(inv).reshape(-1)[0])
                        record["value"]["mean_ci80"] = None

    record["status"] = "fitted"
    record["coefficients"] = coefficients
    record["model_object"] = model_obj if retain_legacy else None
    record["used_row_ids"] = used_row_ids
    metrics: Dict[str, Any] = {
        "complexity": len(spec.get("features") or []),
        "n_outliers_removed": len(outliers_removed),
        "y_transformation": y_name,
    }
    if _finite_number(rmse):
        metrics["original_rmse"] = float(rmse)
        criteria_used.append("original_rmse")
    else:
        criteria_omitted.append("original_rmse")
    if _finite_number(r2_adj):
        metrics["r2_adjusted"] = float(r2_adj)
        if y_name not in (Y_IDENTITY, LINEAR_OPTION):
            metrics["r2_adjusted_scale"] = "transformed_target"
            criteria_omitted.append("r2_adjusted_not_comparable_across_scales")
        else:
            metrics["r2_adjusted_scale"] = "original"
    if grau is not None:
        metrics["grau_fundamentacao"] = grau
    if _finite_number(amplitude):
        metrics["precision_amplitude_pct"] = float(amplitude)
        criteria_used.append("precision_amplitude_pct")
    criteria_used.append("complexity")
    record["metrics"] = metrics
    record["admissibility"] = classify_admissibility(record, evaluation_policy)
    if record["admissibility"]["label"] != "admissible":
        record["discard_reason"] = record["discard_reason"] or ",".join(
            record["admissibility"]["reasons"] or ["exploratory"]
        )
    return record
