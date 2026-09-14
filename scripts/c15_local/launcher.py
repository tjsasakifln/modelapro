"""Public local start path: uvicorn + Streamlit as their own processes."""

from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

# When executed as a checkout script, make the repo root importable.
if __package__ in {None, ""}:
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    if str(_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(_ROOT / "scripts"))

try:
    from .interactive_launch import (
        INSTANCE_LOCK_SCHEMA,
        STOP_REQUEST_SCHEMA,
        append_startup_log,
        bootstrap_log_dir,
        command_is_our_executable,
        evaluate_instance_lock,
        format_browser_failure_message,
        format_failure_message,
        health_matches_instance,
        persist_launch_diagnostic,
        should_open_interactive_browser,
        ui_public_url,
        windows_internal_console_run_kwargs,
    )
except (ImportError, ValueError):
    from c15_local.interactive_launch import (
        INSTANCE_LOCK_SCHEMA,
        STOP_REQUEST_SCHEMA,
        append_startup_log,
        bootstrap_log_dir,
        command_is_our_executable,
        evaluate_instance_lock,
        format_browser_failure_message,
        format_failure_message,
        health_matches_instance,
        persist_launch_diagnostic,
        should_open_interactive_browser,
        ui_public_url,
        windows_internal_console_run_kwargs,
    )


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
    return [sys.executable, "-m", "streamlit", *_streamlit_run_arguments(app_path, host, port)]


def _streamlit_run_arguments(app_path: Path, host: str, port: int) -> List[str]:
    return [
        "run",
        str(app_path),
        # Frozen entrypoints have no Streamlit source checkout.  Explicitly
        # disable its auto-detected development mode before setting a port.
        "--global.developmentMode",
        "false",
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


def service_environment(cfg) -> dict[str, str]:
    """Bind the packaged UI client to the API address selected by the launcher."""
    env = os.environ.copy()
    env.setdefault("MODELA_API_URL", cfg.API_PUBLIC_URL)
    # The first preview in a frozen process loads the scientific import graph.
    # Keep the normal installed path above the measured cold-start time while
    # preserving an operator's explicit timeout choice.
    env.setdefault("MODELA_API_TIMEOUT", "120")
    return env


def _raise_if_children_exited(processes: Optional[Mapping[str, subprocess.Popen]]) -> None:
    for name, process in (processes or {}).items():
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"{name} process exited before API health with exit code {returncode}"
            )


def wait_for_health(
    url: str,
    timeout: float = 30.0,
    *,
    processes: Optional[Mapping[str, subprocess.Popen]] = None,
    instance_id: Optional[str] = None,
    require_instance: bool = False,
) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "not contacted"
    while time.monotonic() < deadline:
        _raise_if_children_exited(processes)
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
                if instance_id or require_instance:
                    if not health_matches_instance(
                        payload, instance_id or "", require_instance=require_instance
                    ):
                        last_error = f"health identity mismatch: {payload!r}"
                        time.sleep(0.3)
                        continue
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for {url}: {last_error}")


def wait_for_ui(
    url: str,
    timeout: float = 30.0,
    *,
    processes: Optional[Mapping[str, subprocess.Popen]] = None,
) -> bytes:
    deadline = time.monotonic() + timeout
    last_error = "not contacted"
    while time.monotonic() < deadline:
        _raise_if_children_exited(processes)
        try:
            with urllib.request.urlopen(url.split("?", 1)[0], timeout=2) as response:
                body = response.read(256)
                if response.status == 200 and body:
                    return body
                last_error = f"HTTP {response.status}, {len(body)} bytes"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for UI {url}: {last_error}")


_WINDOWS_ADMINISTRATORS_SID = "S-1-5-32-544"


def windows_private_acl_command(path: str, user_sid: str, *, is_dir: bool) -> list[str]:
    """Explicit owner/SYSTEM/Administrators DACL; strip inherited Users."""
    if not user_sid.startswith("S-1-") or " " in user_sid:
        raise RuntimeError("Windows private ACL requires a SID")
    rights = "(OI)(CI)F" if is_dir else "F"
    command = [
        "icacls",
        path,
        "/inheritance:r",
        "/grant:r",
        f"*{user_sid}:{rights}",
        "/grant:r",
        f"SYSTEM:{rights}",
        "/grant:r",
        f"*{_WINDOWS_ADMINISTRATORS_SID}:{rights}",
        "/remove:g",
        "*S-1-3-4",
        "/remove:g",
        "*S-1-5-32-545",
        "/remove:g",
        "*S-1-1-0",
    ]
    return command


