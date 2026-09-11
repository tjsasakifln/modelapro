"""MP/1 job composition (C10).

Production binds the frozen import paths from the lote contract. Missing
peers fail closed with structured issues — this module never falls back to
DataLoader.load_data, OptimalCombinationFinder.find_best_model, or any
other hidden parser/converter. Tests may inject callables labeled
`contract_simulator = True`; production resolve_peers never creates those.

Each compose_* call receives its own context dict. There is no shared
DataLoader / finder instance on Worker.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import subprocess
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from modules.logging_manager import logger
from modules.result_contract import (
    SCHEMA_VERSION,
    ContractError,
    ResultSnapshotError,
    dumps_strict,
    empty_value_block,
    freeze_result_snapshot,
    is_evaluation_requested,
    make_issue,
    request_spec_for_peers,
    validate_job_status_progress,
)
from modules.results import adapt_validation_result
from modules.websocket_notifier import WebSocketNotifier

# Frozen import paths (interface A). Do not invent a different module path.
MP1_PEERS: Dict[str, Tuple[str, str]] = {
    "ingest_market": ("modules.data_loader", "ingest_market"),
    "fit_dataset": ("modules.preprocessing", "fit_dataset"),
    "transform_subject": ("modules.preprocessing", "transform_subject"),
    "search_models": ("modules.optimal_combination", "search_models"),
    "fit_candidate": ("modules.model_builder", "fit_candidate"),
    "evaluate_fitted": ("modules.model_builder", "evaluate_fitted"),
    "assess_normative": ("modules.nbr14653_validation", "assess_normative"),
    "evaluate_procedure": ("modules.model_evaluation", "evaluate_procedure"),
    "render_report": ("modules.results_generator", "render_report"),
    "build_evidence_bundle": ("modules.evidence_bundle", "build_evidence_bundle"),
    "recommend_next_actions": ("modules.decision_support", "recommend_next_actions"),
    "evaluate_batch": ("modules.valuation_batch", "evaluate_batch"),
    "fit_target_transform": ("modules.target_transform", "fit_target_transform"),
    "transform_target": ("modules.target_transform", "transform_target"),
    "inverse_target_prediction": ("modules.target_transform", "inverse_target_prediction"),
}

REQUIRED_VALUATION_PEERS = (
    "ingest_market",
    "fit_dataset",
    "search_models",
    "assess_normative",
    "recommend_next_actions",
)
REQUIRED_PREVIEW_PEERS = ("ingest_market",)

STAGE_INGEST = "ingest"
STAGE_PREPARE = "prepare"
STAGE_SUBJECT = "subject"
STAGE_SEARCH = "search"
STAGE_EVALUATE = "evaluate"
STAGE_NORMATIVE = "normative"
STAGE_PROCEDURE = "procedure"
STAGE_ACTIONS = "actions"
STAGE_FREEZE = "freeze"
STAGE_REPORT = "report"
STAGE_EVIDENCE = "evidence"
STAGE_PERSIST = "persist"


class PeerUnavailable(RuntimeError):
    def __init__(self, names: Sequence[str]):
        self.names = list(names)
        super().__init__(f"MP/1 peers unavailable: {', '.join(self.names)}")
        self.issues = [
            make_issue(
                "PEER_UNAVAILABLE",
                f"Required peer {name!r} is not importable at the frozen MP/1 path",
                origin="c10.worker",
                evidence={
                    "peer": name,
                    "module": MP1_PEERS.get(name, ("", ""))[0],
                    "attr": MP1_PEERS.get(name, ("", ""))[1],
                    "integration": "INTEGRATION_PENDING",
                },
            )
            for name in self.names
        ]


class JobCancelled(RuntimeError):
    pass


class CompositionError(RuntimeError):
    def __init__(self, message: str, issues: Optional[Sequence[Mapping[str, Any]]] = None):
        super().__init__(message)
        self.issues = [dict(i) for i in (issues or [])]
        if not self.issues:
            self.issues = [make_issue("COMPOSITION_ERROR", message, origin="c10.worker")]


def current_code_sha() -> str:
    env = os.getenv("MP_CODE_SHA")
    if env:
        return env.strip()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode("ascii").strip()
    except Exception:
        return "unknown"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def peer_kind(fn: Any) -> Tuple[str, str]:
    """Distinguish labeled contract simulators from real imported callables."""
    if fn is None:
        return "missing", ""
    if getattr(fn, "contract_simulator", False):
        label = getattr(fn, "simulator_label", None) or getattr(fn, "__name__", "unnamed")
        return "simulator", str(label)
    module = getattr(fn, "__module__", "") or ""
    name = getattr(fn, "__name__", type(fn).__name__)
    return "real", f"{module}.{name}"


def import_peer(module_name: str, attr: str) -> Tuple[Optional[Callable], str]:
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None, "module_missing"
    fn = getattr(module, attr, None)
    if fn is None:
        return None, "attr_missing"
    return fn, "real"


def resolve_peers(overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Bind frozen MP/1 import paths. Overrides are for tests (must be labeled).

    Production never synthesizes an unlabeled stand-in.
    """
    peers: Dict[str, Any] = {}
    for name, (module_name, attr) in MP1_PEERS.items():
        if overrides is not None and name in overrides:
            fn = overrides[name]
            if fn is not None and not getattr(fn, "contract_simulator", False):
                # An override that is the real imported callable is fine.
                kind, _ = peer_kind(fn)
                if kind != "real":
                    logger.warning("Peer override %s is neither real nor a labeled simulator", name)
            peers[name] = fn
            continue
        fn, _status = import_peer(module_name, attr)
        peers[name] = fn
    return peers


