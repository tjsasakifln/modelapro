"""Interactive launch policy: browser after instance-ready, no-window tools, reuse."""

from __future__ import annotations

import subprocess
import urllib.request
from types import SimpleNamespace

import pytest

from c15_local import launcher as launcher_module
from c15_local.interactive_launch import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    DETACHED_PROCESS,
    InstanceDecision,
    evaluate_instance_lock,
    format_browser_failure_message,
    format_failure_message,
    health_matches_instance,
    should_open_interactive_browser,
    ui_public_url,
    windows_internal_child_popen_kwargs,
    windows_internal_console_creationflags,
    windows_internal_console_run_kwargs,
)
from c15_local.launcher import wait_for_health


class _FakeProc:
    def __init__(self):
        self._handle = 1
        self.pid = 11
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = 1


def _args(**overrides):
    values = dict(
        health_timeout=5.0,
        no_browser=False,
        internal_api=False,
        internal_frontend=False,
        print_commands=False,
        check_pdf=False,
        api_only=False,
        frontend_only=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_internal_console_flags_are_create_no_window_without_conflicts(monkeypatch):
    monkeypatch.setattr("c15_local.interactive_launch.os.name", "nt")
    flags = windows_internal_console_creationflags()
    assert flags == CREATE_NO_WINDOW
    assert not flags & CREATE_NEW_CONSOLE
    assert not flags & DETACHED_PROCESS
    kwargs = windows_internal_console_run_kwargs()
    assert kwargs["creationflags"] == flags
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert "capture_output" not in kwargs
    child = windows_internal_child_popen_kwargs()
    assert child["creationflags"] == flags
    assert child["stdin"] is subprocess.DEVNULL
    assert "stdout" not in child


def test_whoami_uses_no_window_kwargs_and_keeps_return_codes(monkeypatch):
    observed = []

    def fake_run(command, **kwargs):
        observed.append((list(command), dict(kwargs)))
        return subprocess.CompletedProcess(
            command, 0, stdout='"tj","S-1-5-21-1-2-3-1001"\n', stderr=""
        )

    monkeypatch.setattr(launcher_module.os, "name", "nt")
    monkeypatch.setattr("c15_local.interactive_launch.os.name", "nt")
    monkeypatch.setattr(launcher_module.subprocess, "run", fake_run)
    sid = launcher_module._windows_current_user_sid()
    assert sid == "S-1-5-21-1-2-3-1001"
    command, kwargs = observed[0]
    assert command[:2] == ["whoami", "/user"]
    assert kwargs["creationflags"] == windows_internal_console_creationflags()
    assert not kwargs["creationflags"] & CREATE_NEW_CONSOLE
    assert not kwargs["creationflags"] & DETACHED_PROCESS
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "capture_output" not in kwargs
    assert kwargs.get("shell") not in {True, "True"}


def test_should_open_browser_only_for_interactive_parent():
    assert should_open_interactive_browser(_args()) is True
    assert should_open_interactive_browser(_args(internal_api=True)) is False
    assert should_open_interactive_browser(_args(internal_frontend=True)) is False
    assert should_open_interactive_browser(_args(print_commands=True)) is False
    assert should_open_interactive_browser(_args(check_pdf=True)) is False
    assert should_open_interactive_browser(_args(api_only=True)) is False
    assert should_open_interactive_browser(_args(frontend_only=True)) is False
    assert should_open_interactive_browser(_args(no_browser=True)) is False


def test_health_matches_instance_rejects_foreign_http_200():
    assert health_matches_instance(
        {"status": "healthy", "instance_id": "ours"}, "ours", require_instance=True
    )
    assert not health_matches_instance(
        {"status": "healthy"}, "ours", require_instance=True
    )
    assert not health_matches_instance(
        {"status": "healthy", "instance_id": "other"}, "ours", require_instance=True
    )


def test_wait_for_health_rejects_foreign_instance(monkeypatch):
    class _Resp:
        status = 200

        def read(self):
            return b'{"status":"healthy"}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    with pytest.raises(TimeoutError, match="identity mismatch"):
        wait_for_health(
            "http://127.0.0.1:9/health",
            timeout=0.4,
            instance_id="ours",
            require_instance=True,
        )


def test_evaluate_instance_lock_reuse_stale_and_foreign():
    exe = r"C:\Users\tj_sa\MODELA PRO\MODELA-PRO.exe"
    live = {
        "schema_version": "MP-INSTANCE-LOCK/1",
        "pid": 20892,
        "instance_id": "abc",
        "command": f'"{exe}"',
        "ui_url": "http://127.0.0.1:8501/?instance=abc",
    }
    reuse = evaluate_instance_lock(
        live,
        our_executable=exe,
        lock_pid_running=True,
        lock_pid_command=f'"{exe}"',
        listener_pid=20112,
        listener_command=f"{exe} --internal-api",
    )
    assert reuse.action == "reuse"

    stale = evaluate_instance_lock(
        live,
        our_executable=exe,
        lock_pid_running=False,
        lock_pid_command=f'"{exe}"',
        listener_pid=None,
        listener_command=None,
    )
    assert stale.action == "start_new"
    assert "stale" in stale.reason

    recycled = evaluate_instance_lock(
        live,
        our_executable=exe,
        lock_pid_running=True,
        lock_pid_command=r"C:\Windows\System32\notepad.exe",
        listener_pid=None,
        listener_command=None,
    )
    assert recycled.action == "start_new"
    assert "not killed" in recycled.reason

    foreign = evaluate_instance_lock(
        None,
        our_executable=exe,
        lock_pid_running=False,
        lock_pid_command=None,
        listener_pid=444,
        listener_command=r"C:\Windows\System32\notepad.exe",
    )
    assert foreign.action == "conflict"
    assert "444" in foreign.reason


def test_our_listener_is_reused_even_without_lock():
    exe = r"C:\install\MODELA-PRO.exe"
    adopted = evaluate_instance_lock(
        None,
        our_executable=exe,
        lock_pid_running=False,
        lock_pid_command=None,
        listener_pid=3300,
        listener_command=f"{exe} --internal-frontend",
    )
    assert adopted.action == "reuse"


def _patch_supervisor_io(monkeypatch, tmp_path, *, opened, order, popens):
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(tmp_path))
    (tmp_path / "store").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "18000")
    monkeypatch.setenv("API_PUBLIC_URL", "http://127.0.0.1:18000")
    monkeypatch.setenv("FRONTEND_HOST", "127.0.0.1")
    monkeypatch.setenv("FRONTEND_PORT", "18501")
    monkeypatch.setattr(launcher_module, "new_instance_id", lambda: "inst-test")
    monkeypatch.setattr(launcher_module, "ensure_local_directories", lambda cfg: None)
    monkeypatch.setattr("modules.operacao_local.runtime.get_security_policy", lambda: object())
    monkeypatch.setattr(
        "c15_local.pdf_env.probe_weasyprint",
        lambda: SimpleNamespace(ok=True, message="ok"),
    )
    monkeypatch.setattr(
        launcher_module.subprocess,
        "Popen",
        lambda cmd, **kwargs: popens.append((list(cmd), dict(kwargs))) or _FakeProc(),
    )
    monkeypatch.setattr(launcher_module, "_windows_process_tree", lambda: None)
    monkeypatch.setattr(launcher_module._StartupIndicator, "start", lambda self, msg: None)
    monkeypatch.setattr(launcher_module._StartupIndicator, "close", lambda self: None)
    monkeypatch.setattr(launcher_module, "notify_failure", lambda *a, **k: None)
    monkeypatch.setattr(launcher_module, "notify_browser_recovery", lambda *a, **k: None)

    def fake_health(url, timeout=30, **kwargs):
        order.append(("health", url, kwargs.get("instance_id"), kwargs.get("require_instance")))
        return {"status": "healthy", "instance_id": kwargs.get("instance_id") or "inst-test"}

    def fake_ui(url, timeout=30, **kwargs):
        order.append(("ui", url))
        return b"ok"

    def fake_open(url):
        order.append(("browser", url))
        opened.append(url)
        return True

    monkeypatch.setattr(launcher_module, "wait_for_health", fake_health)
    monkeypatch.setattr(launcher_module, "wait_for_ui", fake_ui)
    monkeypatch.setattr(launcher_module, "open_product_browser", fake_open)
    monkeypatch.setattr(
        launcher_module,
        "consume_stop_request",
        lambda cfg, iid: {"instance_id": iid},
    )


