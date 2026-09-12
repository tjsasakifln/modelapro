"""Public start path must spawn Streamlit as Streamlit, not frontend.app:main."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from c15_local.launcher import (
    backend_command,
    frontend_app_path,
    frontend_command,
    health_url,
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
