"""Public start path must spawn Streamlit as Streamlit, not frontend.app:main."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import uvicorn

from backend import worker as worker_module
from c15_local import launcher as launcher_module
from c15_local.launcher import (
    _entrypoint,
    _log_frozen_child_diagnostics,
    backend_command,
    frontend_app_path,
    frontend_command,
    health_url,
    service_environment,
    wait_for_health,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def test_frontend_command_is_streamlit_cli_not_app_main():
    app_path = frontend_app_path()
    assert app_path.name == "app.py"
    assert app_path.is_file()
    cmd = frontend_command(app_path, "127.0.0.1", 8501)
    assert cmd[0] == sys.executable
    assert cmd[1:4] == ["-m", "streamlit", "run"]
    assert str(app_path) in cmd
    assert "--server.address" in cmd
    assert cmd[cmd.index("--server.address") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--global.developmentMode") + 1] == "false"
    joined = " ".join(cmd)
    assert "frontend.app:main" not in joined
    assert "app:main" not in joined


def test_backend_command_is_uvicorn_on_loopback():
    cmd = backend_command("127.0.0.1", 8000)
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "uvicorn"]
    assert "backend.api:app" in cmd
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in cmd


def test_service_environment_binds_frontend_client_to_selected_api(monkeypatch):
    monkeypatch.delenv("MODELA_API_URL", raising=False)
    monkeypatch.delenv("MODELA_API_TIMEOUT", raising=False)
    cfg = SimpleNamespace(API_PUBLIC_URL="http://127.0.0.1:18765")
    env = service_environment(cfg)
    assert env["MODELA_API_URL"] == cfg.API_PUBLIC_URL
    assert env["MODELA_API_TIMEOUT"] == "120"

    monkeypatch.setenv("MODELA_API_URL", "http://127.0.0.1:19999")
    monkeypatch.setenv("MODELA_API_TIMEOUT", "45")
    env = service_environment(cfg)
    assert env["MODELA_API_URL"] == "http://127.0.0.1:19999"
    assert env["MODELA_API_TIMEOUT"] == "45"


def test_windows_process_tree_assigns_children_and_closes_job_handle():
    tree = object.__new__(launcher_module._WindowsProcessTree)
    tree._handle = 101
    tree._kernel32 = SimpleNamespace(
        AssignProcessToJobObject=Mock(return_value=1),
        CloseHandle=Mock(return_value=1),
    )
    process = SimpleNamespace(_handle=202)

    tree.add(process)
    tree.close()
    tree.close()

    tree._kernel32.AssignProcessToJobObject.assert_called_once_with(101, 202)
    tree._kernel32.CloseHandle.assert_called_once_with(101)
    assert tree._handle is None


def test_frozen_code_identity_uses_immutable_resource_and_ignores_environment(
    tmp_path, monkeypatch
):
    identity = {
        "schema_version": "MP-COM-BUILD-IDENTITY/1",
        "source_sha": "a" * 40,
        "tree_sha": "b" * 40,
    }
    (tmp_path / "build-source-identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    monkeypatch.setattr(worker_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(worker_module.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("MP_CODE_SHA", "environment-must-not-override-frozen-build")

    assert worker_module.current_code_sha() == "a" * 40


def test_frozen_code_identity_fails_closed_without_verified_resource(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(worker_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(worker_module.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("MP_CODE_SHA", "environment-must-not-rescue-frozen-build")

    with pytest.raises(RuntimeError, match="frozen build source identity"):
        worker_module.current_code_sha()

    (tmp_path / "build-source-identity.json").write_text(
        json.dumps(
            {
                "schema_version": "MP-COM-BUILD-IDENTITY/1",
                "source_sha": "a" * 40,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="frozen build source identity"):
        worker_module.current_code_sha()


def test_internal_api_disables_uvicorn_console_formatter(monkeypatch):
    from types import SimpleNamespace

    captured = {}
    monkeypatch.setattr(
        launcher_module,
        "_config",
        lambda: SimpleNamespace(API_HOST="127.0.0.1", API_PORT=8000),
    )
    monkeypatch.setattr(launcher_module, "ensure_local_directories", lambda _cfg: None)
    monkeypatch.setattr(
        "modules.operacao_local.runtime.get_security_policy", lambda: object()
    )
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    assert launcher_module.main_api([]) == 0
    assert captured["access_log"] is False
    assert captured["log_config"] is None


def test_print_commands_json_matches_helpers():
    env = {
        **os.environ,
        "MODELA_SKIP_DOTENV": "1",
        "PYTHONPATH": f"{REPO_ROOT}{os.pathsep}{SCRIPTS}",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "c15_local.launcher", "--print-commands"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["backend"][1:3] == ["-m", "uvicorn"]
    assert payload["frontend"][1:4] == ["-m", "streamlit", "run"]
    assert payload["health"].endswith("/health")
    assert "frontend.app:main" not in json.dumps(payload)


def test_backend_import_defers_heavy_document_renderer():
    env = {
        **os.environ,
        "MODELA_SKIP_DOTENV": "1",
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import backend.api, sys; print('scipy' in sys.modules)",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_backend_process_health_on_loopback():
    port = _free_loopback_port()
    cmd = backend_command("127.0.0.1", port)
    env = {
        **__import__("os").environ,
        "MODELA_SKIP_DOTENV": "1",
        "API_HOST": "127.0.0.1",
        "API_PORT": str(port),
        "API_PUBLIC_URL": f"http://127.0.0.1:{port}",
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}/health"
    try:
        body = wait_for_health(url, timeout=40)
        assert body.get("status") == "healthy"
        with urllib.request.urlopen(url, timeout=3) as response:
            assert response.status == 200
            raw = response.read()
            assert raw
        assert "0.0.0.0" not in " ".join(cmd)
        assert health_url(f"http://127.0.0.1:{port}") == url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_health_wait_fails_immediately_when_product_child_exits(monkeypatch):
    class ExitedProcess:
        returncode = 37

        def poll(self):
            return self.returncode

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")
        ),
    )
    with pytest.raises(RuntimeError, match=r"frontend.*exit code 37"):
        wait_for_health(
            "http://127.0.0.1:9/health",
            timeout=30,
            processes={"frontend": ExitedProcess()},
        )


def test_entrypoint_reports_child_failure_without_unhandled_window(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(tmp_path))

    def fail():
        raise RuntimeError("concrete child failure")

    assert _entrypoint(fail) == 1
    assert "RuntimeError: concrete child failure" in capsys.readouterr().err
    diagnostic = next((tmp_path / "logs").glob("frozen-child-error-*.log"))
    assert "RuntimeError: concrete child failure" in diagnostic.read_text(
        encoding="utf-8"
    )


def test_entrypoint_persists_traceback_when_windowed_stderr_is_absent(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setattr(launcher_module.sys, "stderr", None)

    def fail():
        raise RuntimeError("windowed child failure")

    assert _entrypoint(fail) == 1
    diagnostic = next((tmp_path / "logs").glob("frozen-child-error-*.log"))
    detail = diagnostic.read_text(encoding="utf-8")
    assert "command=" in detail
    assert "RuntimeError: windowed child failure" in detail


def test_entrypoint_persists_without_runtime_root_when_stderr_is_none(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MODELA_RUNTIME_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TEMP", str(tmp_path / "Temp"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "Temp"))
    monkeypatch.setattr(launcher_module.sys, "stderr", None)

    def fail():
        raise RuntimeError("windowed child failure without runtime root")

    assert _entrypoint(fail) == 1
    matches = list((tmp_path / "Local" / "MODELAPro" / "logs").glob("frozen-child-error-*.log"))
    matches += list((tmp_path / "xdg" / "modelapro" / "logs").glob("frozen-child-error-*.log"))
    matches += list((tmp_path / "Temp" / "MODELAPro" / "logs").glob("frozen-child-error-*.log"))
    assert matches, "diagnostic must persist without MODELA_RUNTIME_ROOT"
    detail = matches[0].read_text(encoding="utf-8")
    assert "windowed child failure without runtime root" in detail
    assert "stage=entrypoint" in detail


def test_parent_copies_frozen_child_diagnostic_into_product_log(tmp_path):
    from unittest.mock import Mock

    diagnostic = tmp_path / "frozen-child-error-42.log"
    diagnostic.write_text("Traceback\nRuntimeError: child failed", encoding="utf-8")
    logger = Mock()

    _log_frozen_child_diagnostics(logger, tmp_path)

    logger.error.assert_called_once()
    args = logger.error.call_args.args
    assert diagnostic == args[1]
    assert "RuntimeError: child failed" in args[2]