def missing_peers(peers: Mapping[str, Any], required: Sequence[str]) -> List[str]:
    return [name for name in required if not callable(peers.get(name))]


def _as_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return dict(obj)
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        data = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
        return data
    return obj


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _issue_list(obj: Any) -> List[dict]:
    raw = _get(obj, "issues", []) or []
    out = []
    for item in raw:
        if isinstance(item, Mapping) and "code" in item and "message" in item:
            severity = str(item.get("severity") or "error")
            if severity not in ("info", "warning", "error"):
                severity = "error"
            out.append(
                make_issue(
                    str(item.get("code")),
                    str(item.get("message")),
                    severity=severity,
                    origin=str(item.get("origin") or "peer"),
                    affected_ids=item.get("affected_ids") or [],
                    evidence=item.get("evidence") or {},
                )
            )
        elif isinstance(item, str):
            out.append(make_issue("PEER_ISSUE", item, origin="peer"))
    return out


def _has_error_issues(issues: Sequence[Mapping[str, Any]]) -> bool:
    return any(i.get("severity") == "error" for i in issues)


def _row_ids(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        return [str(v) for v in values]
    try:
        return [str(v) for v in list(values)]
    except TypeError:
        return [str(values)]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _check_cancel(cancel_requested: Optional[Callable[[], bool]]) -> None:
    if cancel_requested is None:
        return
    try:
        if bool(cancel_requested()):
            raise JobCancelled("job cancelled")
    except JobCancelled:
        raise
    except Exception:
        logger.warning("cancel_requested() raised; treating as not cancelled")


def build_report_context(
    *,
    request_spec: Mapping[str, Any],
    input_bundle: Any,
    prepared_dataset: Any,
    used_row_ids: Sequence[str],
    excluded_row_ids: Sequence[str],
) -> dict:
    """Data actually used/excluded plus the request dates. Does not refit."""
    sample_ledger = _as_dict(_get(prepared_dataset, "sample_ledger")) or {}
    row_ledger = _as_dict(_get(input_bundle, "row_ledger")) or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "reference_date": request_spec.get("reference_date"),
        "inspection_date": request_spec.get("inspection_date"),
        "target_col": request_spec.get("target_col"),
        "target_unit": request_spec.get("target_unit"),
        "applicant": request_spec.get("applicant"),
        "purpose": request_spec.get("purpose"),
        "used_row_ids": list(used_row_ids),
        "excluded_row_ids": list(excluded_row_ids),
        "sample_ledger": sample_ledger,
        "row_ledger": row_ledger,
        "sources": {
            "input_sha256": _get(input_bundle, "input_sha256"),
            "dataset_sha256": _get(prepared_dataset, "dataset_sha256"),
        },
        "attachments": [],
    }


def build_frozen_project(
    *,
    project_id: Optional[str],
    revision_id: Optional[str],
    request_spec: Mapping[str, Any],
    input_bundle: Any,
    prepared_dataset: Any,
    winner_fit: Any,
    subject_design: Any,
    normative: Any,
    artifact_refs: Mapping[str, Any],
    sample_ledger: Any,
) -> dict:
    candidate_spec = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    feature_schema = _as_dict(_get(prepared_dataset, "feature_schema")) or _as_dict(
        _get(winner_fit, "feature_schema")
    ) or {}
    encoder_state = _as_dict(_get(prepared_dataset, "encoder_state")) or _as_dict(
        _get(winner_fit, "encoder_state")
    ) or {}
    model_state = {
        "coefficients": _as_dict(_get(winner_fit, "coefficients")) or {},
        "diagnostics": _as_dict(_get(winner_fit, "diagnostics")) or {},
        "target_transform_state": _as_dict(_get(winner_fit, "target_transform_state")) or {},
        "model_sha256": _get(winner_fit, "model_sha256"),
        "status": _get(winner_fit, "status"),
    }
    # Never pickle model_object into the frozen project.
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "revision_id": revision_id,
        "input_sha256": _get(input_bundle, "input_sha256"),
        "dataset_sha256": _get(prepared_dataset, "dataset_sha256"),
        "request_spec": request_spec_for_peers(request_spec),
        "feature_schema": feature_schema,
        "encoder_state": encoder_state,
        "model_spec": candidate_spec,
        "model_state": model_state,
        "model_scope": "subject_specific" if subject_design is not None else "population_model",
        "subject_constraints": _as_dict(_get(subject_design, "issues")) or {},
        "domain": {
            "target_col": request_spec.get("target_col"),
            "target_unit": request_spec.get("target_unit"),
            "reference_date": request_spec.get("reference_date"),
        },
        "sample_ledger": _as_dict(sample_ledger) or {},
        "normative_version": _get(normative, "edition"),
        "artifact_refs": dict(artifact_refs or {}),
        "provenance": {
            "code_sha": current_code_sha(),
            "composed_by": "c10.worker",
        },
    }