def _windows_sid_from_process_token() -> str:
    """SID of the current process token; used if whoami cannot start a console."""
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.cast(buf, ctypes.POINTER(TOKEN_USER)).contents
        sid_ptr = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(sid_ptr)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = sid_ptr.value or ""
        finally:
            kernel32.LocalFree(sid_ptr)
    finally:
        kernel32.CloseHandle(token)
    if not sid.startswith("S-1-"):
        raise RuntimeError(f"unable to resolve Windows user SID from token: {sid!r}")
    return sid


def _windows_current_user_sid() -> str:
    completed = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        text=True,
        check=False,
        **windows_internal_console_run_kwargs(),
    )
    if completed.returncode == 0:
        sid = completed.stdout.strip().split(",")[-1].strip().strip('"')
        if sid.startswith("S-1-"):
            return sid
        whoami_error = f"unable to resolve Windows user SID: {completed.stdout!r}"
    else:
        whoami_error = (
            f"unable to resolve Windows user SID: rc={completed.returncode} "
            f"{completed.stderr or completed.stdout}"
        )
    append_startup_log("whoami", whoami_error)
    try:
        return _windows_sid_from_process_token()
    except Exception as exc:
        raise RuntimeError(f"{whoami_error}; token fallback failed: {exc}") from exc


def restrict_private_path(path: str | os.PathLike) -> None:
    target = os.fspath(path)
    if os.name != "nt":
        mode = 0o700 if os.path.isdir(target) else 0o600
        os.chmod(target, mode)
        return
    command = windows_private_acl_command(
        target, _windows_current_user_sid(), is_dir=os.path.isdir(target)
    )
    completed = subprocess.run(
        command, text=True, check=False, **windows_internal_console_run_kwargs()
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"unable to restrict Windows ACL on {target}: {completed.stderr or completed.stdout}"
        )


def ensure_local_directories(cfg) -> None:
    paths = [
        cfg.DATA_DIR,
        cfg.UPLOAD_DIR,
        cfg.REPORTS_DIR,
        cfg.JOBS_DIR,
        cfg.PROJECTS_DIR,
        cfg.LOG_DIR,
    ]
    runtime_root = os.environ.get("MODELA_RUNTIME_ROOT", "").strip()
    if runtime_root:
        paths.insert(0, runtime_root)
    for path in paths:
        os.makedirs(path, mode=0o700, exist_ok=True)
        restrict_private_path(path)
    log_file = os.path.join(cfg.LOG_DIR, "modelapro.log")
    if os.path.isfile(log_file):
        restrict_private_path(log_file)


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
        access_log=False,
        # The windowed PyInstaller entrypoint has no stderr object.  Uvicorn's
        # default formatter calls stderr.isatty() during configuration.
        log_config=None,
    )
    return 0


def main_frontend(argv: Optional[Sequence[str]] = None) -> int:
    cfg = _config()
    os.environ.setdefault("MODELA_API_URL", cfg.API_PUBLIC_URL)
    cmd = frontend_command(frontend_app_path(), cfg.FRONTEND_HOST, cfg.FRONTEND_PORT)
    os.execv(cmd[0], cmd)
    return 0


def _main_frozen_frontend() -> int:
    """Run Streamlit CLI inside the dedicated frozen child process."""
    cfg = _config()
    os.environ.setdefault("MODELA_API_URL", cfg.API_PUBLIC_URL)
    app_path = frontend_app_path()
    sys.argv = frontend_command(app_path, cfg.FRONTEND_HOST, cfg.FRONTEND_PORT)
    # ``frontend_command`` intentionally points back to this executable when
    # frozen, so construct Streamlit's own argv for its in-process CLI here.
    sys.argv = [
        "streamlit",
        *_streamlit_run_arguments(app_path, cfg.FRONTEND_HOST, cfg.FRONTEND_PORT),
    ]
    from streamlit.web import cli as streamlit_cli

    return int(streamlit_cli.main() or 0)


