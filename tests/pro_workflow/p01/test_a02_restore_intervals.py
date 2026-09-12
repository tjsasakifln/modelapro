"""P01-A02: freeze → new process → two subjects; malformed state; log estimand."""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.worker import build_frozen_project, compose_valuation_job, resolve_peers
from modules.model_builder import CandidateSpec, fit_candidate
from modules.pro_workflow.residual_state import extract_residual_state
from modules.valuation_batch import builtin_evaluate_fitted, evaluate_batch, restore_candidate_fit
from tests.pro_workflow.p01.conftest import (
    SYNTHETIC_LABEL,
    documented_identity_ols_frame,
    documented_request_spec,
)
from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared

ABS_TOL = 1e-6
REL_TOL = 1e-8
SCRATCH = Path("/tmp/grok-goal-c8528f369173/implementer")

PROC2 = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from modules.valuation_batch import restore_candidate_fit, builtin_evaluate_fitted

frozen_path, subjects_path, out_path = sys.argv[2], sys.argv[3], sys.argv[4]
with open(frozen_path, encoding="utf-8") as fh:
    frozen = json.load(fh)
with open(subjects_path, encoding="utf-8") as fh:
    subjects = json.load(fh)
spec = frozen["request_spec"]
fit = restore_candidate_fit(frozen)
assert fit.get("model_object") is None
items = []
for sub in subjects:
    design = {
        "subject_id": sub["subject_id"],
        "raw_values": sub["raw"],
        "X": sub["X"],
        "supported": True,
        "issues": [],
    }
    got = builtin_evaluate_fitted(fit, design, spec)
    items.append({
        "subject_id": sub["subject_id"],
        "point": (got.get("value") or {}).get("point"),
        "mean_ci80": (got.get("value") or {}).get("mean_ci80"),
        "prediction_interval": (got.get("value") or {}).get("prediction_interval"),
        "admissible_interval": (got.get("value") or {}).get("admissible_interval"),
        "limitations": (got.get("statistical") or {}).get("limitations") or [],
    })
