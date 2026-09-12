"""Public local start path: uvicorn + Streamlit as their own processes."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Sequence

# When executed as a checkout script, make the repo root importable.
if __package__ in {None, ""}:
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    if str(_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(_ROOT / "scripts"))


def _config():
    from modules.config_manager import config

    return config


def product_version() -> str:
    """Return installed distribution version without depending on a checkout."""
    try:
        return importlib.metadata.version("modelapro")
    except importlib.metadata.PackageNotFoundError:
        return "0+uninstalled"


def is_frozen_product() -> bool:
    """True only inside the buyer-facing PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def frontend_app_path() -> Path:
    import frontend

    path = Path(frontend.__file__).resolve().parent / "app.py"
    if not path.is_file():
        raise FileNotFoundError(f"frontend.app is not packaged at {path}")
    return path


def backend_command(host: str, port: int) -> List[str]:
    if is_frozen_product():
        return [sys.executable, "--internal-api"]
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api:app",
        "--host",
        host,
        "--port",
        str(port),
        "--no-access-log",
    ]


def frontend_command(app_path: Path, host: str, port: int) -> List[str]:
    """Streamlit must be launched as its own process, never frontend.app:main()."""
    if is_frozen_product():
        return [sys.executable, "--internal-frontend"]
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]


def health_url(public_url: str) -> str:
    return public_url.rstrip("/") + "/health"


def wait_for_health(url: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last_error = "not contacted"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = response.read()
                if response.status != 200:
                    last_error = f"HTTP {response.status}"
                    time.sleep(0.3)
                    continue
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict) or not payload:
                    last_error = f"empty or non-object health body: {payload!r}"
                    time.sleep(0.3)
                    continue
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def ensure_local_directories(cfg) -> None:
    for path in (
        cfg.DATA_DIR,
        cfg.UPLOAD_DIR,
        cfg.REPORTS_DIR,
        cfg.JOBS_DIR,
        cfg.PROJECTS_DIR,
        cfg.LOG_DIR,
    ):
        os.makedirs(path, mode=0o700, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            # Windows ACLs are qualified separately; chmod is best-effort there.
            pass


def _print_commands(cfg) -> None:
    app_path = frontend_app_path()
    payload = {
        "backend": backend_command(cfg.API_HOST, cfg.API_PORT),
        "frontend": frontend_command(app_path, cfg.FRONTEND_HOST, cfg.FRONTEND_PORT),
        "health": health_url(cfg.API_PUBLIC_URL),
        "frontend_app": str(app_path),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _print_pdf_probe() -> int:
    from c15_local.pdf_env import probe_weasyprint

    result = probe_weasyprint()
    print(result.message)
    return 0 if result.ok else 2


def main_api(argv: Optional[Sequence[str]] = None) -> int:
    cfg = _config()
    ensure_local_directories(cfg)

    from modules.operacao_local.runtime import get_security_policy
    get_security_policy()  # Provision private credentials before starting either child.
    from modules.logging_manager import logger

    logger.info("Starting API on %s:%s", cfg.API_HOST, cfg.API_PORT)
    import uvicorn

    uvicorn.run(
        "backend.api:app",
        host=cfg.API_HOST,
        port=cfg.API_PORT,
        reload=False,
    )
    return 0


def main_frontend(argv: Optional[Sequence[str]] = None) -> int:
    cfg = _config()
    cmd = frontend_command(frontend_app_path(), cfg.FRONTEND_HOST, cfg.FRONTEND_PORT)
    os.execv(cmd[0], cmd)
    return 0


def _main_frozen_frontend() -> int:
    """Run Streamlit CLI inside the dedicated frozen child process."""
    cfg = _config()
    app_path = frontend_app_path()
    sys.argv = frontend_command(app_path, cfg.FRONTEND_HOST, cfg.FRONTEND_PORT)
    # ``frontend_command`` intentionally points back to this executable when
    # frozen, so construct Streamlit's own argv for its in-process CLI here.
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        cfg.FRONTEND_HOST,
        "--server.port",
        str(cfg.FRONTEND_PORT),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    from streamlit.web import cli as streamlit_cli

    return int(streamlit_cli.main() or 0)


def _terminate(procs: Sequence[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 5
    for proc in procs:
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start MODELA PRO locally (loopback API + Streamlit process)."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"MODELA PRO {product_version()}",
    )
    parser.add_argument("--internal-api", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-frontend", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print backend/frontend commands as JSON and exit.",
    )
    parser.add_argument(
        "--check-pdf",
        action="store_true",
        help="Probe WeasyPrint native libraries and exit.",
    )
    parser.add_argument("--health-timeout", type=float, default=45.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.internal_api:
        return main_api([])
    if args.internal_frontend:
        return _main_frozen_frontend()

    cfg = _config()
    ensure_local_directories(cfg)

    if args.print_commands:
        _print_commands(cfg)
        return 0
    if args.check_pdf:
        return _print_pdf_probe()
    # Provision before the UI and backend race to read first-use credentials.
    from modules.operacao_local.runtime import get_security_policy
    get_security_policy()
    if args.api_only:
        return main_api()
    if args.frontend_only:
        return main_frontend()

    from c15_local.pdf_env import probe_weasyprint
    from modules.logging_manager import logger

    pdf = probe_weasyprint()
    if pdf.ok:
        logger.info("PDF environment: %s", pdf.message)
    else:
        logger.warning("PDF environment: %s", pdf.message)

    if cfg.API_HOST in {"0.0.0.0", "::", "[::]"}:
        logger.warning("API_HOST=%s exposes all interfaces; shipped default is 127.0.0.1", cfg.API_HOST)

    backend_cmd = backend_command(cfg.API_HOST, cfg.API_PORT)
    frontend_cmd = frontend_command(
        frontend_app_path(), cfg.FRONTEND_HOST, cfg.FRONTEND_PORT
    )
    logger.info("Backend command: %s", " ".join(backend_cmd))
    logger.info("Frontend command: %s", " ".join(frontend_cmd))

    procs: list[subprocess.Popen] = []

    def handle_signal(signum, _frame):
        logger.info("Received signal %s; stopping children", signum)
        _terminate(procs)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_signal)

    env = os.environ.copy()
    backend = subprocess.Popen(backend_cmd, env=env)
    procs.append(backend)
    frontend = subprocess.Popen(frontend_cmd, env=env)
    procs.append(frontend)

    try:
        payload = wait_for_health(health_url(cfg.API_PUBLIC_URL), timeout=args.health_timeout)
        logger.info("API health %s -> %s", health_url(cfg.API_PUBLIC_URL), payload)
        print(f"API: {cfg.API_PUBLIC_URL}  (health {payload})")
        print(f"UI:  http://{cfg.FRONTEND_HOST}:{cfg.FRONTEND_PORT}")
        print("Stop with Ctrl+C. Redis is not required.")
        while True:
            if backend.poll() is not None:
                _terminate(procs)
                return backend.returncode or 1
            if frontend.poll() is not None:
                _terminate(procs)
                return frontend.returncode or 1
            time.sleep(0.5)
    except Exception:
        _terminate(procs)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