def _terminate(procs: Sequence[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 5
    for proc in procs:
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()


class _WindowsProcessTree:
    """Own frozen service children in a kill-on-close Windows Job Object."""

    _EXTENDED_LIMIT_INFORMATION = 9
    _KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self) -> None:
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            self._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        self._kernel32 = kernel32
        self._handle = handle

    def add(self, process: subprocess.Popen) -> None:
        if not self._handle:
            raise RuntimeError("Windows process tree is already closed")
        process_handle = getattr(process, "_handle", None)
        if process_handle is None or not self._kernel32.AssignProcessToJobObject(
            self._handle, process_handle
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _windows_process_tree() -> Optional[_WindowsProcessTree]:
    return _WindowsProcessTree() if os.name == "nt" else None


def _log_frozen_child_diagnostics(logger, log_dir: Path) -> None:
    """Copy frozen child tracebacks into the parent product log."""
    for diagnostic in sorted(log_dir.glob("frozen-child-error-*.log")):
        try:
            detail = diagnostic.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(
                "Could not read frozen child diagnostic %s: %s", diagnostic, exc
            )
            continue
        logger.error("Frozen child diagnostic %s:\n%s", diagnostic, detail[-12_000:])


def instance_lock_path(cfg) -> Path:
    return Path(cfg.DATA_DIR) / "instance.lock"


def stop_request_path(cfg) -> Path:
    return Path(cfg.DATA_DIR) / "stop-request.json"


def new_instance_id() -> str:
    return uuid.uuid4().hex


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return False
    return True


def pid_image_path(pid: int) -> Optional[str]:
    if pid <= 0:
        return None
    if os.name != "nt":
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value or None
    finally:
        kernel32.CloseHandle(handle)


def _loopback_owner(host: str, port: int) -> Optional[tuple[int, str]]:
    """Return (pid, image) listening on host:port. Never uses netstat/tasklist."""
    if os.name != "nt":
        try:
            hex_port = f"{port:04X}"
            for table in ("/proc/net/tcp", "/proc/net/tcp6"):
                try:
                    lines = Path(table).read_text(encoding="utf-8").splitlines()[1:]
                except OSError:
                    continue
                for line in lines:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local, state, inode = parts[1], parts[3], parts[9]
                    if state != "0A":
                        continue
                    addr, _, phex = local.rpartition(":")
                    if phex.upper() != hex_port:
                        continue
                    pid = _linux_pid_for_inode(inode)
                    if pid:
                        image = pid_image_path(pid) or ""
                        return pid, image
        except Exception:
            return None
        return None
    try:
        pid = _windows_listener_pid(host, port)
    except Exception:
        return None
    if not pid:
        return None
    return pid, pid_image_path(pid) or ""


def _linux_pid_for_inode(inode: str) -> Optional[int]:
    if not inode or inode == "0":
        return None
    needle = f"socket:[{inode}]"
    try:
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            fd_dir = pid_dir / "fd"
            try:
                for fd in fd_dir.iterdir():
                    try:
                        if fd.readlink().as_posix() == needle:
                            return int(pid_dir.name)
                    except OSError:
                        continue
            except OSError:
                continue
    except OSError:
        return None
    return None


def _windows_listener_pid(host: str, port: int) -> Optional[int]:
    from ctypes import wintypes

    class _Row(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

    iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    size = wintypes.DWORD(0)
    AF_INET = 2
    TCP_TABLE_OWNER_PID_LISTENER = 3
    iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(size), True, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0
    )
    buf = ctypes.create_string_buffer(size.value)

    class _Table(ctypes.Structure):
        _fields_ = [("dwNumEntries", wintypes.DWORD), ("table", _Row * 1)]

    if iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(size), True, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0
    ):
        return None
    import socket as _socket

    count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = ctypes.cast(
        ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
        ctypes.POINTER(_Row * max(count, 1)),
    ).contents
    want = socket_addr_to_dword(host)
    for index in range(count):
        row = rows[index]
        local_port = _socket.ntohs(row.dwLocalPort & 0xFFFF)
        if local_port != port:
            continue
        if want is not None and row.dwLocalAddr not in {want, 0}:
            continue
        return int(row.dwOwningPid)
    return None


def socket_addr_to_dword(host: str) -> Optional[int]:
    import socket as _socket

    if host in {"127.0.0.1", "localhost"}:
        return int.from_bytes(_socket.inet_aton("127.0.0.1"), "little")
    try:
        return int.from_bytes(_socket.inet_aton(host), "little")
    except OSError:
        return None


def read_instance_lock(cfg) -> Optional[dict]:
    path = instance_lock_path(cfg)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != INSTANCE_LOCK_SCHEMA:
        return None
    return payload


def write_instance_lock(cfg, payload: Mapping) -> None:
    path = instance_lock_path(cfg)
    tmp = path.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clear_instance_lock(cfg, instance_id: str) -> None:
    path = instance_lock_path(cfg)
    current = read_instance_lock(cfg)
    if current and current.get("instance_id") != instance_id:
        return
    try:
        path.unlink()
    except OSError:
        pass


def consume_stop_request(cfg, instance_id: str) -> Optional[dict]:
    path = stop_request_path(cfg)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != STOP_REQUEST_SCHEMA:
        return None
    requested = str(payload.get("instance_id") or "")
    if requested and requested != instance_id:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return payload


def open_product_browser(url: str) -> bool:
    import webbrowser

    try:
        return bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception:
        return False


def copy_text_to_clipboard(text: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            encoded = (text + "\0").encode("utf-16le")
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            locked = kernel32.GlobalLock(handle)
            ctypes.memmove(locked, encoded, len(encoded))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


def _interactive_desktop() -> bool:
    if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("MODELA_NO_DIALOGS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return os.name == "nt"


def notify_failure(title: str, message: str) -> None:
    if _interactive_desktop():
        try:
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x00000010 | 0x00010000)
            return
        except Exception:
            pass
    if sys.stderr is not None:
        try:
            sys.stderr.write(f"{title}\n{message}\n")
            sys.stderr.flush()
        except OSError:
            pass


def notify_browser_recovery(url: str, message: str) -> None:
    copy_text_to_clipboard(url)
    notify_failure("MODELA PRO — navegador não associado", message)


class _StartupIndicator:
    def __init__(self) -> None:
        self._stop = __import__("threading").Event()
        self._thread = None
        self._hwnd = None

    def start(self, message: str) -> None:
        append_startup_log("startup", message)
        if os.name != "nt":
            if sys.stdout is not None:
                try:
                    sys.stdout.write(message + "\n")
                    sys.stdout.flush()
                except OSError:
                    pass
            return
        threading = __import__("threading")
        self._thread = threading.Thread(target=self._run, args=(message,), daemon=True)
        self._thread.start()

    def _run(self, message: str) -> None:
        try:
            user32 = ctypes.windll.user32
            WS_OVERLAPPED = 0x00CF0000
            WS_EX_TOPMOST = 0x00000008
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST,
                "STATIC",
                "MODELA PRO",
                WS_OVERLAPPED,
                200,
                200,
                480,
                140,
                None,
                None,
                None,
                None,
            )
            if not hwnd:
                append_startup_log("startup-indicator", "CreateWindowExW failed")
                return
            self._hwnd = hwnd
            user32.SetWindowTextW(hwnd, message)
            user32.ShowWindow(hwnd, 5)
            user32.UpdateWindow(hwnd)
            msg = ctypes.create_string_buffer(256)
            while not self._stop.is_set():
                while user32.PeekMessageW(msg, 0, 0, 0, 1):
                    user32.TranslateMessage(msg)
                    user32.DispatchMessageW(msg)
                time.sleep(0.05)
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
                self._hwnd = None
        except Exception as exc:
            append_startup_log("startup-indicator", str(exc))

    def close(self) -> None:
        self._stop.set()
        if os.name == "nt" and self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)
            except Exception:
                pass


