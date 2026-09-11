"""Isolate C11 storage and C10 runtime. Do not bind labeled C10 simulators."""

from __future__ import annotations

import pytest

from backend.api import RuntimeBindings, bind_runtime, reset_runtime
from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore
from modules.websocket_notifier import WebSocketNotifier


def _shutdown_runner() -> None:
    runner = RuntimeBindings.task_runner
    if runner is not None and hasattr(runner, "shutdown"):
        try:
            runner.shutdown(wait=True)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def isolated_c17_runtime(tmp_path, monkeypatch):
    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()

    store_root = tmp_path / "c17-store"
    store_root.mkdir()
    monkeypatch.setenv("MODELA_STORE_ROOT", str(store_root))
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")
    monkeypatch.setenv("MP_CODE_SHA", "c17-test")

    store = JobStore.configure_default(store_root, recover_abandoned=True)
    projects = ProjectStore(store.root)
    runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
    # Real C11 instances; peers stay None so get_peers() imports production MP/1.
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, reset_submissions=True)
    yield {"root": store_root, "job_store": store, "project_store": projects, "runner": runner}

    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
