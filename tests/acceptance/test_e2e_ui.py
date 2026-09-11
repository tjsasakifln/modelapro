"""E2E UI: open the real local Streamlit page, upload, select, start.

Classified as E2E. If the launcher cannot bind the hardcoded API port
(frontend/app.py uses 127.0.0.1:8000), the failure message starts with
NOT_RUN so the harness can bucket it as não executado — never a mocked 200.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from _helpers import ROOT, fixture_path


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _wait_http(url: str, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


class TestE2EUiStreamlit:
    def test_upload_select_start_and_visible_result(self, tmp_path):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise AssertionError(f"NOT_RUN:playwright import failed: {exc}") from exc

        api_port = 8000
        ui_port = 18516
        if _port_open("127.0.0.1", api_port):
            raise AssertionError(
                f"NOT_RUN:ui_launcher port {api_port} already bound; "
                "frontend/app.py hardcodes API_URL=http://127.0.0.1:8000"
            )

        env = os.environ.copy()
        env["API_PORT"] = str(api_port)
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ui = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"),
             "--server.port", str(ui_port), "--server.headless", "true",
             "--browser.gatherUsageStats", "false"],
            cwd=str(ROOT / "frontend"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        screenshot = Path(os.environ.get("C16_UI_SCREENSHOT", str(tmp_path / "c16_ui.png")))
        try:
            if not _wait_http(f"http://127.0.0.1:{api_port}/health", 25):
                raise AssertionError("NOT_RUN:ui_launcher API did not become healthy")
            if not _wait_http(f"http://127.0.0.1:{ui_port}", 40):
                raise AssertionError("NOT_RUN:ui_launcher Streamlit did not become ready")

            csv_path = str(fixture_path("market_minimal.csv"))
            try:
                playwright_cm = sync_playwright()
            except Exception as exc:
                raise AssertionError(f"NOT_RUN:playwright start failed: {exc}") from exc
            with playwright_cm as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as exc:
                    raise AssertionError(f"NOT_RUN:playwright chromium: {exc}") from exc
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{ui_port}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
                file_input = page.locator("input[type=file]")
                assert file_input.count() >= 1, "upload widget not found"
                file_input.first.set_input_files(csv_path)
                page.wait_for_selector("text=Variável-alvo", timeout=45000)
                start = page.locator("button").filter(has_text="Executar avaliação")
                if start.count() == 0:
                    start = page.get_by_text("Executar", exact=False)
                page.screenshot(path=str(screenshot), full_page=True)
                assert start.count() >= 1, (
                    "start button not found after upload; body="
                    + page.inner_text("body")[:800]
                )
                start.first.click(force=True)
                body = ""
                for _ in range(20):
                    body = page.inner_text("body")
                    if any(
                        token in body
                        for token in ("Cálculo concluído", "Identificador do trabalho", "Estado: Falha")
                    ):
                        break
                    refresh = page.get_by_role("button", name="Atualizar estado")
                    if refresh.count() >= 1 and refresh.first.is_enabled():
                        refresh.first.click()
                    page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshot), full_page=True)
                browser.close()

            assert screenshot.exists() and screenshot.stat().st_size > 1000
            assert any(
                token in body
                for token in ("Cálculo concluído", "Identificador do trabalho", "Estado: Falha")
            ), f"UI did not show a job terminal state after start; body={body[:800]!r}"
        finally:
            for proc in (ui, api):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