def test_interactive_parent_opens_browser_only_after_instance_ready(tmp_path, monkeypatch):
    opened: list[str] = []
    order: list[tuple] = []
    popens: list[tuple] = []
    _patch_supervisor_io(monkeypatch, tmp_path, opened=opened, order=order, popens=popens)
    monkeypatch.setattr(
        launcher_module,
        "resolve_existing_instance",
        lambda cfg, exe: InstanceDecision("start_new", "no live instance", None),
    )
    from modules.config_manager import build_config

    rc = launcher_module._run_interactive_supervisor(build_config(), _args())
    assert rc == 0
    assert [item[0] for item in order[:3]] == ["health", "ui", "browser"]
    assert order[0][2] == "inst-test"
    assert order[0][3] is True
    expected = ui_public_url("127.0.0.1", 18501, "inst-test")
    assert opened == [expected]
    assert order[2][1] == expected
    assert popens
    for _cmd, kwargs in popens:
        assert kwargs.get("stdin") is subprocess.DEVNULL


def test_no_browser_flag_does_not_open(tmp_path, monkeypatch):
    opened: list[str] = []
    order: list[tuple] = []
    popens: list[tuple] = []
    _patch_supervisor_io(monkeypatch, tmp_path, opened=opened, order=order, popens=popens)
    monkeypatch.setattr(
        launcher_module,
        "resolve_existing_instance",
        lambda cfg, exe: InstanceDecision("start_new", "no live instance", None),
    )
    from modules.config_manager import build_config

    rc = launcher_module._run_interactive_supervisor(build_config(), _args(no_browser=True))
    assert rc == 0
    assert opened == []
    assert "browser" not in [item[0] for item in order]


