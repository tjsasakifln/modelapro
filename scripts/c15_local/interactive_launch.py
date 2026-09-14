"""Testable launch policy: window flags, instance lock, browser, diagnostics."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

# Python 3.12 subprocess.CREATE_NO_WINDOW.  Incompatible with CREATE_NEW_CONSOLE
# and DETACHED_PROCESS — combining them is how console tools fail with
# 0x800700e8 (ERROR_NO_DATA / pipe closed) under Windows Terminal.
CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
CREATE_NEW_CONSOLE = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010))
DETACHED_PROCESS = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))

INSTANCE_LOCK_SCHEMA = "MP-INSTANCE-LOCK/1"
STOP_REQUEST_SCHEMA = "MP-STOP-REQUEST/1"


def windows_internal_console_creationflags() -> int:
    """Flags for strictly internal Windows console tools (whoami, icacls)."""
    flags = CREATE_NO_WINDOW
    if flags & (CREATE_NEW_CONSOLE | DETACHED_PROCESS):
        raise RuntimeError(
            "internal console flags must not include CREATE_NEW_CONSOLE or DETACHED_PROCESS"
        )
    return flags


def windows_internal_console_run_kwargs() -> dict:
    """subprocess.run kwargs: hidden window, explicit pipes, no inherited None stdio."""
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        kwargs["creationflags"] = windows_internal_console_creationflags()
    return kwargs


def windows_internal_child_popen_kwargs() -> dict:
    """Long-running internal children: no window, no unread pipes."""
    kwargs: dict = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = windows_internal_console_creationflags()
    return kwargs


def _is_unsafe_log_dir(directory: Path) -> bool:
    text = str(directory).replace("\\", "/").lower()
    if "program files" in text:
        return True
    try:
        resolved = directory.resolve()
        cwd = Path.cwd().resolve()
    except OSError:
        return True
    return resolved == cwd


def bootstrap_log_dir() -> Path:
    """Per-user log directory without requiring MODELA_RUNTIME_ROOT or a writable cwd."""
    candidates: list[Path] = []
    configured = os.environ.get("MODELA_RUNTIME_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured) / "logs")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        candidates.append(Path(base) / "MODELAPro" / "logs")
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        candidates.append(Path(xdg) / "modelapro" / "logs")
    tmp = os.environ.get("TEMP") or os.environ.get("TMPDIR") or tempfile.gettempdir()
    candidates.append(Path(tmp) / "MODELAPro" / "logs")
    last_error: Optional[Exception] = None
    for directory in candidates:
        if _is_unsafe_log_dir(directory):
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            probe = directory / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return directory
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"unable to open a private diagnostic directory: {last_error}")


def persist_launch_diagnostic(
    *,
    stage: str,
    detail: str,
    returncode: Optional[int] = None,
) -> Optional[Path]:
    try:
        directory = bootstrap_log_dir()
        path = directory / f"frozen-child-error-{os.getpid()}.log"
        path.write_text(
            (
                f"stage={stage}\n"
                f"role={os.environ.get('MODELA_PROCESS_ROLE', '')}\n"
                f"pid={os.getpid()}\n"
                f"command={sys.argv!r}\n"
                f"returncode={returncode}\n"
                f"{detail}"
            ),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        startup = directory / "startup.log"
        with startup.open("a", encoding="utf-8") as handle:
            handle.write(f"stage={stage} pid={os.getpid()} returncode={returncode}\n")
        return path
    except OSError:
        return None


def append_startup_log(stage: str, message: str) -> Optional[Path]:
    try:
        directory = bootstrap_log_dir()
        path = directory / "startup.log"
        with path.open("a", encoding="utf-8") as handle:
            role = os.environ.get("MODELA_PROCESS_ROLE", "")
            handle.write(
                f"stage={stage} pid={os.getpid()} role={role} {message}\n"
            )
        return path
    except OSError:
        return None


def should_open_interactive_browser(args) -> bool:
    for name in (
        "internal_api",
        "internal_frontend",
        "print_commands",
        "check_pdf",
        "api_only",
        "frontend_only",
        "no_browser",
    ):
        if getattr(args, name, False):
            return False
    return True


def ui_public_url(host: str, port: int, instance_id: str = "") -> str:
    base = f"http://{host}:{port}/"
    if instance_id:
        return f"{base}?instance={instance_id}"
    return base


def health_matches_instance(
    payload: object,
    instance_id: str,
    *,
    require_instance: bool = True,
) -> bool:
    if not isinstance(payload, Mapping) or payload.get("status") != "healthy":
        return False
    if not require_instance:
        return True
    return payload.get("instance_id") == instance_id


def command_is_our_executable(command: Optional[str], executable: str) -> bool:
    if not command or not executable:
        return False
    cmd = command.replace("/", "\\").lower()
    exe = executable.replace("/", "\\").lower()
    name = Path(executable).name.lower()
    return exe in cmd or name in cmd


def command_is_our_supervisor(command: Optional[str], executable: str) -> bool:
    if not command_is_our_executable(command, executable):
        return False
    assert command is not None
    return "--internal-api" not in command and "--internal-frontend" not in command


def command_is_our_service_child(command: Optional[str], executable: str) -> bool:
    if not command_is_our_executable(command, executable):
        return False
    assert command is not None
    return "--internal-api" in command or "--internal-frontend" in command


@dataclass(frozen=True)
class InstanceDecision:
    action: str
    reason: str
    lock: Optional[dict] = None


def evaluate_instance_lock(
    lock: Optional[Mapping],
    *,
    our_executable: str,
    lock_pid_running: bool,
    lock_pid_command: Optional[str],
    listener_pid: Optional[int],
    listener_command: Optional[str],
) -> InstanceDecision:
    """Decide reuse / start_new / conflict. Never authorizes killing a PID."""
    lock_dict = dict(lock) if isinstance(lock, Mapping) else None
    our_listener = command_is_our_executable(listener_command, our_executable)
    foreign_listener = listener_pid is not None and not our_listener

    if lock_dict and lock_pid_running and command_is_our_supervisor(
        lock_pid_command, our_executable
    ):
        return InstanceDecision("reuse", "legitimate supervisor still running", lock_dict)

    if foreign_listener:
        return InstanceDecision(
            "conflict",
            (
                f"A porta já está em uso pelo processo {listener_pid} "
                f"({listener_command or 'desconhecido'}), que não é este MODELA PRO. "
                "Nada foi encerrado. Feche esse programa ou altere a porta e tente de novo."
            ),
            lock_dict,
        )

    if our_listener:
        adopted = dict(lock_dict or {})
        adopted.setdefault("pid", listener_pid)
        return InstanceDecision(
            "reuse",
            "listening process belongs to this installation",
            adopted,
        )

    if lock_dict and not lock_pid_running:
        return InstanceDecision("start_new", "stale lock: recorded pid is not running", None)

    if lock_dict and lock_pid_running and not command_is_our_supervisor(
        lock_pid_command, our_executable
    ):
        return InstanceDecision(
            "start_new",
            "stale lock: pid was reused by an unrelated process; not killed",
            None,
        )

    return InstanceDecision("start_new", "no live instance", None)


def format_failure_message(stage: str, reason: str, log_path: str) -> str:
    return (
        "MODELA PRO não concluiu a abertura.\n\n"
        f"Etapa: {stage}\n"
        f"Motivo: {reason}\n\n"
        f"Diagnóstico: {log_path}\n"
        "Não é necessário manter um terminal aberto nem procurar o endereço local."
    )


def format_browser_failure_message(url: str, log_path: str) -> str:
    return (
        "MODELA PRO está em execução, mas o navegador padrão não abriu.\n\n"
        f"Endereço local (sem segredo): {url}\n\n"
        "Abra este endereço no navegador ou copie-o a partir desta mensagem. "
        "Isso recupera a falha de associação do navegador; não é a abertura normal.\n"
        f"Diagnóstico: {log_path}"
    )