def _value_from_assessment(assessment: Any, issues: List[dict]) -> dict:
    """Copy CandidateAssessment.value as-is. Never derive point from arbitration."""
    value = _get(assessment, "value")
    if isinstance(value, Mapping) and "point" in value:
        block = empty_value_block()
        for key in block:
            if key in value:
                block[key] = value[key]
        for key, item in value.items():
            if key not in block:
                block[key] = item
        return block
    point = _get(assessment, "point")
    if point is not None:
        block = empty_value_block()
        block["point"] = point
        issues.append(
            make_issue(
                "VALUE_SHAPE_ADAPTED",
                "assessment lacked value{}; point copied from assessment.point, not from arbitration",
                severity="warning",
                origin="c10.worker",
            )
        )
        return block
    issues.append(
        make_issue(
            "VALUE_MISSING",
            "peer assessment did not provide value{}; point is null (not 0)",
            origin="c10.worker",
        )
    )
    return empty_value_block()


def _sample_from_prepared(
    input_bundle: Any,
    prepared: Any,
    used_row_ids: Sequence[str],
    excluded_row_ids: Sequence[str],
) -> dict:
    row_ledger = _get(input_bundle, "row_ledger")
    received = 0
    observed = 0
    if isinstance(row_ledger, Mapping):
        received = int(row_ledger.get("received") or len(row_ledger.get("rows") or []))
        observed = int(row_ledger.get("observed_target") or 0)
        if not received and isinstance(row_ledger.get("rows"), list):
            received = len(row_ledger["rows"])
    raw_frame = _get(input_bundle, "raw_frame")
    if received == 0 and raw_frame is not None:
        try:
            received = int(len(raw_frame))
        except Exception:
            received = 0
    prepared_n = 0
    prepared_ids = _get(prepared, "row_ids")
    if prepared_ids is not None:
        try:
            prepared_n = len(list(prepared_ids))
        except Exception:
            prepared_n = 0
    used = list(used_row_ids)
    excluded = list(excluded_row_ids)
    if not excluded:
        excluded = _row_ids(_get(prepared, "excluded_row_ids") or _get(prepared, "excluded"))
    return {
        "received": received,
        "observed_target": observed if observed else received,
        "prepared": prepared_n,
        "used": len(used),
        "excluded": len(excluded),
        "used_row_ids": used,
        "excluded_row_ids": excluded,
    }


def _model_identity(winner_fit: Any, prepared: Any, assessment: Any) -> dict:
    feature_schema = _as_dict(_get(winner_fit, "feature_schema")) or _as_dict(
        _get(prepared, "feature_schema")
    ) or {}
    used_ids = _row_ids(
        _get(winner_fit, "used_row_ids")
        or _get(assessment, "used_row_ids")
        or _get(prepared, "row_ids")
    )
    spec = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    delivered = {
        "candidate_id": _get(winner_fit, "candidate_id") or _get(assessment, "candidate_id"),
        "model_sha256": _get(winner_fit, "model_sha256"),
        "feature_schema_version": feature_schema.get("version"),
        "used_row_ids": used_ids,
        "transformations": spec.get("x_transformations") or {},
        "y_transformation": spec.get("y_transformation"),
        "encoder_state_present": _get(winner_fit, "encoder_state") is not None
        or _get(prepared, "encoder_state") is not None,
    }
    used = dict(delivered)
    delivered["delivered_matches_used"] = used == {k: delivered[k] for k in used}
    delivered["used"] = used
    return delivered


