import io
import logging
import threading
import subprocess
import sys
import os
import stat

import pytest

from modules.config_manager import Config, build_config, default_runtime_root, validate_config
from modules.local_task_runner import LocalTaskRunner
from modules.logging_manager import DropClientDataFilter, setup_logging
from scripts.c15_local import launcher
from scripts.c15_local.launcher import product_version


def test_runtime_root_is_per_user_and_shared_host_is_rejected():
    assert "modelapro" in default_runtime_root().lower()
    with pytest.raises(ValueError, match="Non-loopback"):
        validate_config(Config(
            API_HOST="0.0.0.0", DATA_DIR="x", UPLOAD_DIR="x",
            REPORTS_DIR="x", JOBS_DIR="x", PROJECTS_DIR="x", LOG_DIR="x",
        ))
    with pytest.raises(ValueError, match="FRONTEND_HOST"):
        validate_config(Config(
            FRONTEND_HOST="0.0.0.0", DATA_DIR="x", UPLOAD_DIR="x",
            REPORTS_DIR="x", JOBS_DIR="x", PROJECTS_DIR="x", LOG_DIR="x",
        ))


def test_runtime_and_job_store_share_one_default_root(tmp_path, monkeypatch):
    from modules.job_store import JobStore

    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.delenv("MODELA_STORE_ROOT", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")
    JobStore.reset_default()
    cfg = build_config()
    store = JobStore(recover_abandoned=False)
    assert store.root == __import__("pathlib").Path(cfg.DATA_DIR).resolve()
    JobStore.reset_default()


def test_windows_private_acl_command_excludes_inherited_users_and_owner_rights():
    from scripts.c15_local.launcher import windows_private_acl_command

    user_sid = "S-1-5-21-3699639565-2515463329-295617607-500"
    command = windows_private_acl_command(r"D:\a\_temp\profile-active", user_sid, is_dir=True)
    joined = " ".join(command)
    assert command[:3] == ["icacls", r"D:\a\_temp\profile-active", "/inheritance:r"]
    assert f"*{user_sid}:(OI)(CI)F" in command
    assert "SYSTEM:(OI)(CI)F" in command
    assert "*S-1-5-32-544:(OI)(CI)F" in command
    assert "S-1-5-32-545" not in joined
    assert "Users" not in joined
    assert "Everyone" not in joined
    assert "S-1-3-4" not in joined
    assert "OWNER RIGHTS" not in joined


def test_ensure_local_directories_restricts_windows_runtime_root(tmp_path, monkeypatch):
    from scripts.c15_local import launcher as launcher_module
    from scripts.c15_local.launcher import ensure_local_directories

    root = tmp_path / "runtime"
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(root))
    monkeypatch.setattr(launcher_module.os, "name", "nt")
    monkeypatch.setattr(launcher_module, "_windows_current_user_sid", lambda: "S-1-5-21-1-2-3-500")
    observed = []

    def fake_run(command, **_kwargs):
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(launcher_module.subprocess, "run", fake_run)
    cfg = Config(
        DATA_DIR=str(root / "store"),
        UPLOAD_DIR=str(root / "uploads"),
        REPORTS_DIR=str(root / "reports"),
        JOBS_DIR=str(root / "store" / "jobs"),
        PROJECTS_DIR=str(root / "store" / "projects"),
        LOG_DIR=str(root / "logs"),
    )
    ensure_local_directories(cfg)
    assert observed
    assert observed[0][1] == str(root)
    assert all(item[2] == "/inheritance:r" for item in observed)
    assert all("S-1-5-32-545" not in " ".join(item) for item in observed)


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod bits; Windows uses restrict_private_path")
def test_launcher_directories_and_rotating_log_are_private(tmp_path):
    from scripts.c15_local.launcher import ensure_local_directories

    root = tmp_path / "runtime"
    cfg = Config(
        DATA_DIR=str(root / "store"),
        UPLOAD_DIR=str(root / "uploads"),
        REPORTS_DIR=str(root / "reports"),
        JOBS_DIR=str(root / "store" / "jobs"),
        PROJECTS_DIR=str(root / "store" / "projects"),
        LOG_DIR=str(root / "logs"),
    )
    previous_umask = os.umask(0o022)
    try:
        ensure_local_directories(cfg)
        logger = setup_logging("test.c04.private-log", log_dir=cfg.LOG_DIR)
        logger.info("technical event")
    finally:
        os.umask(previous_umask)
    for path in (
        cfg.DATA_DIR,
        cfg.UPLOAD_DIR,
        cfg.REPORTS_DIR,
        cfg.JOBS_DIR,
        cfg.PROJECTS_DIR,
        cfg.LOG_DIR,
    ):
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(root / "logs" / "modelapro.log").st_mode) == 0o600


def test_log_filter_redacts_message_arguments_and_extras():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(DropClientDataFilter())
    logger = logging.getLogger("test.c04.redaction")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info(
        "contact=%s cpf=%s token=%s",
        "ana@example.com", "123.456.789-09", "secret-value",
        extra={"payload": "private"},
    )
    output = stream.getvalue()
    assert "ana@example.com" not in output and "123.456.789-09" not in output
    assert "secret-value" not in output and "[REDACTED]" in output

    stream.seek(0)
    stream.truncate(0)
    logger.info(
        "filename=%s client_name=%s cnpj=%s",
        "Cliente_Joao_Rua_Augusta_123.xlsx",
        "Joao",
        "12.345.678/0001-90",
    )
    output = stream.getvalue()
    assert "Cliente_Joao" not in output
    assert "Joao" not in output
    assert "12.345.678/0001-90" not in output
    stream.seek(0)
    stream.truncate(0)
    logger.info("client=Pessoa Identificada; status=failed")
    assert "Pessoa Identificada" not in stream.getvalue()


def test_runner_enforces_queue_and_passes_cooperative_deadline(tmp_path):
    from modules.job_store import JobStore

    job_store = JobStore(tmp_path / "store", recover_abandoned=False)
    jobs = [job_store.create() for _ in range(2)]
    runner = LocalTaskRunner(job_store, max_workers=1, max_queue=0, min_free_disk_bytes=0, recover_abandoned=False)
    release = threading.Event()
    runner.submit(jobs[0]["job_id"], lambda deadline_monotonic: (release.wait(), {"outcome": "cancelled"})[1])
    with pytest.raises(RuntimeError, match="queue is full"):
        runner.submit(jobs[1]["job_id"], lambda: None)
    release.set()
    runner.shutdown(wait=True)


def test_product_version_is_visible_without_starting_services():
    assert product_version()
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.c15_local.launcher", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.startswith("MODELA PRO ")


def test_frozen_product_spawns_internal_children_not_python_dash_m(monkeypatch):
    monkeypatch.setattr(launcher, "is_frozen_product", lambda: True)
    assert launcher.backend_command("127.0.0.1", 8000) == [
        sys.executable,
        "--internal-api",
    ]
    assert launcher.frontend_command(__import__("pathlib").Path("app.py"), "127.0.0.1", 8501) == [
        sys.executable,
        "--internal-frontend",
    ]