def test_internal_roles_do_not_open_browser_or_supervisor(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        launcher_module, "open_product_browser", lambda url: opened.append(url) or True
    )
    monkeypatch.setattr(launcher_module, "main_api", lambda argv=None: 17)
    monkeypatch.setattr(launcher_module, "_main_frozen_frontend", lambda: 18)
    monkeypatch.setattr(launcher_module, "_run_interactive_supervisor", lambda *a, **k: 99)
    assert launcher_module.main(["--internal-api"]) == 17
    assert launcher_module.main(["--internal-frontend"]) == 18
    assert opened == []


def test_second_start_reuses_without_new_tree(tmp_path, monkeypatch):
    opened: list[str] = []
    order: list[tuple] = []
    popens: list[tuple] = []
    _patch_supervisor_io(monkeypatch, tmp_path, opened=opened, order=order, popens=popens)
    ui = "http://127.0.0.1:18501/?instance=abc"
    monkeypatch.setattr(
        launcher_module,
        "resolve_existing_instance",
        lambda cfg, exe: InstanceDecision(
            "reuse",
            "legitimate supervisor still running",
            {
                "instance_id": "abc",
                "api_url": "http://127.0.0.1:18000",
                "ui_url": ui,
            },
        ),
    )
    from modules.config_manager import build_config

    rc = launcher_module._run_interactive_supervisor(build_config(), _args())
    assert rc == 0
    assert popens == []
    assert opened == [ui]
    assert order[0][0] == "health"
    assert order[1][0] == "ui"
    assert order[2][0] == "browser"


def test_failure_message_is_portuguese_and_points_to_log():
    text = format_failure_message("porta", "ocupada por outro programa", r"C:\logs\startup.log")
    assert "Etapa: porta" in text
    assert "ocupada por outro programa" in text
    assert "startup.log" in text
    recovery = format_browser_failure_message("http://127.0.0.1:8501/?instance=x", "log")
    assert "http://127.0.0.1:8501/?instance=x" in recovery
    assert "navegador" in recovery.lower()


def test_iss_opens_installed_exe_after_setup():
    iss = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "packaging"
        / "comercial"
        / "modelapro.iss"
    )
    text = iss.read_text(encoding="utf-8")
    assert r"{app}\MODELA-PRO.exe" in text
    assert "[Run]" in text
    assert "nowait postinstall" in text
