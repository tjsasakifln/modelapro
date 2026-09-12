"""Synthetic fixtures for MP-COM C01. Not market evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.api import RuntimeBindings, bind_runtime, reset_runtime
from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore
from modules.websocket_notifier import WebSocketNotifier
from tests.pro_workflow.p01.conftest import (
    SYNTHETIC_LABEL,
    documented_csv_bytes,
    documented_identity_ols_frame,
    documented_request_spec,
)

SCRATCH = Path("/tmp/grok-goal-d8546a9b6ead/implementer")


def gold_csv_bytes() -> bytes:
    return documented_csv_bytes()


def gold_spec(**overrides):
    spec = documented_request_spec()
    spec["applicant"] = SYNTHETIC_LABEL
    spec["purpose"] = "c01-gold"
    spec.update(overrides)
    return spec


def gold_subject():
    return {"area": 73.5, "bairro": "Centro"}


def _shutdown_runner() -> None:
    runner = RuntimeBindings.task_runner
    if runner is not None and hasattr(runner, "shutdown"):
        try:
            runner.shutdown(wait=True)
        except Exception:
            pass


@pytest.fixture
def isolated_c01_runtime(tmp_path, monkeypatch):
    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
    store_root = tmp_path / "c01-store"
    store_root.mkdir()
    monkeypatch.setenv("MODELA_STORE_ROOT", str(store_root))
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")
    monkeypatch.setenv("MP_CODE_SHA", "c01-test")
    store = JobStore.configure_default(store_root, recover_abandoned=True)
    projects = ProjectStore(store.root)
    runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, reset_submissions=True)
    yield {"root": store_root, "job_store": store, "project_store": projects, "runner": runner}
    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()


def dump_json(name: str, payload) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
