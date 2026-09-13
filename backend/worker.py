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
import io
import json
import math
import os
import re
import subprocess
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
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
from modules.pro_workflow.report_context import (
    aligned_fit_series,
    complete_report_context,
    formula_from_coefficients,
)
from modules.pro_workflow.numeric_disclosure import build_numeric_disclosure
from modules.pro_workflow.residual_state import (
    CALCULATION_VERSION,
    complete_residual_state_for_persist,
    residual_state_is_complete,
)
from modules.pro_workflow.workflow_context import build_workflow_context
from modules.results import adapt_validation_result
from modules.websocket_notifier import WebSocketNotifier

# Frozen import paths (interface A). Do not invent a different module path.
MP1_PEERS: Dict[str, Tuple[str, str]] = {
    "ingest_market": ("modules.data_loader", "ingest_market"),
    "fit_dataset": ("modules.preprocessing", "fit_dataset"),
    "transform_subject": ("modules.preprocessing", "transform_subject"),
    "search_models": ("modules.optimal_combination", "search_models"),
    "fit_candidate": ("modules.model_builder", "fit_candidate"),
    "evaluate_fitted": ("modules.valuation_batch", "evaluate_fitted"),
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
    if getattr(sys, "frozen", False):
        identity_path = Path(sys._MEIPASS) / "build-source-identity.json"
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            source_sha = str(payload.get("source_sha") or "")
            tree_sha = str(payload.get("tree_sha") or "")
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
            raise RuntimeError("frozen build source identity is absent or invalid") from exc
        if (
            payload.get("schema_version") != "MP-COM-BUILD-IDENTITY/1"
            or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not re.fullmatch(r"[0-9a-f]{40}", tree_sha)
        ):
            raise RuntimeError("frozen build source identity is absent or invalid")
        return source_sha
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


def _point_from(obj: Any) -> Optional[float]:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        if "point" in obj:
            value = obj.get("point")
        else:
            nested = obj.get("value")
            value = nested.get("point") if isinstance(nested, Mapping) else nested
    else:
        value = _get(obj, "point")
        if value is None:
            nested = _get(obj, "value")
            value = nested.get("point") if isinstance(nested, Mapping) else nested
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _json_coeffs(obj: Any) -> Dict[str, float]:
    raw = _as_dict(_get(obj, "coefficients")) or {}
    out: Dict[str, float] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, value in raw.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out[str(key)] = number
    return out


def _encoder_fingerprint(encoder_state: Any) -> str:
    data = _as_dict(encoder_state) or {}
    try:
        payload = dumps_strict(data)
    except Exception:
        payload = str(sorted(data.keys()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _preview_column_profile(bundle: Any, spec: Mapping[str, Any]) -> dict:
    """Column kinds/categories from parsed_frame. Not a fitted encoder."""
    parsed = _get(bundle, "parsed_frame")
    column_map = _as_dict(_get(bundle, "column_map")) or {}
    entries = column_map.get("entries") or []
    roles = dict(spec.get("roles") or {})
    columns: Dict[str, Any] = {}
    groups: Dict[str, Any] = {}
    import pandas as pd

    frame = parsed if isinstance(parsed, pd.DataFrame) else pd.DataFrame(parsed) if parsed is not None else pd.DataFrame()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        original = str(entry.get("original") or "")
        internal = str(entry.get("internal") or original)
        series = frame[internal] if internal in frame.columns else None
        kind = "numeric"
        categories = None
        if series is not None and (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            kind = "categorical"
            categories = sorted({str(v) for v in series.dropna().tolist()})
            groups[internal] = {"columns": [], "base_variable": original or internal}
        columns[internal] = {
            "original_name": original,
            "role": roles.get(original) or roles.get(internal),
            "kind": kind,
            "unit": (spec.get("units") or {}).get(original),
            "group_id": internal if kind == "categorical" else None,
            "categories": categories,
            "reference_category": None,
        }
    sample_preview = []
    if not frame.empty:
        preview_df = frame.head(8)
        for _, rec in preview_df.iterrows():
            sample_preview.append({str(k): (None if rec[k] != rec[k] else rec[k]) for k in preview_df.columns})
    ledger = _get(bundle, "row_ledger")
    if isinstance(ledger, (list, tuple)):
        row_ledger = list(ledger)
    else:
        row_ledger = _as_dict(ledger) or []
    return {
        "feature_schema": {
            "version": "MP/1-preview",
            "preview": True,
            "columns": columns,
            "groups": groups,
            "target": {"column": spec.get("target_col") or "", "unit": spec.get("target_unit") or ""},
        },
        "row_ledger": row_ledger,
        "sample_preview": sample_preview,
    }


def _rows_for_ids(bundle: Any, row_ids: Sequence[str]) -> List[dict]:
    import pandas as pd

    wanted = {str(i) for i in row_ids}
    parsed = _get(bundle, "parsed_frame")
    frame = parsed if isinstance(parsed, pd.DataFrame) else pd.DataFrame(parsed) if parsed is not None else pd.DataFrame()
    if frame.empty:
        return [{"row_id": rid, "values": {}, "nome": rid} for rid in row_ids]
    id_col = "row_id" if "row_id" in frame.columns else None
    out: List[dict] = []
    seen = set()
    for idx, rec in frame.iterrows():
        rid = str(rec[id_col]) if id_col is not None else str(idx)
        if rid not in wanted:
            continue
        values = {str(k): rec[k] for k in rec.index if str(k) != "row_id"}
        out.append({"row_id": rid, "values": values, "nome": rid})
        seen.add(rid)
    for rid in row_ids:
        if str(rid) not in seen:
            out.append({"row_id": str(rid), "values": {}, "nome": str(rid)})
    return out


class _FoldPredictor:
    """C07 handle: predict(records) using the fold encoder, never the outer subject."""

    def __init__(self, winner_fit, prepared, spec, peers, seed, train_row_ids):
        self.status = "fitted" if _get(winner_fit, "status") in (None, "fitted") and winner_fit is not None else "error"
        self._fit = winner_fit
        self._prepared = prepared
        self._spec = spec
        self._peers = peers
        schema = _get(prepared, "feature_schema")
        encoder = _get(prepared, "encoder_state")
        spec_dict = _as_dict(_get(winner_fit, "candidate_spec")) or {}
        self.trace = {
            "used_row_ids": _row_ids(_get(prepared, "row_ids")),
            "selected_features": list(spec_dict.get("features") or []),
            "selected_base_variables": list(spec_dict.get("base_variables") or []),
            "encoder_state": _as_dict(encoder) or {},
            "impute_values": (_as_dict(encoder) or {}).get("impute_values") or {},
            "categories": {
                name: meta.get("categories")
                for name, meta in ((_as_dict(schema) or {}).get("columns") or {}).items()
                if isinstance(meta, Mapping)
            },
            "model_spec": spec_dict,
            "status": self.status,
            "seed": seed,
            "train_row_ids": list(train_row_ids) if train_row_ids is not None else None,
        }

    def predict(self, records):
        transform = self._peers.get("transform_subject")
        evaluate = self._peers.get("evaluate_fitted")
        schema = _get(self._prepared, "feature_schema")
        encoder = _get(self._prepared, "encoder_state")
        out = []
        for rec in records or []:
            raw = dict(rec) if isinstance(rec, Mapping) else {"value": rec}
            rid = raw.get("row_id")
            if not callable(transform) or not callable(evaluate) or self._fit is None:
                out.append({"row_id": rid, "value": None, "status": "error"})
                continue
            design = transform(raw, schema, encoder)
            assessment = evaluate(self._fit, design, self._spec)
            out.append({
                "row_id": rid,
                "value": _point_from(assessment),
                "status": "ok" if _point_from(assessment) is not None else "error",
            })
        return out


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
    winner_fit: Any = None,
) -> dict:
    """Data actually used/excluded plus the request dates. Does not refit."""
    sample_ledger = _as_dict(_get(prepared_dataset, "sample_ledger")) or {}
    ledger = _get(input_bundle, "row_ledger")
    row_ledger = list(ledger) if isinstance(ledger, (list, tuple)) else (_as_dict(ledger) or {})
    used_rows = _rows_for_ids(input_bundle, used_row_ids)
    excluded_rows = _rows_for_ids(input_bundle, excluded_row_ids)
    spec_dict = _as_dict(_get(winner_fit, "candidate_spec")) or {} if winner_fit is not None else {}
    y_name = spec_dict.get("y_transformation")
    if isinstance(y_name, Mapping):
        y_name = y_name.get("name")
    series = aligned_fit_series(
        winner_fit,
        used_row_ids=list(used_row_ids),
        target_unit=request_spec.get("target_unit"),
        y_transform_name=str(y_name) if y_name else None,
    ) if winner_fit is not None else {
        "fitted_values": None,
        "residuals": None,
        "observed_values": None,
        "series_row_ids": list(used_row_ids),
        "series_scale": None,
        "series_unit": request_spec.get("target_unit"),
        "available": False,
        "reason": "fit_unavailable",
    }
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
        "used_rows": used_rows,
        "excluded_rows": excluded_rows,
        "sample_ledger": sample_ledger,
        "row_ledger": row_ledger,
        "sources": {
            "input_sha256": _get(input_bundle, "input_sha256"),
            "dataset_sha256": _get(prepared_dataset, "dataset_sha256"),
        },
        "attachments": [],
        "fitted_values": series.get("fitted_values"),
        "residuals": series.get("residuals"),
        "observed_values": series.get("observed_values"),
        "series_row_ids": series.get("series_row_ids") or list(used_row_ids),
        "series_scale": series.get("series_scale"),
        "series_unit": series.get("series_unit"),
        "series_available": bool(series.get("available")),
        "series_reason": series.get("reason"),
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
    search_audit: Any = None,
    value: Any = None,
    value_policy: Any = None,
) -> dict:
    candidate_spec = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    feature_schema = _as_dict(_get(prepared_dataset, "feature_schema")) or _as_dict(
        _get(winner_fit, "feature_schema")
    ) or {}
    encoder_state = _as_dict(_get(prepared_dataset, "encoder_state")) or _as_dict(
        _get(winner_fit, "encoder_state")
    ) or {}
    residual_state = complete_residual_state_for_persist(winner_fit, subject_design)
    diagnostics = _as_dict(_get(winner_fit, "diagnostics")) or {}
    feature_order = list(
        residual_state.get("feature_order")
        or (_as_dict(_get(winner_fit, "model_state")) or {}).get("feature_order")
        or diagnostics.get("design_columns")
        or (_as_dict(_get(winner_fit, "coefficients")) or {}).keys()
    )
    model_state = {
        "coefficients": _as_dict(_get(winner_fit, "coefficients")) or {},
        "diagnostics": diagnostics,
        "target_transform_state": _as_dict(_get(winner_fit, "target_transform_state")) or {},
        "model_sha256": _get(winner_fit, "model_sha256"),
        "status": _get(winner_fit, "status"),
        "used_row_ids": list(_get(winner_fit, "used_row_ids") or _get(prepared_dataset, "row_ids") or []),
        "excluded_row_ids": list(_get(winner_fit, "excluded_row_ids") or []),
        "n": residual_state.get("n") or _get(winner_fit, "n") or diagnostics.get("n"),
        "k": residual_state.get("k") or _get(winner_fit, "k") or diagnostics.get("k"),
        "df_resid": residual_state.get("df_resid") or diagnostics.get("df_resid"),
        "feature_order": feature_order,
        "residual_std": residual_state.get("residual_std"),
        "residual_scale": residual_state.get("residual_scale"),
        "scale_convention": residual_state.get("scale_convention"),
        "xtx_inv": residual_state.get("xtx_inv"),
        "xtx_inv_kind": residual_state.get("xtx_inv_kind"),
        "has_intercept": residual_state.get("has_intercept") if residual_state.get("has_intercept") is not None else diagnostics.get("has_intercept"),
        "intercept_column": residual_state.get("intercept_column") or diagnostics.get("intercept_column"),
        "residual_state": residual_state,
        "calculation_version": CALCULATION_VERSION,
        "residual_state_complete": residual_state_is_complete(residual_state),
    }
    declared_scope = (
        (request_spec.get("search_policy") or {}).get("model_scope")
        or request_spec.get("model_scope")
    )
    audit = _as_dict(search_audit) or {}
    # Presence of a subject_design for prediction is not subject-conditioned
    # selection. Only an explicit subject_specific policy binds the freeze.
    # The actual conditioning flag is recorded separately from the scope label.
    if declared_scope == "subject_specific" or audit.get("selection_scope") == "subject_specific":
        model_scope = "subject_specific"
        raw = _as_dict(_get(subject_design, "raw_values")) or {}
        subject_constraints = {
            "selection_subject_id": _get(subject_design, "subject_id"),
            "bound_variables": dict(raw),
            "dropped_transforms": audit.get("dropped_transforms_due_to_subject") or {},
        }
    else:
        model_scope = "population_model"
        subject_constraints = {}
    selection_conditioned = audit.get("selection_conditioned_on_subject")
    if selection_conditioned is None:
        selection_conditioned = model_scope == "subject_specific"
    locale = str((_as_dict(request_spec.get("import_options")) or {}).get("locale") or "auto")
    axes = _axes_from_fit(
        winner_fit,
        prepared_dataset,
        _as_dict(_get(subject_design, "raw_values")) or None,
        locale=locale,
    )
    domain_variables: Dict[str, Any] = {}
    for axis in axes:
        name = str(axis.get("variable") or axis.get("name") or "")
        if not name:
            continue
        if axis.get("kind") == "categorical":
            allowed = list(axis.get("sample_values") or axis.get("categories") or [])
            if allowed:
                domain_variables[name] = {"allowed_categories": allowed}
        else:
            vmin = axis.get("sample_min")
            vmax = axis.get("sample_max")
            if vmin is not None and vmax is not None:
                domain_variables[name] = {"min": vmin, "max": vmax, "kind": "sample_used"}
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
        "model_scope": model_scope,
        "selection_conditioned_on_subject": bool(selection_conditioned),
        "subject_constraints": subject_constraints,
        "domain": {
            "kind": "sample_used",
            "target_col": request_spec.get("target_col"),
            "target_unit": request_spec.get("target_unit"),
            "reference_date": request_spec.get("reference_date"),
            "variables": domain_variables,
        },
        "sample_ledger": _as_dict(sample_ledger) or {},
        "normative_version": _get(normative, "edition"),
        "artifact_refs": dict(artifact_refs or {}),
        "provenance": {
            "code_sha": current_code_sha(),
            "composed_by": "c10.worker",
            "calculation_version": CALCULATION_VERSION,
        },
        "calculation_version": CALCULATION_VERSION,
        "residual_state": residual_state,
        "value": dict(value) if isinstance(value, Mapping) else None,
        "value_policy": dict(value_policy) if isinstance(value_policy, Mapping) else {},
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
        rows = row_ledger.get("rows")
        received = int(row_ledger.get("received") or (len(rows) if isinstance(rows, list) else 0))
        if "observed_target" in row_ledger and not isinstance(row_ledger.get("observed_target"), bool):
            try:
                observed = int(row_ledger.get("observed_target") or 0)
            except (TypeError, ValueError):
                observed = 0
        elif isinstance(rows, list):
            observed = sum(1 for entry in rows if isinstance(entry, Mapping) and entry.get("observed_target"))
    elif isinstance(row_ledger, (list, tuple)):
        received = len(row_ledger)
        observed = sum(
            1 for entry in row_ledger if isinstance(entry, Mapping) and entry.get("observed_target")
        )
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
        "observed_target": observed,
        "prepared": prepared_n,
        "used": len(used),
        "excluded": len(excluded),
        "used_row_ids": used,
        "excluded_row_ids": excluded,
    }


def _model_identity(winner_fit: Any, prepared: Any, assessment: Any) -> dict:
    """Compare CandidateFit (used) vs CandidateAssessment (delivered). Not a self-copy."""
    feature_schema = _as_dict(_get(winner_fit, "feature_schema")) or _as_dict(
        _get(prepared, "feature_schema")
    ) or {}
    spec = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    used_ids = _row_ids(_get(winner_fit, "used_row_ids") or _get(prepared, "row_ids"))
    delivered_ids = _row_ids(_get(assessment, "used_row_ids") or used_ids)
    used_coeffs = _json_coeffs(winner_fit)
    delivered_point = _point_from(assessment)
    used = {
        "candidate_id": _get(winner_fit, "candidate_id"),
        "model_sha256": _get(winner_fit, "model_sha256"),
        "used_row_ids": used_ids,
        "coefficient_names": sorted(used_coeffs),
        "y_transformation": spec.get("y_transformation"),
        "encoder_fingerprint": _encoder_fingerprint(_get(winner_fit, "encoder_state") or _get(prepared, "encoder_state")),
        "dataset_sha256": _get(prepared, "dataset_sha256"),
    }
    delivered = {
        "candidate_id": _get(assessment, "candidate_id") or _get(winner_fit, "candidate_id"),
        "model_sha256": _get(winner_fit, "model_sha256"),
        "used_row_ids": delivered_ids,
        "coefficient_names": sorted(used_coeffs),
        "y_transformation": spec.get("y_transformation"),
        "encoder_fingerprint": used["encoder_fingerprint"],
        "dataset_sha256": _get(prepared, "dataset_sha256"),
        "point_finite": delivered_point is not None,
    }
    match = (
        used["candidate_id"] == delivered["candidate_id"]
        and used["used_row_ids"] == delivered["used_row_ids"]
        and used["coefficient_names"] == delivered["coefficient_names"]
        and used["y_transformation"] == delivered["y_transformation"]
        and used["encoder_fingerprint"] == delivered["encoder_fingerprint"]
        and bool(used_coeffs)
    )
    return {
        "candidate_id": delivered["candidate_id"],
        "model_sha256": used["model_sha256"],
        "feature_schema_version": feature_schema.get("version"),
        "used_row_ids": used_ids,
        "transformations": spec.get("x_transformations") or {},
        "y_transformation": spec.get("y_transformation"),
        "coefficients": used_coeffs,
        "encoder_state_present": bool(used["encoder_fingerprint"]),
        "delivered_matches_used": match,
        "used": used,
        "delivered": {k: delivered[k] for k in delivered if k != "coefficient_names" or True},
    }


def _first_present(*values: Any) -> Any:
    """Return the first value that is not None. DataFrames are not bool-tested."""
    for value in values:
        if value is not None:
            return value
    return None


def _design_row_mapping(x_row: Any) -> Dict[str, Any]:
    """One JSON object of feature → scalar for the C12 dossier (never a DataFrame)."""
    if x_row is None:
        return {}
    if hasattr(x_row, "iloc"):
        try:
            x_row = x_row.iloc[0].to_dict()
        except Exception:
            return {}
    if not isinstance(x_row, Mapping):
        return {}
    out: Dict[str, Any] = {}
    for key, value in x_row.items():
        if isinstance(value, Mapping) and len(value) == 1:
            value = next(iter(value.values()))
        out[str(key)] = value
    return out


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        return len(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def _frame_columns(frame: Any) -> List[str]:
    if frame is None:
        return []
    columns = getattr(frame, "columns", None)
    if columns is not None:
        return [str(c) for c in list(columns)]
    if isinstance(frame, Mapping):
        return [str(k) for k in frame.keys()]
    return []


def _column_values(frame: Any, name: str) -> List[Any]:
    if frame is None:
        return []
    series = None
    try:
        if hasattr(frame, "columns") and name in list(frame.columns):
            series = frame[name]
        elif isinstance(frame, Mapping) and name in frame:
            series = frame[name]
    except Exception:
        return []
    if series is None:
        return []
    try:
        return list(series)
    except TypeError:
        return [series]


def _parse_subject_numeric(aval: Any, locale: str = "auto") -> Optional[float]:
    if aval is None or aval == "":
        return None
    if isinstance(aval, bool):
        return None
    if isinstance(aval, (int, float)):
        try:
            number = float(aval)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None
    try:
        from modules.variable_schema import parse_numeric

        parsed = parse_numeric(aval, locale=locale or "auto")
        if parsed is not None and math.isfinite(parsed):
            return float(parsed)
    except Exception:
        pass
    return None


def _axes_from_fit(
    winner_fit: Any,
    prepared: Any,
    subject_raw: Optional[Mapping[str, Any]],
    *,
    locale: str = "auto",
) -> List[dict]:
    """Item-4 axes from CandidateFit.base_frame (fallback: prepared.base_frame / X).

    Extra form fields that are not part of the fitted candidate do not create
    extrapolation axes for that model.
    """
    raw = dict(subject_raw or {})
    nested = _get(winner_fit, "candidate_fit")
    frame = _first_present(
        _get(winner_fit, "base_frame"),
        _get(nested, "base_frame") if nested is not None else None,
        _get(prepared, "base_frame"),
        _get(winner_fit, "X_design"),
        _get(prepared, "X"),
    )
    spec = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    names = [str(n) for n in (spec.get("base_variables") or [])]
    frame_cols = _frame_columns(frame)
    intercept_names = {"const", "intercept", "Intercept"}
    if not names:
        names = [str(n) for n in (spec.get("features") or [])]
    if not names:
        names = [c for c in frame_cols if c not in intercept_names]
    schema = _as_dict(_get(winner_fit, "feature_schema") or _get(prepared, "feature_schema")) or {}
    columns_meta = schema.get("columns") if isinstance(schema.get("columns"), Mapping) else {}
    groups = schema.get("groups") if isinstance(schema.get("groups"), Mapping) else {}
    axes: List[dict] = []
    seen = set()
    for name in names:
        if name in seen or name in intercept_names:
            continue
        seen.add(name)
        values = _column_values(frame, name)
        if not values:
            group = groups.get(name) if isinstance(groups, Mapping) else None
            if isinstance(group, Mapping):
                values = _column_values(frame, str(group.get("base_variable") or name))
        meta = columns_meta.get(name) if isinstance(columns_meta, Mapping) else None
        kind_hint = str((meta or {}).get("kind") or "").lower()
        nums: List[float] = []
        others: List[Any] = []
        for item in values:
            try:
                number = float(item)
            except (TypeError, ValueError):
                if item is not None and str(item) != "":
                    others.append(item)
                continue
            if math.isfinite(number):
                nums.append(number)
            else:
                others.append(item)
        qualitative = kind_hint in {"categorical", "qualitative", "dummy", "indicator"} or (
            others and not nums
        )
        if qualitative:
            sample_values = []
            observed_counts: Dict[str, int] = {}
            for item in values:
                if item is None:
                    continue
                text = str(item)
                if text and text not in sample_values:
                    sample_values.append(text)
                if text:
                    observed_counts[text] = observed_counts.get(text, 0) + 1
            aval = raw.get(name)
            axes.append(
                {
                    "name": name,
                    "variable": name,
                    "kind": "categorical",
                    "avaliando_value": aval,
                    "sample_values": sample_values,
                    "categories": sample_values,
                    "category_counts": observed_counts,
                }
            )
            continue
        if not nums:
            continue
        aval = raw.get(name)
        aval_f = _parse_subject_numeric(aval, locale=locale)
        axes.append(
            {
                "name": name,
                "variable": name,
                "kind": "quantitative",
                "avaliando_value": aval_f if aval_f is not None else aval,
                "sample_min": min(nums),
                "sample_max": max(nums),
                "n": len(nums),
            }
        )
    return axes


def _pvalues_from_fit(winner_fit: Any) -> Dict[str, Any]:
    records = _get(winner_fit, "coefficient_records") or []
    pvalues: Dict[str, Any] = {}
    if isinstance(records, list):
        for rec in records:
            if isinstance(rec, Mapping) and rec.get("name") is not None:
                pvalues[str(rec["name"])] = rec.get("pvalue")
    if pvalues:
        return pvalues
    diagnostics = _as_dict(_get(winner_fit, "diagnostics")) or {}
    nested = diagnostics.get("pvalues")
    if isinstance(nested, Mapping):
        return {str(k): v for k, v in nested.items()}
    return pvalues


def _documentary_from_spec(spec: Mapping[str, Any]) -> dict:
    """Map RequestSpec.declared_documentary onto the C05/legacy documentary shape.

    Canonical RequestSpec keys are item1_grade / item3_grade plus optional
    nested item1/item3 provenance. assess_normative reads itemN.grade and
    itemN.provenance (or grau_itemN / itemN_provenance on the context).
    """
    raw = spec.get("declared_documentary") if isinstance(spec.get("declared_documentary"), Mapping) else None
    if raw is None and isinstance(spec.get("documentary"), Mapping):
        raw = spec.get("documentary")
    if raw is None:
        evaluation = spec.get("evaluation_policy")
        if isinstance(evaluation, Mapping) and isinstance(evaluation.get("documentary"), Mapping):
            raw = evaluation.get("documentary")
    if not isinstance(raw, Mapping):
        return {}
    out = dict(raw)
    for item, grade_key, prov_key in (
        (1, "item1_grade", "item1_provenance"),
        (3, "item3_grade", "item3_provenance"),
    ):
        nested_key = f"item{item}"
        nested = dict(out.get(nested_key) or {}) if isinstance(out.get(nested_key), Mapping) else {}
        if out.get(grade_key) is not None and nested.get("grade") is None:
            nested["grade"] = out.get(grade_key)
        if out.get(prov_key) is not None and not nested.get("provenance"):
            nested["provenance"] = out.get(prov_key)
        if nested:
            out[nested_key] = nested
    return out


def _declared_item_grade(spec: Mapping[str, Any], item: int) -> Any:
    doc = _documentary_from_spec(spec)
    nested = doc.get(f"item{item}") if isinstance(doc.get(f"item{item}"), Mapping) else {}
    if nested.get("grade") is not None:
        return nested.get("grade")
    return doc.get(f"item{item}_grade")


def _declared_item_provenance(spec: Mapping[str, Any], item: int) -> Any:
    doc = _documentary_from_spec(spec)
    nested = doc.get(f"item{item}") if isinstance(doc.get(f"item{item}"), Mapping) else {}
    if nested.get("provenance") is not None:
        return nested.get("provenance")
    return doc.get(f"item{item}_provenance")


def _normative_context_from_fit(
    winner_fit: Any,
    prepared: Any,
    assessment: Any,
    spec: Mapping[str, Any],
    subject_raw: Optional[Mapping[str, Any]],
    predict_original: Callable[[Any], Any],
    numeric_disclosure: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a C03 context from the live CandidateFit + prepared sample.

    Nested search-record `assessment.normative` is not a substitute: it may
    lack axes, integer n/k, p-values and a `{point}` predict_original.
    """
    diagnostics = _as_dict(_get(winner_fit, "diagnostics")) or {}
    used_ids = _row_ids(_get(winner_fit, "used_row_ids") or _get(prepared, "row_ids"))
    n = _int_or_none(diagnostics.get("n"))
    if n is None:
        n = len(used_ids)
    k = _int_or_none(diagnostics.get("k"))
    intercept = diagnostics.get("has_intercept")
    spec_c = _as_dict(_get(winner_fit, "candidate_spec")) or {}
    if intercept is None:
        intercept = spec_c.get("intercept")
    if k is None:
        cols = diagnostics.get("design_columns") or _frame_columns(
            _first_present(_get(winner_fit, "X_design"), _get(prepared, "X"))
        )
        if cols:
            intercept_cols = [c for c in cols if str(c).lower() in {"const", "intercept"}]
            drop = 1 if intercept or intercept_cols else 0
            k = max(0, len(cols) - drop)
        else:
            coeffs = _json_coeffs(winner_fit)
            drop = 1 if intercept or "const" in coeffs else 0
            k = max(0, len(coeffs) - drop) if coeffs else None
    locale = str((_as_dict(spec.get("import_options")) or {}).get("locale") or "auto")
    axes = _axes_from_fit(winner_fit, prepared, subject_raw, locale=locale)
    value_block = _as_dict(_get(assessment, "value")) or {}
    nested_norm = _as_dict(_get(assessment, "normative")) or {}
    precisao = nested_norm.get("precisao") if isinstance(nested_norm.get("precisao"), Mapping) else {}
    amplitude = precisao.get("amplitude_pct") if isinstance(precisao, Mapping) else None
    if amplitude is None and value_block.get("point") and isinstance(value_block.get("mean_ci80"), Mapping):
        point = _point_from(value_block)
        bounds = value_block.get("mean_ci80") or {}
        try:
            width = abs(float(bounds.get("upper")) - float(bounds.get("lower")))
            if point not in (0, None) and math.isfinite(point):
                amplitude = width / abs(point) * 100.0
        except (TypeError, ValueError):
            amplitude = None
    statistical = _as_dict(_get(assessment, "statistical")) or {}
    statistical = dict(statistical)
    numeric_statistical = _as_dict(
        _get(numeric_disclosure, "normative_statistical")
    ) or {}
    for key, value in numeric_statistical.items():
        if value is not None:
            statistical[key] = value
    statistical.setdefault("n", n)
    statistical.setdefault("k", k)
    statistical.setdefault("automatic_selection", False)
    declared_category_counts = spec.get("category_counts")
    if isinstance(declared_category_counts, Mapping):
        category_counts = dict(declared_category_counts)
    else:
        category_counts = {
            f"{axis.get('name')}={category}": count
            for axis in axes
            if axis.get("kind") == "categorical"
            for category, count in dict(axis.get("category_counts") or {}).items()
        }
    return {
        "n": n,
        "k": k,
        "intercept": intercept,
        "sample": {"used": used_ids, "n": n, "k": k},
        "X": _first_present(_get(winner_fit, "X_design"), _get(prepared, "X")),
        "y": _first_present(_get(winner_fit, "y_design"), _get(prepared, "y")),
        "subject_raw": subject_raw,
        "predict_original": predict_original,
        "pvalues": _pvalues_from_fit(winner_fit),
        "f_pvalue": diagnostics.get("f_pvalue"),
        "amplitude_pct": amplitude,
        "value": value_block,
        "mean_ci80": value_block.get("mean_ci80") if isinstance(value_block, Mapping) else None,
        "prediction_interval": value_block.get("prediction_interval") if isinstance(value_block, Mapping) else None,
        "central_estimate": _point_from(assessment),
        "axes": axes,
        "extrapolation_details": axes,
        "documentary": _documentary_from_spec(spec),
        "grau_item1": _declared_item_grade(spec, 1),
        "grau_item3": _declared_item_grade(spec, 3),
        "item1_provenance": _declared_item_provenance(spec, 1),
        "item3_provenance": _declared_item_provenance(spec, 3),
        "diagnostics": dict(spec.get("normative_diagnostics") or {}),
        "professional_findings": dict(spec.get("professional_findings") or {}),
        "category_counts": category_counts,
        "request_spec": spec,
        "used_row_ids": used_ids,
        "statistical": statistical,
        "estimand": value_block.get("estimand") or _get(assessment, "estimand"),
        "feature_names": diagnostics.get("design_columns"),
    }


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
    # model training. Subject is echoed, not scored. Column profile is
    # observed categories from parsed_frame, not a fitted encoder.
    profile = _preview_column_profile(bundle, request_spec)
    sample_counts = _sample_from_prepared(bundle, None, [], [])
    return {
        "schema_version": SCHEMA_VERSION,
        "preview": True,
        "input_sha256": _get(bundle, "input_sha256") or sha256_bytes(file_bytes),
        "filename": filename,
        "column_map": _as_dict(_get(bundle, "column_map")) or {},
        "feature_schema": profile["feature_schema"],
        "row_ledger": profile["row_ledger"],
        "sample_preview": profile["sample_preview"],
        "roles_applied": dict(request_spec.get("roles") or {}),
        "target_col": request_spec.get("target_col"),
        "candidate_cols": request_spec.get("candidate_cols"),
        "issues": issues,
        "sample": {
            "received": sample_counts.get("received", 0),
            "observed_target": sample_counts.get("observed_target", 0),
        },
        "subject_received": dict(subject_raw) if isinstance(subject_raw, Mapping) else None,
        "search_invoked": False,
        "fit_invoked": False,
        "project_mutated": False,
    }


def _compose_cost_valuation_job(
    *, context: Dict[str, Any], emit: Callable[[str, Optional[float]], None],
    spec: Mapping[str, Any], file_bytes: bytes, filename: str,
    subject_raw: Optional[Mapping[str, Any]], project_id: Optional[str],
    peers: Mapping[str, Any], job_store: Any, output_dir: Optional[str],
) -> dict:
    """Compose the cost method without parsing/fitting a market sample."""
    from modules.cost_valuation import compute_reconstruction_cost
    from modules.valuation_policy.qualification import compose_qualification_context, map_issuance_status

    emit(STAGE_NORMATIVE, None)
    bom = spec.get("cost_bom")
    cost_result = compute_reconstruction_cost(
        bom,
        value_basis="depreciated_cost",
        include_depreciation=True,
    )
    issues = list(cost_result.get("issues") or [])
    if isinstance(bom, Mapping):
        if spec.get("reference_date") != bom.get("reference_date"):
            issues.append(make_issue(
                "COST_REFERENCE_DATE_CONFLICT",
                "RequestSpec.reference_date e cost_bom.reference_date devem coincidir; atualização implícita é proibida.",
                origin="c06.worker",
                evidence={"request_reference_date": spec.get("reference_date"), "cost_reference_date": bom.get("reference_date")},
            ))
        if spec.get("target_unit") != bom.get("currency"):
            issues.append(make_issue(
                "COST_CURRENCY_CONFLICT",
                "RequestSpec.target_unit e cost_bom.currency devem coincidir; conversão implícita é proibida.",
                origin="c06.worker",
                evidence={"target_unit": spec.get("target_unit"), "cost_currency": bom.get("currency")},
            ))
    if any(item.get("severity") == "error" for item in issues):
        cost_result = dict(cost_result)
        cost_result["computable"] = False
        cost_result["reason"] = issues[0].get("code") if issues else "cost_not_computable"
        cost_result["issues"] = issues
        cost_result["value"] = dict(cost_result.get("value") or {})
        cost_result["value"]["point"] = None

    normative = {
        "schema_version": "MP-NORMATIVE-COST/1",
        "edition": "ABNT NBR 14653-2:2011",
        "verification_status": "case_cost_evidence_assessed_profile_currency_unconfirmed",
        "fundamentacao": dict(cost_result.get("fundamentacao") or {}),
        "precisao": {"status": "not_computed", "grade": None, "reason": "not_applicable_to_cost_quantification"},
        "documentary": {"status": "derived_from_cost_memory", "verified": False},
        "issues": [],
    }
    value = empty_value_block()
    cost_value = dict(cost_result.get("value") or {})
    for key in value:
        value[key] = cost_value.get(key)
    value["basis"] = "depreciated_cost"
    model = {
        "candidate_id": "cost-quantification",
        "status": "fitted" if cost_result.get("computable") else "rejected",
        "method": "metodo_quantificacao_de_custo",
        "coefficients": {},
        "formula": None,
    }
    input_sha = sha256_bytes(dumps_strict(bom or {}).encode("utf-8"))
    validation = _map_validation(normative, {})
    validation["fundamentacao"] = dict(cost_result.get("fundamentacao") or {})
    validation["statistical"] = {
        "route": "cost_quantification",
        "market_sample_applicable": False,
        "precision_grade_applicable": False,
    }
    draft = {
        "schema_version": SCHEMA_VERSION,
        "job_id": context["job_id"],
        "project_id": project_id,
        "input_sha256": input_sha,
        "code_sha": current_code_sha(),
        "reference_date": spec.get("reference_date"),
        "generated_at": _utc_now_iso(),
        "target": {"column": "", "unit": spec.get("target_unit") or "", "estimand": "depreciated_reconstruction_cost"},
        "value": value,
        "sample": {"received": 0, "observed_target": 0, "prepared": 0, "used": 0, "excluded": 0,
                   "used_row_ids": [], "excluded_row_ids": []},
        "validation": validation,
        "issues": issues,
        "model": model,
        "search": {"audit": {"route": "cost_quantification", "search_invoked": False}, "winner_candidate_id": "cost-quantification"},
        "alternatives": [],
        "next_actions": [],
        "provenance": {
            "filename": filename or "cost-bom.json",
            "composed_by": "c06.worker.cost",
            "peers": {},
            "sample_ledger_present": False,
            "subject_categorical_survived": False,
            "calculation_version": CALCULATION_VERSION,
            "normative_assessment": normative,
            "cost_result": cost_result,
            "market_sample_not_required": True,
            "market_value_not_used_as_cost": True,
            "workflow_context": build_workflow_context(
                request_spec=spec, subject_raw=subject_raw, validation=validation,
                search_audit={"route": "cost_quantification", "search_invoked": False},
                limitation_codes=[item.get("code") for item in issues], issues=issues,
            ),
        },
    }
    qc = compose_qualification_context(
        request_spec=spec, snapshot_draft=draft,
        winner={"status": "fitted"} if cost_result.get("computable") else None,
        search_audit=draft["search"]["audit"], issues=issues,
        review_events=list(spec.get("review_events") or []), cost_result=cost_result,
        normative_assessment=normative,
    )
    draft["provenance"]["qualification_context"] = qc
    issuance = dict(validation.get("issuance") or {})
    issuance["status"] = map_issuance_status(qc.get("case_release_status"))
    issuance["case_release_status"] = qc.get("case_release_status")
    issuance["reasons"] = list(dict.fromkeys(list(issuance.get("reasons") or []) + (["not_qualified_emission"] if qc.get("case_release_status") == "analysis_only" else [])))
    draft["validation"]["issuance"] = issuance
    emit(STAGE_FREEZE, None)
    try:
        snapshot = freeze_result_snapshot(draft)
    except ResultSnapshotError as exc:
        raise CompositionError("freeze_result_snapshot failed", exc.issues) from exc
    if job_store is not None:
        job_store.save_snapshot(context["job_id"], snapshot)

    sources = []
    if isinstance(bom, Mapping):
        direct = bom.get("direct_cost")
        if isinstance(direct, Mapping) and direct.get("source"):
            sources.append(direct.get("source"))
        for item in cost_result.get("items") or []:
            if item.get("source") and item.get("source") not in sources:
                sources.append(item.get("source"))
    report_context = complete_report_context(
        {
            "cost_memory": cost_result.get("memory"),
            "cost_items": cost_result.get("items"),
            "cost_fundamentacao": cost_result.get("fundamentacao"),
            "sources": sources,
            "used_rows": [], "excluded_rows": [],
            "methodology_justification": "Método da quantificação de custo; memória MP-COST/1 sem fator de mercado.",
        },
        request_spec=spec, subject_raw=subject_raw, snapshot=snapshot,
    )
    artifact_refs: Dict[str, Any] = {}
    for artifact_name, artifact_value in (("normative_assessment.json", normative), ("report_context.json", report_context)):
        payload = dumps_strict(artifact_value).encode("utf-8")
        context["artifact_bytes"][artifact_name] = payload
        context["artifact_states"][artifact_name] = {"state": "ready", "error": None}
        artifact_refs[artifact_name] = {"sha256": sha256_bytes(payload)}
        _save_artifact(job_store, context["job_id"], artifact_name, payload)

    emit(STAGE_REPORT, None)
    render = peers.get("render_report")
    if callable(render):
        try:
            pdf = render(snapshot, report_context)
            if not isinstance(pdf, (bytes, bytearray)) or not pdf:
                raise ValueError("render_report returned no bytes")
            payload = bytes(pdf)
            context["artifact_bytes"]["report.pdf"] = payload
            context["artifact_states"]["report.pdf"] = {"state": "ready", "error": None}
            artifact_refs["report.pdf"] = {"sha256": sha256_bytes(payload)}
            _save_artifact(job_store, context["job_id"], "report.pdf", payload)
        except Exception as exc:
            context["artifact_states"]["report.pdf"] = {"state": "failed", "error": make_issue("PDF_FAILED", f"render_report failed: {exc}", origin="c06.worker.cost")}
    else:
        context["artifact_states"]["report.pdf"] = {"state": "failed", "error": make_issue("PEER_UNAVAILABLE", "render_report unavailable", severity="warning", origin="c06.worker.cost")}

    emit(STAGE_EVIDENCE, None)
    evidence_files = {
        "snapshot/result_snapshot.json": dumps_strict(snapshot).encode("utf-8"),
        "calculation/cost_bom.json": dumps_strict(bom or {}).encode("utf-8"),
        "calculation/cost_result.json": dumps_strict(cost_result).encode("utf-8"),
        "documents/report_context.json": dumps_strict(report_context).encode("utf-8"),
        "metadata/request_spec.json": dumps_strict(request_spec_for_peers(spec)).encode("utf-8"),
        "qualification/context.json": dumps_strict(qc).encode("utf-8"),
        # The C12 package contract keeps these neutral paths across methods.
        # Empty CSVs truthfully record that no market sample exists; the
        # effective cost inputs live in calculation/cost_bom.json instead.
        "data/source_input.bin": dumps_strict(bom or {}).encode("utf-8"),
        "data/original_base.csv": b"row_id\r\n",
        "data/interpreted_base.csv": b"row_id\r\n",
        "data/used_sample.csv": b"row_id\r\n",
        "data/excluded_rows.csv": b"row_id\r\n",
        "data/identifier_map.json": dumps_strict({"applicability": "not_applicable_cost_quantification"}).encode("utf-8"),
        "data/representation_map.json": dumps_strict({
            "schema_version": "MP-EVIDENCE-MAP/1",
            "market_sample": "not_applicable_cost_quantification",
            "cost_input": "calculation/cost_bom.json",
            "normalized_cost_result": "calculation/cost_result.json",
            "row_identity": "item_id",
        }).encode("utf-8"),
        "model/coefficients.json": dumps_strict({"values": {}, "applicability": "not_applicable_cost_quantification"}).encode("utf-8"),
        "model/subject_design.json": dumps_strict({"applicability": "not_applicable_cost_quantification"}).encode("utf-8"),
        "model/transformations.json": dumps_strict({"applicability": "not_applicable_cost_quantification"}).encode("utf-8"),
        "model/residual_context.json": dumps_strict({"applicability": "not_applicable_cost_quantification"}).encode("utf-8"),
        "policies/request_spec.json": dumps_strict(request_spec_for_peers(spec)).encode("utf-8"),
        "policies/missing_policy.json": dumps_strict(spec.get("missing_policy") or {}).encode("utf-8"),
        "policies/outlier_policy.json": dumps_strict(spec.get("outlier_policy") or {}).encode("utf-8"),
        "policies/search_policy.json": dumps_strict(spec.get("search_policy") or {}).encode("utf-8"),
        "policies/evaluation_policy.json": dumps_strict(spec.get("evaluation_policy") or {}).encode("utf-8"),
        "policies/value_policy.json": dumps_strict(spec.get("value_policy") or {
            "applicability": "cost_result_is_directly_calculated",
        }).encode("utf-8"),
        "reproduction/spec.json": dumps_strict({
            "schema_version": "MP-COST-REPRODUCTION/1",
            "promised": True,
            "method": "validated_cost_bom_sum",
            "input": "calculation/cost_bom.json",
            "result": "calculation/cost_result.json",
            "expected_point": snapshot.get("value", {}).get("point"),
            "formula": (cost_result.get("memory") or {}).get("formula"),
            "market_sample": "not_applicable",
        }).encode("utf-8"),
    }
    if context["artifact_bytes"].get("report.pdf"):
        evidence_files["documents/report.pdf"] = context["artifact_bytes"]["report.pdf"]
    ledger = {
        "schema_version": "MP-COMPLETENESS/1",
        "items": [
            {"component": "cost_input", "status": "verified", "declared": True, "source": "calculation/cost_bom.json", "notes": "BOM integral identificado por hash.", "evidence": {}},
            {"component": "cost_calculation", "status": "verified", "declared": True, "source": "calculation/cost_result.json", "notes": "Memória reproduz o point do snapshot.", "evidence": {}},
            {"component": "frozen_snapshot", "status": "verified", "declared": True, "source": "snapshot.schema_version", "notes": "Snapshot MP/1.", "evidence": {}},
            {"component": "qualification_context", "status": "present", "declared": True, "source": "snapshot.provenance.qualification_context", "notes": "", "evidence": {}},
            {"component": "report_artifact", "status": "present", "declared": True, "source": "artifacts.report_pdf", "notes": "", "evidence": {}},
            {"component": "docx_artifact", "status": "missing", "declared": False, "source": "", "notes": "Gerado na passagem documental.", "evidence": {}},
            {"component": "review_history", "status": "missing", "declared": False, "source": "", "notes": "Ato humano ainda não realizado.", "evidence": {}},
            {"component": "signature_record", "status": "missing", "declared": False, "source": "", "notes": "Assinatura ainda não importada.", "evidence": {}},
            {"component": "photos_documents", "status": "missing", "declared": False, "source": "", "notes": "Anexos documentais ainda não fornecidos.", "evidence": {}},
        ],
    }
    ledger["missing"] = [item["component"] for item in ledger["items"] if item["status"] == "missing"]
    ledger["counts"] = {status: sum(item["status"] == status for item in ledger["items"])
                        for status in ("declared", "missing", "present", "verified")}
    evidence_files["completeness/ledger.json"] = dumps_strict(ledger).encode("utf-8")
    media = {
        ".json": "application/json", ".pdf": "application/pdf",
    }
    evidence_manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_version": "C12/1",
        "input_id": snapshot.get("input_sha256"),
        "code_id": snapshot.get("code_sha"),
        "snapshot_sha256": sha256_bytes(evidence_files["snapshot/result_snapshot.json"]),
        "job_id": snapshot.get("job_id"),
        "project_id": snapshot.get("project_id"),
        "cost_evidence_schema": "MP-COST-EVIDENCE/1",
        "result_fingerprint": qc.get("result_fingerprint"),
        "calculation_schema": cost_result.get("schema_version"),
        "completeness_status": "incomplete",
        "completeness_missing": ledger["missing"],
        "completeness_summary": ledger["counts"],
        "numerical_reproduction_status": "ready",
        "replay": {
            "formula": (cost_result.get("memory") or {}).get("formula"),
            "point": snapshot.get("value", {}).get("point"),
            "automatic_currency_or_date_adjustment": False,
        },
        "files": [
            {"path": name, "sha256": sha256_bytes(payload), "size": len(payload),
             "type": media.get(os.path.splitext(name)[1], "application/octet-stream"),
             "version": "MP-COST/1", "function": "cost_evidence_" + name.replace("/", "_")}
            for name, payload in sorted(evidence_files.items())
        ],
    }
    manifest_payload = dumps_strict(evidence_manifest).encode("utf-8")
    evidence_files["MANIFEST.json"] = manifest_payload
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in sorted(evidence_files.items()):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, payload)
    bundle_payload = archive.getvalue()
    for artifact_name, payload in (("evidence_manifest.json", manifest_payload), ("evidence_bundle.zip", bundle_payload)):
        context["artifact_bytes"][artifact_name] = payload
        context["artifact_states"][artifact_name] = {"state": "ready", "error": None}
        artifact_refs[artifact_name] = {"sha256": sha256_bytes(payload)}
        _save_artifact(job_store, context["job_id"], artifact_name, payload)

    frozen_project = {
        "schema_version": SCHEMA_VERSION, "project_id": project_id, "revision_id": None,
        "input_sha256": input_sha, "dataset_sha256": None,
        "request_spec": request_spec_for_peers(spec), "feature_schema": {}, "encoder_state": {},
        "model_spec": {"method": "metodo_quantificacao_de_custo"},
        "model_state": {"status": model["status"], "cost_result": cost_result},
        "model_scope": "cost_inputs", "selection_conditioned_on_subject": False,
        "subject_constraints": {}, "domain": {"kind": "cost_inputs", "target_col": "", "target_unit": spec.get("target_unit"), "reference_date": spec.get("reference_date"), "variables": {}},
        "sample_ledger": {}, "normative_version": normative["edition"], "artifact_refs": artifact_refs,
        "provenance": {"code_sha": current_code_sha(), "composed_by": "c06.worker.cost", "calculation_version": CALCULATION_VERSION},
        "calculation_version": CALCULATION_VERSION, "residual_state": {}, "value": snapshot.get("value"),
    }
    frozen_payload = dumps_strict(frozen_project).encode("utf-8")
    context["artifact_bytes"]["frozen_project.json"] = frozen_payload
    context["artifact_states"]["frozen_project.json"] = {"state": "ready", "error": None}
    _save_artifact(job_store, context["job_id"], "frozen_project.json", frozen_payload)
    emit(STAGE_PERSIST, None)
    patch = {"stage": STAGE_PERSIST, "progress": context["progress"], "result_available": True,
             "artifact_states": context["artifact_states"], "calculation_state": "succeeded", "issues": list(snapshot.get("issues") or [])}
    if job_store is not None:
        for old in ("running", "queued"):
            try:
                job_store.update_transition(context["job_id"], old, "succeeded", patch=patch); break
            except Exception:
                continue
    context.update({"snapshot": snapshot, "frozen_project": frozen_project,
                    "report_context": report_context, "calculation_state": "succeeded"})
    return context


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
            "normative_assessment.json": {"state": "pending", "error": None},
            "report_context.json": {"state": "pending", "error": None},
            "report.pdf": {"state": "pending", "error": None},
            "evidence_manifest.json": {"state": "pending", "error": None},
            "frozen_project.json": {"state": "pending", "error": None},
            "evidence_bundle.zip": {"state": "pending", "error": None},
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
    profile_wire = spec.get("qualification_profile") if isinstance(spec.get("qualification_profile"), Mapping) else {}
    is_cost_route = bool(
        profile_wire.get("method") == "metodo_quantificacao_de_custo"
        and profile_wire.get("value_basis") == "custo_de_reedicao"
    )
    if is_cost_route:
        return _compose_cost_valuation_job(
            context=context,
            emit=emit,
            spec=spec,
            file_bytes=file_bytes,
            filename=filename,
            subject_raw=context.get("subject_raw"),
            project_id=project_id,
            peers=peers,
            job_store=job_store,
            output_dir=output_dir,
        )
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
        for alt in _get(search_result, "alternatives") or []:
            adm = _as_dict(_get(alt, "admissibility")) or {}
            if adm.get("numeric_technical") or _get(alt, "status") == "fitted":
                winner = alt
                search_issues.append(
                    make_issue(
                        "WINNER_PROMOTED_FROM_NUMERIC_ALTERNATIVE",
                        "Fitted numeric alternative promoted; grade/framing is not a NO_WINNER gate.",
                        severity="warning",
                        origin="c10.worker",
                    )
                )
                break
    if winner is None:
        raise CompositionError(
            "search_models returned no winner",
            search_issues + [make_issue("NO_WINNER", "search_models returned no winner", origin="c10.worker")],
        )

    winner_fit = _get(winner, "candidate_fit") or winner
    assessment = winner
    if callable(peers.get("evaluate_fitted")) and subject_design is not None:
        emit(STAGE_EVALUATE, None)
        assessment = peers["evaluate_fitted"](winner_fit, subject_design, spec)
        eval_issues = _issue_list(assessment)
        if _has_error_issues(eval_issues):
            raise CompositionError("evaluate_fitted failed", eval_issues)

    def predict_original(subject_next):
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
        result = evaluate(winner_fit, design, spec)
        return {"point": _point_from(result)}

    numeric_disclosure = build_numeric_disclosure(
        winner_fit,
        prepared,
        subject_raw=context.get("subject_raw"),
        predict_original=predict_original,
    )

    emit(STAGE_NORMATIVE, None)
    # Always feed C03 from the live CandidateFit + prepared sample. Nested
    # assessment.normative from a partial search record is not sufficient.
    if callable(peers.get("assess_normative")):
        normative = peers["assess_normative"](
            _normative_context_from_fit(
                winner_fit,
                prepared,
                assessment,
                spec,
                context.get("subject_raw"),
                predict_original,
                numeric_disclosure,
            )
        )
    else:
        normative = _get(assessment, "normative")
    normative_issues = _issue_list(normative)
    if _has_error_issues(normative_issues):
        raise CompositionError("assess_normative failed", normative_issues)

    procedure = None
    if is_evaluation_requested(spec) and callable(peers.get("evaluate_procedure")):
        emit(STAGE_PROCEDURE, None)

        def fit_select_predictor(train_row_ids, seed):
            prepared_fold = peers["fit_dataset"](bundle, spec, train_row_ids)
            # Do not reuse the outer subject_design; the fold encoder is the source.
            fold_search = peers["search_models"](
                prepared_fold, None, spec, None, cancel_requested
            )
            fold_winner = _get(fold_search, "winner")
            fold_fit = _get(fold_winner, "candidate_fit") or fold_winner
            return _FoldPredictor(fold_fit, prepared_fold, spec, peers, seed, train_row_ids)

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
        winner_fit=winner_fit,
    )
    report_context = complete_report_context(
        report_context,
        request_spec=spec,
        subject_raw=context.get("subject_raw"),
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
    value_policy_used = _as_dict(_get(assessment, "value_policy")) or {}
    # Map normativa/estatística; do not recompute classifications.
    mapped_validation = _map_validation(
        normative,
        assessment,
        procedure,
        numeric_disclosure=numeric_disclosure,
    )

    profile = spec.get("qualification_profile") if isinstance(spec.get("qualification_profile"), Mapping) else {}
    value_basis = str((profile or {}).get("value_basis") or "market")
    cost_result = None
    market_value_block = dict(value_block)
    cost_basis_map = {
        "reconstruction_cost": "reconstruction_cost",
        "replacement_cost": "replacement_cost",
        "depreciated_cost": "depreciated_cost",
        "custo_de_reedicao": "depreciated_cost",
    }
    if value_basis in cost_basis_map:
        from modules.cost_valuation import compute_reconstruction_cost

        cost_result = compute_reconstruction_cost(
            spec.get("cost_bom"),
            market_point=market_value_block.get("point"),
            value_basis=cost_basis_map[value_basis],
            include_depreciation=cost_basis_map[value_basis] == "depreciated_cost",
        )
        snapshot_issues.extend(list(cost_result.get("issues") or []))
        cost_value = dict(cost_result.get("value") or {})
        value_block = empty_value_block()
        for key in empty_value_block():
            value_block[key] = cost_value.get(key)
        value_block["basis"] = cost_value.get("basis") or value_basis
        value_block["estimand"] = cost_value.get("estimand") or "reconstruction_cost_sum"
        if not cost_result.get("computable"):
            value_block["point"] = None
    else:
        value_block.setdefault("basis", "market")

    model_block = _model_identity(winner_fit, prepared, assessment)
    formula = formula_from_coefficients(
        model_block.get("coefficients") or {},
        list(((_as_dict(_get(winner_fit, "diagnostics")) or {}).get("design_columns"))
             or (model_block.get("coefficients") or {}).keys()),
        target_name=str(spec.get("target_col") or "y"),
    )
    if formula:
        model_block["formula"] = formula
    diagnostics_fit = _as_dict(_get(winner_fit, "diagnostics")) or {}
    if diagnostics_fit:
        model_block["diagnostics"] = diagnostics_fit
    model_block.update(_as_dict(numeric_disclosure.get("model")) or {})
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
            "calculation_version": CALCULATION_VERSION,
            # Persist the single normative authority so document/review routes
            # can perform the second MP-QUAL/1 pass without reconstructing a
            # grade from presentation fields.
            "normative_assessment": _as_dict(normative) or {},
            "workflow_context": build_workflow_context(
                request_spec=spec,
                subject_raw=context.get("subject_raw"),
                validation=mapped_validation,
                search_audit=search_audit,
                limitation_codes=list((_as_dict(_get(assessment, "statistical")) or {}).get("limitations") or []),
                issues=snapshot_issues,
            ),
        },
    }
    # Restore estimand only on target, not inside value (value shape is exact).
    if "estimand" in value_block and "estimand" in draft["value"]:
        draft["value"] = {k: v for k, v in draft["value"].items() if k != "estimand"}
        draft["target"]["estimand"] = value_block.get("estimand") or draft["target"].get("estimand")

    from modules.valuation_policy.qualification import (
        compose_qualification_context,
        map_issuance_status,
    )

    qc = compose_qualification_context(
        request_spec=spec,
        snapshot_draft=draft,
        winner=_as_dict(winner) if winner is not None else None,
        search_audit=search_audit,
        issues=snapshot_issues,
        review_events=list(spec.get("review_events") or context.get("review_events") or []),
        cost_result=cost_result,
        previous_fingerprint=context.get("previous_fingerprint") or spec.get("previous_fingerprint"),
        normative_assessment=_as_dict(normative) or {},
    )
    draft.setdefault("provenance", {})
    draft["provenance"]["qualification_context"] = qc
    if value_basis in cost_basis_map:
        draft["provenance"]["market_value_not_used_as_cost"] = market_value_block
    issuance = dict((draft.get("validation") or {}).get("issuance") or {})
    issuance["status"] = map_issuance_status(qc.get("case_release_status"))
    issuance["case_release_status"] = qc.get("case_release_status")
    reasons = list(issuance.get("reasons") or [])
    if qc.get("case_release_status") == "analysis_only" and "not_qualified_emission" not in reasons:
        reasons.append("not_qualified_emission")
    issuance["reasons"] = reasons
    draft.setdefault("validation", {})["issuance"] = issuance

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
    # These are internal, calculation-derived inputs for document/review
    # re-assessment.  Persist them rather than accepting equivalent structures
    # back from an HTTP client, which would create a qualification bypass.
    for artifact_name, artifact_value in (
        ("normative_assessment.json", _as_dict(normative) or {}),
        ("report_context.json", report_context),
    ):
        try:
            artifact_payload = dumps_strict(artifact_value).encode("utf-8")
            context["artifact_bytes"][artifact_name] = artifact_payload
            context["artifact_states"][artifact_name] = {"state": "ready", "error": None}
            artifact_refs[artifact_name] = {"sha256": sha256_bytes(artifact_payload)}
            _save_artifact(job_store, job_id, artifact_name, artifact_payload)
        except Exception as exc:
            context["artifact_states"][artifact_name] = {
                "state": "failed",
                "error": make_issue(
                    "INTERNAL_CONTEXT_PERSIST_FAILED",
                    f"{artifact_name} could not be persisted: {exc}",
                    origin="c06.worker",
                    evidence={"exception_type": type(exc).__name__},
                ),
            }

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
            if not output_dir and job_store is not None:
                root = getattr(job_store, "root", None)
                if root is not None:
                    output_dir = os.path.join(str(root), "jobs", str(job_id), "evidence")
                    os.makedirs(output_dir, exist_ok=True)
            pack = dict(context["artifact_bytes"])
            if subject_design is not None:
                raw_values = _as_dict(_get(subject_design, "raw_values")) or dict(
                    context.get("subject_raw") or {}
                )
                pack["subject_design"] = {
                    "raw_values": raw_values,
                    "X": _design_row_mapping(_get(subject_design, "X")),
                    "supported": _get(subject_design, "supported"),
                }
            if context.get("subject_raw"):
                pack["subject_raw"] = context["subject_raw"]
            if pack.get("report.pdf") is not None:
                pack.setdefault("report_pdf", pack["report.pdf"])
            coeffs = _as_dict(_get(winner_fit, "coefficients"))
            if coeffs:
                pack.setdefault("coefficients", coeffs)
            cand_spec = _as_dict(_get(winner_fit, "candidate_spec"))
            y_tr = cand_spec.get("y_transformation") or _get(winner_fit, "y_transformation")
            if y_tr:
                pack.setdefault("y_transformation", y_tr)
            if cand_spec:
                pack.setdefault("candidate_spec", cand_spec)
            residual_for_pack = complete_residual_state_for_persist(winner_fit, subject_design)
            if residual_for_pack:
                pack.setdefault("residual_context", residual_for_pack)
                pack.setdefault("residual_state", residual_for_pack)
            pack.setdefault("feature_schema", _as_dict(_get(prepared, "feature_schema")) or _as_dict(_get(winner_fit, "feature_schema")))
            pack.setdefault("encoder_state", _as_dict(_get(prepared, "encoder_state")) or _as_dict(_get(winner_fit, "encoder_state")))
            pack.setdefault("request_spec", request_spec_for_peers(spec))
            pack.setdefault("missing_policy", spec.get("missing_policy"))
            pack.setdefault("outlier_policy", spec.get("outlier_policy"))
            pack.setdefault("search_policy", spec.get("search_policy"))
            pack.setdefault("evaluation_policy", spec.get("evaluation_policy"))
            # The bundle records the policy actually used by evaluation.  The
            # request remains available separately and cannot replace this
            # catalog-resolved rule with a client declaration.
            pack["value_policy"] = value_policy_used
            pack.setdefault("source_bytes", file_bytes)
            manifest = builder(
                snapshot, bundle, prepared, pack, output_dir
            )
            manifest_dict = _as_dict(manifest) or {"manifest": manifest}
            payload = dumps_strict(manifest_dict).encode("utf-8")
            context["artifact_bytes"]["evidence_manifest.json"] = payload
            context["artifact_states"]["evidence_manifest.json"] = {"state": "ready", "error": None}
            artifact_refs["evidence_manifest.json"] = {"sha256": sha256_bytes(payload)}
            _save_artifact(job_store, job_id, "evidence_manifest.json", payload)
            if output_dir:
                try:
                    zip_bytes = _zip_directory(output_dir)
                    context["artifact_bytes"]["evidence_bundle.zip"] = zip_bytes
                    context["artifact_states"]["evidence_bundle.zip"] = {"state": "ready", "error": None}
                    artifact_refs["evidence_bundle.zip"] = {"sha256": sha256_bytes(zip_bytes)}
                    _save_artifact(job_store, job_id, "evidence_bundle.zip", zip_bytes)
                except Exception as zip_exc:
                    logger.warning("evidence_bundle.zip failed; calculation preserved: %s", zip_exc)
                    context["artifact_states"]["evidence_bundle.zip"] = {
                        "state": "failed",
                        "error": make_issue(
                            "EVIDENCE_ZIP_FAILED",
                            f"evidence_bundle.zip could not be packed: {zip_exc}",
                            origin="c10.worker",
                            evidence={"exception_type": type(zip_exc).__name__},
                        ),
                    }
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
        search_audit=search_audit,
        value=snapshot.get("value") if isinstance(snapshot, Mapping) else None,
        value_policy=value_policy_used,
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


def _map_validation(
    normative: Any,
    assessment: Any,
    procedure: Any = None,
    *,
    numeric_disclosure: Optional[Mapping[str, Any]] = None,
) -> dict:
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
    statistical = dict(statistical or {})
    if n.get("n") is not None:
        statistical.setdefault("n", n.get("n"))
    if n.get("k") is not None:
        statistical.setdefault("k", n.get("k"))
    if n.get("intercept") is not None:
        statistical.setdefault("intercept", n.get("intercept"))
    numeric_diagnostics = _as_dict(_get(numeric_disclosure, "diagnostics")) or {}
    if numeric_diagnostics:
        statistical["diagnostics"] = numeric_diagnostics
    if procedure is not None:
        proc = _as_dict(procedure) or {}
        provenance = _as_dict(proc.get("procedure_provenance")) or {}
        partition = _as_dict(proc.get("partition")) or {}
        statistical = dict(statistical)
        statistical["procedure"] = {
            "method": partition.get("method") or provenance.get("evaluated_unit"),
            "seed": provenance.get("evaluation_seed") or partition.get("seed"),
            "coverage": proc.get("coverage") or proc.get("generalization"),
            "metrics": proc.get("metrics") or proc.get("original_unit_metrics") or proc.get("scores"),
            "stability": proc.get("stability"),
            "limitations": proc.get("limitations") or [],
            "partition": partition,
            "predictions": proc.get("predictions"),
            "usable_for_model_selection": proc.get("usable_for_model_selection"),
            "reserved_filtered_by_error": proc.get("reserved_filtered_by_error"),
            "winner_retrained_on_full_data": proc.get("winner_retrained_on_full_data"),
            "not_normative_classification": True,
        }
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
    drop = (
        "model_object",
        "base_frame",
        "candidate_fit",
        "X_design",
        "y_design",
        "_legacy_model_result",
        "_rank_tuple",
        "_peer_fit",
    )
    for item in alternatives:
        d = _as_dict(item) or {}
        for key in drop:
            d.pop(key, None)
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


def _zip_directory(root: str) -> bytes:
    """Pack a local evidence directory into a downloadable zip. Paths stay relative."""
    buf = io.BytesIO()
    base = os.path.abspath(root)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, base).replace("\\", "/")
                if rel.startswith(".."):
                    continue
                zf.write(full, arcname=rel)
    return buf.getvalue()


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