def resolve_existing_instance(cfg, our_executable: str):
    lock = read_instance_lock(cfg)
    lock_pid = int(lock.get("pid") or 0) if lock else 0
    running = pid_is_running(lock_pid) if lock_pid else False
    image = pid_image_path(lock_pid) if running else None
    if lock and running and image and not command_is_our_executable(image, our_executable):
        lock_command = image
    elif lock:
        lock_command = str(lock.get("command") or image or "")
    else:
        lock_command = image
    listener = _loopback_owner(cfg.API_HOST, cfg.API_PORT)
    listener_pid, listener_command = (listener if listener else (None, None))
    return evaluate_instance_lock(
        lock,
        our_executable=our_executable,
        lock_pid_running=running,
        lock_pid_command=lock_command,
        listener_pid=listener_pid,
        listener_command=listener_command,
    )


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
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the default browser (automation only; not the interactive default).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    append_startup_log(
        "argv",
        f"frozen={is_frozen_product()} argv={list(argv) if argv is not None else sys.argv!r}",
    )

    if args.internal_api:
        os.environ.setdefault("MODELA_PROCESS_ROLE", "api")
        return main_api([])
    if args.internal_frontend:
        os.environ.setdefault("MODELA_PROCESS_ROLE", "frontend")
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

    return _run_interactive_supervisor(cfg, args)