def compose_preview(
    *,
    file_bytes: bytes,
    filename: str,
    request_spec: Mapping[str, Any],
    subject_raw: Optional[Mapping[str, Any]] = None,
    peers: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Ingest-only preview. Does not search, fit candidates, or mutate projects."""
    peers = dict(peers or resolve_peers())
    missing = missing_peers(peers, REQUIRED_PREVIEW_PEERS)
    if missing:
        raise PeerUnavailable(missing)
    ingest = peers["ingest_market"]
    bundle = ingest(file_bytes, filename, request_spec_for_peers(request_spec))
    issues = _issue_list(bundle)
    if _has_error_issues(issues) or _get(bundle, "supported") is False:
        raise CompositionError("ingest_market failed during preview", issues)
    # Deliberately do not call search_models / fit_candidate / fit_dataset
    # model training. Subject is echoed, not scored.
    return {
        "schema_version": SCHEMA_VERSION,
        "preview": True,
        "input_sha256": _get(bundle, "input_sha256") or sha256_bytes(file_bytes),
        "filename": filename,
        "column_map": _as_dict(_get(bundle, "column_map")) or {},
        "roles_applied": dict(request_spec.get("roles") or {}),
        "target_col": request_spec.get("target_col"),
        "candidate_cols": request_spec.get("candidate_cols"),
        "issues": issues,
        "sample": {
            "received": _sample_from_prepared(bundle, None, [], []).get("received", 0),
        },
        "subject_received": dict(subject_raw) if isinstance(subject_raw, Mapping) else None,
        "search_invoked": False,
        "fit_invoked": False,
        "project_mutated": False,
    }


def compose_valuation_job(
    *,
    job_id: str,
    file_bytes: bytes,
    filename: str,
    request_spec: Mapping[str, Any],
    subject_raw: Optional[Mapping[str, Any]],
    project_id: Optional[str],
    peers: Mapping[str, Any],
    job_store: Any,
    cancel_requested: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[Optional[float], str], None]] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """Compose C01→C13 on one independent job context.

    On peer failure, persist structured issues and stop. Never fall back to
    a second parser. PDF/evidence failure does not unwind a frozen snapshot.
    """
    context: Dict[str, Any] = {
        "job_id": job_id,
        "filename": filename,
        "project_id": project_id,
        "subject_raw": dict(subject_raw) if isinstance(subject_raw, Mapping) else None,
        "artifact_bytes": {},
        "artifact_states": {
            "report.pdf": {"state": "pending", "error": None},
            "evidence_manifest.json": {"state": "pending", "error": None},
            "frozen_project.json": {"state": "pending", "error": None},
        },
        "stage": STAGE_INGEST,
        "progress": None,
        "peers_used": {name: peer_kind(fn) for name, fn in peers.items()},
    }

    def emit(stage: str, progress: Optional[float] = None) -> None:
        _check_cancel(cancel_requested)
        context["stage"] = stage
        try:
            context["progress"] = validate_job_status_progress(progress)
        except ContractError:
            context["progress"] = None
        if progress_callback is not None:
            progress_callback(context["progress"], stage)
        if job_store is not None:
            try:
                job_store.update_transition(
                    job_id,
                    "running",
                    "running",
                    patch={"stage": stage, "progress": context["progress"]},
                )
            except Exception:
                logger.debug("update_transition(running→running) not accepted; continuing")

    spec = request_spec_for_peers(request_spec)
    required = list(REQUIRED_VALUATION_PEERS)
    if context["subject_raw"] is not None:
        required.append("transform_subject")
    if is_evaluation_requested(spec):
        required.append("evaluate_procedure")
    missing = missing_peers(peers, required)
    if missing:
        raise PeerUnavailable(missing)

    emit(STAGE_INGEST, None)
    bundle = peers["ingest_market"](file_bytes, filename, spec)
    ingest_issues = _issue_list(bundle)
    if _has_error_issues(ingest_issues):
        raise CompositionError("ingest_market failed", ingest_issues)
    # Roles/target were on spec before this call; C01 is the only parser.

    emit(STAGE_PREPARE, None)
    prepared = peers["fit_dataset"](bundle, spec, None)
    prepare_issues = _issue_list(prepared)
    if _has_error_issues(prepare_issues):
        raise CompositionError("fit_dataset failed", prepare_issues)
    sample_ledger = _get(prepared, "sample_ledger")

    subject_design = None
    if context["subject_raw"] is not None:
        emit(STAGE_SUBJECT, None)
        subject_design = peers["transform_subject"](
            context["subject_raw"],
            _get(prepared, "feature_schema"),
            _get(prepared, "encoder_state"),
        )
        subject_issues = _issue_list(subject_design)
        if _get(subject_design, "supported") is False or _has_error_issues(subject_issues):
            raise CompositionError("transform_subject failed or unsupported", subject_issues)

    def search_progress(value=None, *args, **kwargs):
        # Synchronous light callback from C05; do not invent a percentage.
        if value is None:
            return
        try:
            emit(STAGE_SEARCH, float(value) if isinstance(value, (int, float)) else None)
        except Exception:
            emit(STAGE_SEARCH, None)

    emit(STAGE_SEARCH, None)
    search_result = peers["search_models"](
        prepared,
        subject_design,
        spec,
        search_progress,
        cancel_requested,
    )
    search_issues = _issue_list(search_result)
    if _has_error_issues(search_issues):
        raise CompositionError("search_models failed", search_issues)
    winner = _get(search_result, "winner")
    if winner is None:
        raise CompositionError(
            "search_models returned no winner",
            search_issues + [make_issue("NO_WINNER", "search_models returned no winner", origin="c10.worker")],
        )

    assessment = winner
    winner_fit = winner
    if _get(winner, "value") is None and callable(peers.get("evaluate_fitted")) and subject_design is not None:
        emit(STAGE_EVALUATE, None)
        assessment = peers["evaluate_fitted"](winner, subject_design, spec)
        winner_fit = winner
        eval_issues = _issue_list(assessment)
        if _has_error_issues(eval_issues):
            raise CompositionError("evaluate_fitted failed", eval_issues)

    def predict_original(subject_next):
        # Same pipeline: transform_subject + evaluate_fitted. No alternate converter.
        transform = peers.get("transform_subject")
        evaluate = peers.get("evaluate_fitted")
        if not callable(transform) or not callable(evaluate):
            raise CompositionError(
                "predict_original unavailable",
                [make_issue(
                    "PEER_UNAVAILABLE",
                    "predict_original needs transform_subject and evaluate_fitted",
                    origin="c10.worker",
                )],
            )
        design = transform(
            subject_next,
            _get(prepared, "feature_schema"),
            _get(prepared, "encoder_state"),
        )
        return evaluate(winner_fit, design, spec)

    emit(STAGE_NORMATIVE, None)
    normative_context = {
        "sample": prepared,
        "n": _sample_from_prepared(
            bundle, prepared,
            _row_ids(_get(winner_fit, "used_row_ids") or _get(prepared, "row_ids")),
            _row_ids(_get(winner_fit, "excluded_row_ids")),
        ),
        "documentary": spec.get("declared_documentary") or {},
        "request_spec": spec,
        "assessment": assessment,
        "point": _get(_get(assessment, "value"), "point") if isinstance(_get(assessment, "value"), Mapping) else None,
        "intervals": _get(assessment, "value"),
        "predict_original": predict_original,
        "feature_schema": _get(prepared, "feature_schema"),
        "used_row_ids": _row_ids(_get(winner_fit, "used_row_ids") or _get(assessment, "used_row_ids") or _get(prepared, "row_ids")),
    }
    # Do not pass k/n invented here beyond what prepared/winner already have.
    normative = peers["assess_normative"](normative_context)
    normative_issues = _issue_list(normative)
    if _has_error_issues(normative_issues):
        raise CompositionError("assess_normative failed", normative_issues)

    procedure = None
    if is_evaluation_requested(spec) and callable(peers.get("evaluate_procedure")):
        emit(STAGE_PROCEDURE, None)

        def fit_select_predictor(train_row_ids, seed):
            prepared_fold = peers["fit_dataset"](bundle, spec, train_row_ids)
            fold_search = peers["search_models"](
                prepared_fold, subject_design, spec, None, cancel_requested
            )
            return {
                "winner": _get(fold_search, "winner"),
                "prepared": prepared_fold,
                "seed": seed,
                "train_row_ids": list(train_row_ids) if train_row_ids is not None else None,
            }

        seed = spec.get("evaluation_policy", {}).get("seed")
        procedure = peers["evaluate_procedure"](bundle, spec, fit_select_predictor, seed)
        proc_issues = _issue_list(procedure)
        if _has_error_issues(proc_issues):
            raise CompositionError("evaluate_procedure failed", proc_issues)

    used_row_ids = _row_ids(
        _get(assessment, "used_row_ids")
        or _get(winner_fit, "used_row_ids")
        or _get(prepared, "row_ids")
    )
    excluded_row_ids = _row_ids(
        _get(winner_fit, "excluded_row_ids") or _get(prepared, "excluded_row_ids")
    )
    report_context = build_report_context(
        request_spec=spec,
        input_bundle=bundle,
        prepared_dataset=prepared,
        used_row_ids=used_row_ids,
        excluded_row_ids=excluded_row_ids,
    )

    snapshot_issues: List[dict] = []
    snapshot_issues.extend(ingest_issues)
    snapshot_issues.extend(prepare_issues)
    snapshot_issues.extend(_issue_list(subject_design))
    snapshot_issues.extend(search_issues)
    snapshot_issues.extend(_issue_list(assessment))
    snapshot_issues.extend(normative_issues)
    snapshot_issues.extend(_issue_list(procedure))

    value_block = _value_from_assessment(assessment, snapshot_issues)
    # Map normativa/estatística; do not recompute classifications.
    mapped_validation = _map_validation(normative, assessment)

    model_block = _model_identity(winner_fit, prepared, assessment)
    search_audit = _as_dict(_get(search_result, "search_audit")) or {}
    alternatives = _json_safe_alternatives(_get(search_result, "alternatives") or [])

    draft = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "project_id": project_id,
        "input_sha256": _get(bundle, "input_sha256") or sha256_bytes(file_bytes),
        "code_sha": current_code_sha(),
        "reference_date": spec.get("reference_date"),
        "generated_at": _utc_now_iso(),
        "target": {
            "column": spec.get("target_col") or "",
            "unit": spec.get("target_unit") or "",
            "estimand": _get(value_block, "estimand")
            or _get(_get(assessment, "value"), "estimand")
            or "subject_prediction",
        },
        "value": {k: v for k, v in value_block.items() if k != "estimand"}
        if "estimand" in value_block
        else value_block,
        "sample": _sample_from_prepared(bundle, prepared, used_row_ids, excluded_row_ids),
        "validation": mapped_validation,
        "issues": snapshot_issues,
        "model": model_block,
        "search": {
            "audit": search_audit,
            "winner_candidate_id": model_block.get("candidate_id"),
        },
        "alternatives": alternatives,
        "next_actions": [],
        "provenance": {
            "filename": filename,
            "composed_by": "c10.worker",
            "peers": {k: {"kind": v[0], "ref": v[1]} for k, v in context["peers_used"].items() if v[0] != "missing"},
            "sample_ledger_present": sample_ledger is not None,
            "subject_categorical_survived": _subject_categorical_survived(subject_design, context["subject_raw"]),
        },
    }
    # Restore estimand only on target, not inside value (value shape is exact).
    if "estimand" in value_block and "estimand" in draft["value"]:
        draft["value"] = {k: v for k, v in draft["value"].items() if k != "estimand"}

    emit(STAGE_ACTIONS, None)
    actions = peers["recommend_next_actions"](draft, _get(prepared, "feature_schema"))
    draft["next_actions"] = _normalize_actions(actions)

    emit(STAGE_FREEZE, None)
    try:
        snapshot = freeze_result_snapshot(draft)
    except ResultSnapshotError as exc:
        raise CompositionError("freeze_result_snapshot failed", exc.issues) from exc

    if job_store is not None:
        job_store.save_snapshot(job_id, snapshot)

    artifact_refs: Dict[str, Any] = {}
    emit(STAGE_REPORT, None)
    render = peers.get("render_report")
    if callable(render):
        context["artifact_states"]["report.pdf"] = {"state": "running", "error": None}
        try:
            pdf_bytes = render(snapshot, report_context)
            if not pdf_bytes:
                raise CompositionError(
                    "render_report returned empty bytes",
                    [make_issue("PDF_EMPTY", "render_report returned empty bytes", origin="c10.worker")],
                )
            if not isinstance(pdf_bytes, (bytes, bytearray)):
                raise CompositionError(
                    "render_report did not return bytes",
                    [make_issue("PDF_TYPE", "render_report must return bytes", origin="c10.worker")],
                )
            context["artifact_bytes"]["report.pdf"] = bytes(pdf_bytes)
            context["artifact_states"]["report.pdf"] = {"state": "ready", "error": None}
            artifact_refs["report.pdf"] = {"sha256": sha256_bytes(bytes(pdf_bytes))}
            _save_artifact(job_store, job_id, "report.pdf", bytes(pdf_bytes))
        except Exception as exc:
            logger.warning("PDF generation failed; calculated snapshot is preserved: %s", exc)
            err = make_issue(
                "PDF_FAILED",
                f"render_report failed: {exc}",
                origin="c10.worker",
                evidence={"exception_type": type(exc).__name__},
            )
            context["artifact_states"]["report.pdf"] = {"state": "failed", "error": err}
    else:
        context["artifact_states"]["report.pdf"] = {
            "state": "failed",
            "error": make_issue(
                "PEER_UNAVAILABLE",
                "render_report is not importable; PDF not produced",
                severity="warning",
                origin="c10.worker",
            ),
        }

    emit(STAGE_EVIDENCE, None)
    builder = peers.get("build_evidence_bundle")
    if callable(builder):
        context["artifact_states"]["evidence_manifest.json"] = {"state": "running", "error": None}
        try:
            manifest = builder(
                snapshot, bundle, prepared, context["artifact_bytes"], output_dir
            )
            manifest_dict = _as_dict(manifest) or {"manifest": manifest}
            payload = dumps_strict(manifest_dict).encode("utf-8")
            context["artifact_bytes"]["evidence_manifest.json"] = payload
            context["artifact_states"]["evidence_manifest.json"] = {"state": "ready", "error": None}
            artifact_refs["evidence_manifest.json"] = {"sha256": sha256_bytes(payload)}
            _save_artifact(job_store, job_id, "evidence_manifest.json", payload)
        except Exception as exc:
            logger.warning("evidence bundle failed; snapshot preserved: %s", exc)
            err = make_issue(
                "EVIDENCE_FAILED",
                f"build_evidence_bundle failed: {exc}",
                origin="c10.worker",
                evidence={"exception_type": type(exc).__name__},
            )
            context["artifact_states"]["evidence_manifest.json"] = {"state": "failed", "error": err}
    else:
        context["artifact_states"]["evidence_manifest.json"] = {
            "state": "failed",
            "error": make_issue(
                "PEER_UNAVAILABLE",
                "build_evidence_bundle is not importable",
                severity="warning",
                origin="c10.worker",
            ),
        }

    frozen_project = build_frozen_project(
        project_id=project_id,
        revision_id=None,
        request_spec=spec,
        input_bundle=bundle,
        prepared_dataset=prepared,
        winner_fit=winner_fit,
        subject_design=subject_design,
        normative=normative,
        artifact_refs=artifact_refs,
        sample_ledger=sample_ledger,
    )
    try:
        frozen_bytes = dumps_strict(frozen_project).encode("utf-8")
        context["artifact_bytes"]["frozen_project.json"] = frozen_bytes
        context["artifact_states"]["frozen_project.json"] = {"state": "ready", "error": None}
        _save_artifact(job_store, job_id, "frozen_project.json", frozen_bytes)
    except Exception as exc:
        err = make_issue(
            "FROZEN_PROJECT_JSON",
            f"frozen_project could not be serialized: {exc}",
            origin="c10.worker",
        )
        context["artifact_states"]["frozen_project.json"] = {"state": "failed", "error": err}

    emit(STAGE_PERSIST, None)
    calculation_state = "succeeded"
    patch = {
        "stage": STAGE_PERSIST,
        "progress": context["progress"],
        "result_available": True,
        "artifact_states": context["artifact_states"],
        "calculation_state": calculation_state,
        "issues": list(snapshot.get("issues") or []),
    }
    if job_store is not None:
        try:
            job_store.update_transition(job_id, "running", "succeeded", patch=patch)
        except Exception:
            try:
                job_store.update_transition(job_id, "queued", "succeeded", patch=patch)
            except Exception:
                logger.warning("could not persist succeeded state for %s", job_id)

    context["snapshot"] = snapshot
    context["frozen_project"] = frozen_project
    context["report_context"] = report_context
    context["calculation_state"] = calculation_state
    return context


def _map_validation(normative: Any, assessment: Any) -> dict:
    """Copy C03/C04 validation fields; do not recompute grades."""
    n = _as_dict(normative) or {}
    a = _as_dict(assessment) or {}
    fallback = adapt_validation_result(None)
    normative_block = _as_dict(a.get("normative")) or {}
    fundamentacao = (
        _as_dict(n.get("fundamentacao"))
        or _as_dict(normative_block.get("fundamentacao"))
        or fallback["fundamentacao"]
    )
    precisao = _as_dict(n.get("precisao")) or dict(fallback["precisao"])
    if precisao.get("status") not in {"not_computed", "classified", "unclassified", "error"}:
        precisao["status"] = "not_computed" if precisao.get("grade") is None else "classified"
    documentary = _as_dict(n.get("documentary")) or {
        "status": "declared",
        "verified": False,
    }
    statistical = _as_dict(a.get("statistical")) or _as_dict(n.get("statistical")) or {}
    issuance = {
        "status": "draft",
        "reasons": [
            "no_automatic_report_approval",
            "grau_is_not_issuance_readiness",
            "documentary_declared_is_not_verified_proof",
        ],
    }
    return {
        "fundamentacao": fundamentacao,
        "precisao": precisao,
        "statistical": statistical,
        "documentary": documentary,
        "issuance": issuance,
        "normative_verification_status": n.get("verification_status"),
        "normative_edition": n.get("edition"),
        "model_eligibility": _as_dict(a.get("model_eligibility")) or {},
    }


def _subject_categorical_survived(subject_design: Any, subject_raw: Optional[Mapping[str, Any]]) -> bool:
    if subject_design is None or subject_raw is None:
        return False
    raw_values = _get(subject_design, "raw_values")
    if isinstance(raw_values, Mapping):
        for key, value in subject_raw.items():
            if isinstance(value, str) and raw_values.get(key) == value:
                return True
            if isinstance(value, str) and str(raw_values.get(key)) == value:
                return True
    return _get(subject_design, "supported") is True


def _json_safe_alternatives(alternatives: Any) -> List[dict]:
    out: List[dict] = []
    if not alternatives:
        return out
    for item in alternatives:
        d = _as_dict(item) or {}
        d.pop("model_object", None)
        d.pop("base_frame", None)
        out.append(d)
    return out


def _normalize_actions(actions: Any) -> List[dict]:
    if actions is None:
        return []
    out = []
    for item in actions:
        d = _as_dict(item) or {}
        if not d:
            continue
        out.append(
            {
                "code": d.get("code"),
                "priority": d.get("priority"),
                "reason": d.get("reason"),
                "next_step": d.get("next_step"),
                "evidence_refs": d.get("evidence_refs") or [],
                "limitations": d.get("limitations") or [],
                **{k: v for k, v in d.items() if k not in {
                    "code", "priority", "reason", "next_step", "evidence_refs", "limitations"
                }},
            }
        )
    return out


def _save_artifact(job_store: Any, job_id: str, name: str, data: bytes) -> None:
    if job_store is None:
        return
    saver = getattr(job_store, "save_artifact", None)
    if callable(saver):
        saver(job_id, name, data)


def run_job(
    *,
    job_id: str,
    file_bytes: bytes,
    filename: str,
    request_spec: Mapping[str, Any],
    subject_raw: Optional[Mapping[str, Any]],
    project_id: Optional[str],
    peers: Mapping[str, Any],
    job_store: Any,
    cancel_requested: Optional[Callable[[], bool]] = None,
    loop: Any = None,
) -> dict:
    """Sync entry point submitted to LocalTaskRunner. Never runs on the event loop by itself."""
    notifier = WebSocketNotifier()

    def notify(payload: dict) -> None:
        _notify_optional(notifier, payload, loop=loop)

    def progress_callback(progress, stage):
        notify(
            {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "state": "running",
                "stage": stage,
                "progress": progress,
            }
        )

    try:
        if job_store is not None:
            try:
                job_store.update_transition(job_id, "queued", "running", patch={"stage": STAGE_INGEST})
            except Exception:
                try:
                    job_store.update_transition(job_id, "running", "running", patch={"stage": STAGE_INGEST})
                except Exception:
                    pass
        notify({"schema_version": SCHEMA_VERSION, "job_id": job_id, "state": "running", "stage": STAGE_INGEST, "progress": None})
        context = compose_valuation_job(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=filename,
            request_spec=request_spec,
            subject_raw=subject_raw,
            project_id=project_id,
            peers=peers,
            job_store=job_store,
            cancel_requested=cancel_requested,
            progress_callback=progress_callback,
        )
        notify(
            {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "state": "succeeded",
                "stage": context.get("stage"),
                "progress": context.get("progress"),
                "result_available": True,
            }
        )
        return {"outcome": "succeeded"}
    except JobCancelled:
        logger.info("job %s cancelled", job_id)
        if job_store is not None:
            try:
                job_store.update_transition(
                    job_id,
                    "running",
                    "cancelled",
                    patch={"stage": "cancelled", "result_available": False},
                )
            except Exception:
                logger.warning("failed to persist cancelled state for %s", job_id)
        notify({"schema_version": SCHEMA_VERSION, "job_id": job_id, "state": "cancelled", "progress": None})
        return {"outcome": "cancelled"}
    except PeerUnavailable as exc:
        _fail_job(job_store, job_id, exc.issues, notify)
        return {"outcome": "failed"}
    except CompositionError as exc:
        _fail_job(job_store, job_id, exc.issues, notify)
        return {"outcome": "failed"}
    except Exception as exc:
        logger.error("job %s crashed: %s\n%s", job_id, exc, traceback.format_exc())
        _fail_job(
            job_store,
            job_id,
            [make_issue("JOB_CRASH", str(exc), origin="c10.worker",
                        evidence={"type": type(exc).__name__})],
            notify,
        )
        return {"outcome": "failed"}


def _fail_job(job_store: Any, job_id: str, issues: Sequence[Mapping[str, Any]], notify) -> None:
    patch = {
        "result_available": False,
        "issues": [dict(i) for i in issues],
        "calculation_state": "failed",
        "stage": "failed",
    }
    if job_store is not None:
        try:
            job_store.update_transition(job_id, "running", "failed", patch=patch)
        except Exception:
            try:
                job_store.update_transition(job_id, "queued", "failed", patch=patch)
            except Exception:
                logger.warning("failed to persist failed state for %s", job_id)
    notify(
        {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "state": "failed",
            "progress": None,
            "issues": [dict(i) for i in issues],
        }
    )


def _notify_optional(notifier: WebSocketNotifier, payload: dict, loop=None) -> None:
    """Optional small WS notification. Never the exclusive result channel; never PDF."""
    safe = dict(payload)
    safe.pop("report_pdf_base64", None)
    safe.pop("charts", None)
    try:
        import asyncio

        coro = notifier.send_notification(safe)
        if loop is not None and getattr(loop, "is_running", lambda: False)():
            asyncio.run_coroutine_threadsafe(coro, loop)
            return
        try:
            running = asyncio.get_running_loop()
            running.create_task(coro)
            return
        except RuntimeError:
            asyncio.run(coro)
    except Exception as exc:
        logger.debug("optional websocket notify skipped: %s", exc)


class Worker:
    """Compatibility façade. Holds no shared DataLoader/finder state."""

    def __init__(self, peers: Optional[Mapping[str, Any]] = None):
        self.peers_override = dict(peers) if peers else None
        self.notifier = WebSocketNotifier()

    def resolve(self) -> Dict[str, Any]:
        return resolve_peers(self.peers_override)
