"""Install the built wheel outside the checkout and import packaged resources.

This is skipped unless C15_INSTALL_SMOKE=1 so the default suite stays cheap.
CI runs it in the dedicated install-smoke job; local verification also sets the flag.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("C15_INSTALL_SMOKE", "") not in {"1", "true", "yes"},
    reason="Set C15_INSTALL_SMOKE=1 to run the clean-venv wheel install smoke",
)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_clean_venv_install_imports_resources_and_health(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr[-4000:]
    wheels = list(dist.glob("modelapro-*.whl"))
    assert wheels

    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)
    constraint = REPO_ROOT / "constraints" / "linux-py3.txt"
    install_cmd = [str(python), "-m", "pip", "install", str(wheels[0])]
    if constraint.is_file():
        install_cmd = [
            str(python),
            "-m",
            "pip",
            "install",
            "-c",
            str(constraint),
            str(wheels[0]),
        ]
    installed = subprocess.run(install_cmd, capture_output=True, text=True, check=False)
    assert installed.returncode == 0, installed.stderr[-4000:]

    probe = r"""
import json, os
from pathlib import Path
from importlib.resources import files
import backend, modules, frontend, c15_local
from c15_local.launcher import frontend_app_path, frontend_command, backend_command

assert not os.environ.get("PYTHONPATH"), os.environ.get("PYTHONPATH")
template = files("modules") / "templates" / "report.html"
css = files("frontend") / "assets" / "styles.css"
assert template.is_file() and template.read_bytes()
assert css.is_file() and css.read_bytes()
app = frontend_app_path()
assert app.is_file()
cmd = frontend_command(app, "127.0.0.1", 8501)
assert cmd[1:4] == ["-m", "streamlit", "run"]
print(json.dumps({
    "backend": backend.__file__,
    "modules": modules.__file__,
    "frontend": frontend.__file__,
    "template": str(template),
    "css": str(css),
    "app": str(app),
    "frontend_cmd": cmd,
}))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["MODELA_SKIP_DOTENV"] = "1"
    ran = subprocess.run(
        [str(python), "-c", probe],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    payload = __import__("json").loads(ran.stdout.splitlines()[-1])
    assert "site-packages" in payload["backend"].replace("\\", "/")
    assert "modela-pro-c15" not in payload["template"]

    port = _free_port()
    env["API_HOST"] = "127.0.0.1"
    env["API_PORT"] = str(port)
    env["API_PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [str(python), "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        from c15_local.launcher import wait_for_health

        body = wait_for_health(f"http://127.0.0.1:{port}/health", timeout=40)
        assert body.get("status") == "healthy"
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