def _run_interactive_supervisor(cfg, args) -> int:
    from c15_local.pdf_env import probe_weasyprint
    from modules.logging_manager import logger

    os.environ.setdefault("MODELA_PROCESS_ROLE", "supervisor")
    log_hint = str(Path(cfg.LOG_DIR) / "startup.log")
    indicator = _StartupIndicator()
    if not getattr(args, "no_browser", False) and _interactive_desktop():
        indicator.start("MODELA PRO está iniciando…")
    else:
        append_startup_log("startup", "MODELA PRO está iniciando…")
    our_executable = sys.executable
    instance_id = ""
    procs: list[subprocess.Popen] = []
    process_tree = None
    child_logs: list = []

    def fail(stage: str, reason: str, exc: Optional[BaseException] = None) -> int:
        detail = traceback.format_exc() if exc else reason
        path = persist_launch_diagnostic(stage=stage, detail=detail, returncode=1)
        if not getattr(args, "no_browser", False):
            notify_failure(
                "MODELA PRO",
                format_failure_message(stage, reason, str(path or log_hint)),
            )
        elif sys.stderr is not None:
            try:
                sys.stderr.write(format_failure_message(stage, reason, str(path or log_hint)) + "\n")
                sys.stderr.flush()
            except OSError:
                pass
        return 1

    try:
        decision = resolve_existing_instance(cfg, our_executable)
        if decision.action == "conflict":
            indicator.close()
            return fail("porta", decision.reason)
        if decision.action == "reuse":
            lock = decision.lock or {}
            ui_url = str(
                lock.get("ui_url")
                or ui_public_url(
                    cfg.FRONTEND_HOST, cfg.FRONTEND_PORT, str(lock.get("instance_id") or "")
                )
            )
            health = health_url(str(lock.get("api_url") or cfg.API_PUBLIC_URL))
            expected = str(lock.get("instance_id") or "")
            payload = wait_for_health(
                health,
                timeout=args.health_timeout,
                instance_id=expected or None,
                require_instance=bool(expected),
            )
            wait_for_ui(ui_url, timeout=min(args.health_timeout, 30.0))
            logger.info("Reusing instance %s health=%s", expected or payload, payload)
            if should_open_interactive_browser(args):
                append_startup_log("browser", ui_url)
                opened = open_product_browser(ui_url)
                if not opened:
                    notify_browser_recovery(
                        ui_url,
                        format_browser_failure_message(ui_url, log_hint),
                    )
            indicator.close()
            return 0

        pdf = probe_weasyprint()
        if pdf.ok:
            logger.info("PDF environment: %s", pdf.message)
        else:
            logger.warning("PDF environment: %s", pdf.message)

        if cfg.API_HOST in {"0.0.0.0", "::", "[::]"}:
            logger.warning(
                "API_HOST=%s exposes all interfaces; shipped default is 127.0.0.1",
                cfg.API_HOST,
            )

        instance_id = new_instance_id()
        ui_url = ui_public_url(cfg.FRONTEND_HOST, cfg.FRONTEND_PORT, instance_id)
        backend_cmd = backend_command(cfg.API_HOST, cfg.API_PORT)
        frontend_cmd = frontend_command(
            frontend_app_path(), cfg.FRONTEND_HOST, cfg.FRONTEND_PORT
        )
        logger.info("Backend command: %s", " ".join(backend_cmd))
        logger.info("Frontend command: %s", " ".join(frontend_cmd))

        def handle_signal(signum, _frame):
            logger.info("Received signal %s; stopping children", signum)
            _terminate(procs)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, handle_signal)

        env = service_environment(cfg)
        env["MODELA_INSTANCE_ID"] = instance_id
        api_env = dict(env)
        api_env["MODELA_PROCESS_ROLE"] = "api"
        ui_env = dict(env)
        ui_env["MODELA_PROCESS_ROLE"] = "frontend"
        # Windowed children already have no console. CREATE_NO_WINDOW here
        # makes stdout an invalid handle; Streamlit then dies in click.echo
        # (OSError 22) while printing its URL. Log files, not unread pipes.
        api_log = (Path(cfg.LOG_DIR) / "api-child.log").open("ab")
        ui_log = (Path(cfg.LOG_DIR) / "frontend-child.log").open("ab")
        child_logs = [api_log, ui_log]
        process_tree = _windows_process_tree()
        write_instance_lock(
            cfg,
            {
                "schema_version": INSTANCE_LOCK_SCHEMA,
                "pid": os.getpid(),
                "instance_id": instance_id,
                "executable": our_executable,
                "command": " ".join([our_executable, *list(sys.argv[1:])]),
                "api_url": cfg.API_PUBLIC_URL,
                "ui_url": ui_url,
            },
        )
        backend = subprocess.Popen(
            backend_cmd, env=api_env, stdout=api_log, stderr=subprocess.STDOUT
        )
        procs.append(backend)
        if process_tree is not None:
            process_tree.add(backend)
        frontend = subprocess.Popen(
            frontend_cmd, env=ui_env, stdout=ui_log, stderr=subprocess.STDOUT
        )
        procs.append(frontend)
        if process_tree is not None:
            process_tree.add(frontend)
        owned = {"backend": backend, "frontend": frontend}
        payload = wait_for_health(
            health_url(cfg.API_PUBLIC_URL),
            timeout=args.health_timeout,
            processes=owned,
            instance_id=instance_id,
            require_instance=True,
        )
        wait_for_ui(ui_url, timeout=args.health_timeout, processes=owned)
        logger.info("API health %s -> %s", health_url(cfg.API_PUBLIC_URL), payload)
        if sys.stdout is not None:
            print(f"API: {cfg.API_PUBLIC_URL}  (health {payload})")
            print(f"UI:  {ui_url}")
            print("Encerre pelo controle Encerrar MODELA PRO na interface. Redis is not required.")
        if should_open_interactive_browser(args):
            append_startup_log("browser", ui_url)
            opened = open_product_browser(ui_url)
            if not opened:
                notify_browser_recovery(
                    ui_url,
                    format_browser_failure_message(ui_url, log_hint),
                )
        indicator.close()
        while True:
            if backend.poll() is not None:
                code = backend.returncode or 1
                persist_launch_diagnostic(
                    stage="backend",
                    detail=f"backend exited {code}",
                    returncode=code,
                )
                _terminate(procs)
                notify_failure(
                    "MODELA PRO",
                    format_failure_message(
                        "api",
                        f"O serviço da API encerrou (código {code}).",
                        log_hint,
                    ),
                )
                return code
            if frontend.poll() is not None:
                code = frontend.returncode or 1
                persist_launch_diagnostic(
                    stage="frontend",
                    detail=f"frontend exited {code}",
                    returncode=code,
                )
                _terminate(procs)
                notify_failure(
                    "MODELA PRO",
                    format_failure_message(
                        "interface",
                        f"O serviço da interface encerrou (código {code}).",
                        log_hint,
                    ),
                )
                return code
            if consume_stop_request(cfg, instance_id):
                logger.info("Stop requested for instance %s", instance_id)
                _terminate(procs)
                return 0
            time.sleep(0.5)
    except Exception as exc:
        _terminate(procs)
        try:
            from modules.logging_manager import logger as _logger

            _log_frozen_child_diagnostics(_logger, Path(cfg.LOG_DIR))
        except Exception:
            pass
        indicator.close()
        return fail("inicialização", str(exc), exc)
    finally:
        _terminate(procs)
        if process_tree is not None:
            process_tree.close()
        for handle in child_logs:
            try:
                handle.close()
            except OSError:
                pass
        if instance_id:
            clear_instance_lock(cfg, instance_id)
        indicator.close()


def _entrypoint(run=main) -> int:
    """Turn frozen child failures into stderr and an observable exit code."""
    append_startup_log("entrypoint", "begin")
    try:
        return run()
    except Exception:
        detail = traceback.format_exc()
        if sys.stderr is not None:
            try:
                sys.stderr.write(detail)
                sys.stderr.flush()
            except OSError:
                pass
        path = persist_launch_diagnostic(stage="entrypoint", detail=detail, returncode=1)
        if path is None and sys.stderr is None:
            # Last resort: still never send the only traceback to DEVNULL.
            try:
                fallback = bootstrap_log_dir() / f"frozen-child-error-{os.getpid()}.log"
                fallback.write_text(f"command={sys.argv!r}\n{detail}", encoding="utf-8")
            except OSError:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