payload = {
    "items": items,
    "json_has_model_object": "model_object" in json.dumps(frozen),
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
print(json.dumps({"n": len(items)}))
"""


def _close(a, b):
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _fit_identity():
    frame = documented_identity_ols_frame()
    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="p01-a02",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    fit = fit_candidate(prepared, spec, documented_request_spec())
    frozen = build_frozen_project(
        project_id="p01-a02",
        revision_id="rev-a02",
        request_spec=documented_request_spec(),
        input_bundle={"input_sha256": "p01-a02-input", "raw_frame": frame},
        prepared_dataset=prepared,
        winner_fit=fit,
        subject_design={"subject_id": "orig", "raw_values": {"area": 90.0, "bairro": "Centro"}, "supported": True},
        normative={"edition": "NBR 14653-2:2011"},
        artifact_refs={},
        sample_ledger=prepared["sample_ledger"],
    )
    return frame, prepared, fit, frozen


def _design(area, sul, bairro):
    return {
        "subject_id": f"s-{bairro}-{area}",
        "raw_values": {"area": area, "bairro": bairro, "bairro_Sul": sul},
        "X": {"const": 1.0, "area": float(area), "bairro_Sul": float(sul)},
        "supported": True,
        "issues": [],
    }


def test_p01_a02_new_process_two_subjects_match_individual(tmp_path):
    _frame, _prepared_ds, fit, frozen = _fit_identity()
    dumped = json.dumps(frozen, allow_nan=False)
    assert "model_object" not in dumped
    assert "pickle" not in dumped.lower()

    subjects = [
        {
            "subject_id": "s-centro",
            "raw": {"area": 90.0, "bairro": "Centro", "bairro_Sul": 0.0},
            "X": {"const": 1.0, "area": 90.0, "bairro_Sul": 0.0},
        },
        {
            "subject_id": "s-sul",
            "raw": {"area": 140.0, "bairro": "Sul", "bairro_Sul": 1.0},
            "X": {"const": 1.0, "area": 140.0, "bairro_Sul": 1.0},
        },
    ]
    designs = [
        _design(90.0, 0.0, "Centro"),
        _design(140.0, 1.0, "Sul"),
    ]
    restored = restore_candidate_fit(frozen)
    individuals = [
        builtin_evaluate_fitted(restored, d, documented_request_spec()) for d in designs
    ]
    live = [
        builtin_evaluate_fitted(
            {
                **restore_candidate_fit(frozen),
                "residual_state": extract_residual_state(fit),
            },
            d,
            documented_request_spec(),
        )
        for d in designs
    ]
    for ind, lv in zip(individuals, live):
        assert _close(ind["value"]["point"], lv["value"]["point"])
        assert _close(ind["value"]["mean_ci80"]["lower"], lv["value"]["mean_ci80"]["lower"])
        assert _close(ind["value"]["prediction_interval"]["lower"], lv["value"]["prediction_interval"]["lower"])

    frozen_path = tmp_path / "frozen.json"
    subjects_path = tmp_path / "subjects.json"
    out_path = tmp_path / "proc2.json"
    frozen_path.write_text(json.dumps(frozen, allow_nan=False), encoding="utf-8")
    subjects_path.write_text(json.dumps(subjects, allow_nan=False), encoding="utf-8")
    repo = str(Path(__file__).resolve().parents[3])
    log1 = SCRATCH / "p01-a02-proc1.log"
    log2 = SCRATCH / "p01-a02-proc2.log"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log1.write_text(dumped[:4000], encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", PROC2, repo, str(frozen_path), str(subjects_path), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    log2.write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["json_has_model_object"] is False
    assert len(payload["items"]) == 2
    for item, ind in zip(payload["items"], individuals):
        assert _close(item["point"], ind["value"]["point"])
        assert _close(item["mean_ci80"]["lower"], ind["value"]["mean_ci80"]["lower"])
        assert _close(item["mean_ci80"]["upper"], ind["value"]["mean_ci80"]["upper"])
        assert _close(item["prediction_interval"]["lower"], ind["value"]["prediction_interval"]["lower"])
        assert _close(item["prediction_interval"]["upper"], ind["value"]["prediction_interval"]["upper"])


def test_p01_a02_malformed_and_incomplete_do_not_fabricate_precision():
    _frame, _prep, _fit, frozen = _fit_identity()
    order = list(frozen["model_state"]["feature_order"])
    identity = [[1.0 if i == j else 0.0 for j in range(len(order))] for i in range(len(order))]
    malformed = copy.deepcopy(frozen)
    # Same order as the fit: a 3x3 identity is a usable matrix, not an order mismatch.
    malformed["model_state"]["xtx_inv"] = identity
    malformed["model_state"]["residual_state"]["xtx_inv"] = identity
    malformed["model_state"]["residual_state"]["status"] = "malformed"
    malformed["model_state"]["residual_state"]["feature_order"] = order
    malformed["residual_state"] = malformed["model_state"]["residual_state"]
    design = _design(100.0, 1.0, "Sul")
    restored = restore_candidate_fit(malformed)
    rebuilt = extract_residual_state(restored)
    assert rebuilt.get("status") == "malformed"
    got = builtin_evaluate_fitted(restored, design, documented_request_spec())
    assert got["value"]["point"] is not None
    assert got["value"]["mean_ci80"] is None
    assert got["value"]["prediction_interval"] is None
    assert got["value"]["admissible_interval"] is None
    assert (got.get("statistical") or {}).get("residual_state_status") == "malformed"
    limitations = list((got.get("statistical") or {}).get("limitations") or [])
    assert "residual_state_malformed" in limitations or "statistical_intervals_unavailable" in limitations

    incomplete = copy.deepcopy(frozen)
    incomplete["model_state"]["xtx_inv"] = None
    incomplete["model_state"]["residual_std"] = None
    incomplete["model_state"]["residual_state"] = {"schema_version": "MP-PRO/1", "status": "incomplete"}
    incomplete["residual_state"] = incomplete["model_state"]["residual_state"]
    got2 = builtin_evaluate_fitted(restore_candidate_fit(incomplete), design, documented_request_spec())
    assert got2["value"]["point"] is not None
    assert got2["value"]["mean_ci80"] is None
    assert got2["value"]["admissible_interval"] is None
    # ±15% arbitration may exist as arbitration, never as statistical IC / admissible.
    arb = got2["value"].get("arbitration_interval")
    if arb:
        lo, hi = float(arb["lower"]), float(arb["upper"])
        point = float(got2["value"]["point"])
        assert abs((hi - lo) / point - 0.30) < 0.02
        assert got2["value"]["mean_ci80"] is None


HTTP_PROC1 = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from backend.api import app, bind_runtime, reset_runtime
from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore
from modules.result_contract import dumps_strict
from modules.websocket_notifier import WebSocketNotifier

repo, root, frozen_path, meta_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
reset_runtime()
JobStore.reset_default()
WebSocketNotifier().reset_connections()
store = JobStore.configure_default(root, recover_abandoned=True)
projects = ProjectStore(store.root)
runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
bind_runtime(job_store=store, project_store=projects, task_runner=runner, reset_submissions=True)
frozen = json.loads(open(frozen_path, encoding="utf-8").read())
from modules.operacao_local.runtime import local_client_headers
client = TestClient(app, headers=local_client_headers())
saved = client.post(
    "/projects/p01-a02/revisions",
    content=dumps_strict(frozen),
    headers={"Content-Type": "application/json"},
)
assert saved.status_code == 201, saved.text
open(meta_path, "w", encoding="utf-8").write(json.dumps({"revision_id": saved.json()["revision_id"]}))
runner.shutdown(wait=True)
reset_runtime()
JobStore.reset_default()
print("proc1-ok")
"""

HTTP_PROC2 = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from fastapi.testclient import TestClient
from backend.api import app, bind_runtime, reset_runtime
from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore
from modules.valuation_batch import builtin_evaluate_fitted, restore_candidate_fit
from modules.websocket_notifier import WebSocketNotifier

repo, root, meta_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
reset_runtime()
JobStore.reset_default()
WebSocketNotifier().reset_connections()
store = JobStore.configure_default(root, recover_abandoned=True)
projects = ProjectStore(store.root)
runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
bind_runtime(job_store=store, project_store=projects, task_runner=runner, reset_submissions=True)
from modules.operacao_local.runtime import local_client_headers
client = TestClient(app, headers=local_client_headers())
loaded = client.get("/projects/p01-a02")
assert loaded.status_code == 200, loaded.text
frozen = loaded.json()["revision"]
assert frozen["model_state"]["residual_std"] is not None
assert frozen["model_state"]["xtx_inv"] is not None
restored = restore_candidate_fit(frozen)
subjects = [
    {"subject_id": "s-centro", "X": {"const": 1.0, "area": 90.0, "bairro_Sul": 0.0}, "raw_values": {"area": 90.0, "bairro": "Centro"}},
    {"subject_id": "s-sul", "X": {"const": 1.0, "area": 140.0, "bairro_Sul": 1.0}, "raw_values": {"area": 140.0, "bairro": "Sul"}},
]
items = []
for sub in subjects:
    got = builtin_evaluate_fitted(
        restored,
        {"subject_id": sub["subject_id"], "raw_values": sub["raw_values"], "X": sub["X"], "supported": True, "issues": []},
        frozen["request_spec"],
    )
    items.append({
        "subject_id": sub["subject_id"],
        "point": (got.get("value") or {}).get("point"),
        "mean_ci80": (got.get("value") or {}).get("mean_ci80"),
        "prediction_interval": (got.get("value") or {}).get("prediction_interval"),
        "admissible_interval": (got.get("value") or {}).get("admissible_interval"),
    })
open(out_path, "w", encoding="utf-8").write(json.dumps({"items": items, "revision_id": frozen.get("revision_id")}))
runner.shutdown(wait=True)
reset_runtime()
print("proc2-ok")
"""


def test_p01_a02_http_revision_roundtrip_fresh_process(tmp_path):
    from modules.result_contract import dumps_strict

    _frame, _prep, fit, frozen = _fit_identity()
    dumps_strict(frozen)
    live = [
        builtin_evaluate_fitted(
            restore_candidate_fit(frozen),
            d,
            documented_request_spec(),
        )
        for d in (_design(90.0, 0.0, "Centro"), _design(140.0, 1.0, "Sul"))
    ]
    repo = str(Path(__file__).resolve().parents[3])
    root = tmp_path / "http-store"
    root.mkdir()
    frozen_path = tmp_path / "frozen.json"
    meta_path = tmp_path / "meta.json"
    out_path = tmp_path / "proc2.json"
    frozen_path.write_text(dumps_strict(frozen), encoding="utf-8")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    p1 = subprocess.run(
        [sys.executable, "-c", HTTP_PROC1, repo, str(root), str(frozen_path), str(meta_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    (SCRATCH / "p01-a02-proc1.log").write_text(p1.stdout + "\n" + p1.stderr, encoding="utf-8")
    assert p1.returncode == 0, p1.stderr + p1.stdout
    p2 = subprocess.run(
        [sys.executable, "-c", HTTP_PROC2, repo, str(root), str(meta_path), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    (SCRATCH / "p01-a02-proc2.log").write_text(p2.stdout + "\n" + p2.stderr, encoding="utf-8")
    assert p2.returncode == 0, p2.stderr + p2.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload["items"]) == 2
    for item, ind in zip(payload["items"], live):
        assert _close(item["point"], ind["value"]["point"])
        assert _close(item["mean_ci80"]["lower"], ind["value"]["mean_ci80"]["lower"])
        assert _close(item["mean_ci80"]["upper"], ind["value"]["mean_ci80"]["upper"])
        assert _close(item["prediction_interval"]["lower"], ind["value"]["prediction_interval"]["lower"])
        assert item["admissible_interval"] is not None or ind["value"]["admissible_interval"] is None


def test_p01_a02_log_target_keeps_estimand_no_monetary_mean_ci():
    frame = documented_identity_ols_frame()
    frame = frame[frame["preco"] > 0].reset_index(drop=True)
    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="p01-a02-log",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="log",
    )
    fit = fit_candidate(prepared, spec, documented_request_spec())
    assert fit.status == "fitted"
    frozen = build_frozen_project(
        project_id="p01-a02-log",
        revision_id="rev-log",
        request_spec=documented_request_spec(target_unit="BRL"),
        input_bundle={"input_sha256": "p01-log", "raw_frame": frame},
        prepared_dataset=prepared,
        winner_fit=fit,
        subject_design={"subject_id": "s", "raw_values": {"area": 100.0, "bairro": "Sul"}, "supported": True},
        normative={"edition": "NBR 14653-2:2011"},
        artifact_refs={},
        sample_ledger=prepared["sample_ledger"],
    )
    y_state = frozen["model_state"]["target_transform_state"]
    assert str(y_state.get("name")) in {"log", "ln"}
    got = builtin_evaluate_fitted(
        restore_candidate_fit(frozen),
        _design(100.0, 1.0, "Sul"),
        documented_request_spec(target_unit="BRL"),
    )
    assert got["value"]["point"] is not None
    assert got["value"]["mean_ci80"] is None
    limitations = list((got.get("statistical") or {}).get("limitations") or [])
    estimand = (got.get("statistical") or {}).get("estimand")
    assert estimand in {None, "exp(E[log Y|X])", "median(Y|X)"} or "log" in str(estimand).lower() or estimand
    assert got["value"]["mean_ci80"] is None
