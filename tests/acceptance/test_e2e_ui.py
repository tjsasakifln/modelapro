"""E2E UI: real Streamlit + API on loopback, download PDF, check analytic point.

Classified as E2E. API URL is MODELA_API_URL on a free loopback pair (not
port 8000). If the launcher cannot start, the failure message starts with
NOT_RUN so the harness can bucket it as não executado — never a mocked 200.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from _helpers import ROOT

UNIQUE_AREA = 73.5
EXPECTED_POINT = 735000.0  # 10000 × 73.5; not on the 50,52,… sample grid
# Avoid 8000: this environment blackholes it, and frontend reads MODELA_API_URL.
_API_PORT_RANGE = range(18100, 18180, 2)


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_ports():
    for api_port in _API_PORT_RANGE:
        ui_port = api_port + 1
        if _port_free(api_port) and _port_free(ui_port):
            return api_port, ui_port
    raise AssertionError("NOT_RUN:no free loopback ports in 18100-18180")


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


def _copy_evidence(src: Path, name: str) -> None:
    dest_root = os.environ.get("C17_UI_EVIDENCE")
    if not dest_root:
        return
    dest = Path(dest_root)
    dest.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dest / name)


class TestE2EUiStreamlit:
    def test_upload_select_start_and_visible_result(self, tmp_path):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise AssertionError(f"NOT_RUN:playwright import failed: {exc}") from exc

        api_port, ui_port = _pick_ports()

        from tests.c17_integration.helpers import (
            analytic_linear_csv,
            analytic_linear_sample_areas,
            assert_pdf_conclusion_point,
        )

        assert UNIQUE_AREA not in analytic_linear_sample_areas(n=24)
        csv_path = tmp_path / "mercado.csv"
        csv_path.write_bytes(analytic_linear_csv(n=24, tag="UI"))

        screenshot = Path(os.environ.get("C16_UI_SCREENSHOT", str(tmp_path / "c16_ui.png")))
        trace_zip = tmp_path / "pw_trace.zip"
        har_path = tmp_path / "ui.har"
        pdf_path = tmp_path / "report.pdf"

        env = os.environ.copy()
        env["MODELA_API_URL"] = f"http://127.0.0.1:{api_port}"
        env["MODELA_API_TIMEOUT"] = "120"
        env["MODELA_SKIP_DOTENV"] = "1"
        env["MODELA_STORE_ROOT"] = str(tmp_path / "ui-store")
        env.pop("PYTHONPATH", None)

        api_log = (tmp_path / "api.log").open("w", encoding="utf-8")
        ui_log = (tmp_path / "ui.log").open("w", encoding="utf-8")
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=str(ROOT),
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        ui = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"),
             "--server.port", str(ui_port), "--server.headless", "true",
             "--browser.gatherUsageStats", "false"],
            cwd=str(ROOT),
            env=env,
            stdout=ui_log,
            stderr=subprocess.STDOUT,
        )
        page_errors: list[str] = []
        try:
            if not _wait_http(f"http://127.0.0.1:{api_port}/health", 40):
                api_log.flush()
                tail = Path(api_log.name).read_text(encoding="utf-8")[-1500:]
                raise AssertionError("NOT_RUN:ui_launcher API did not become healthy\n" + tail)
            if not _wait_http(f"http://127.0.0.1:{ui_port}", 40):
                ui_log.flush()
                tail = Path(ui_log.name).read_text(encoding="utf-8")[-1500:]
                raise AssertionError("NOT_RUN:ui_launcher Streamlit did not become ready\n" + tail)

            try:
                playwright_cm = sync_playwright()
            except Exception as exc:
                raise AssertionError(f"NOT_RUN:playwright start failed: {exc}") from exc
            with playwright_cm as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as exc:
                    raise AssertionError(f"NOT_RUN:playwright chromium: {exc}") from exc
                context = browser.new_context(
                    accept_downloads=True,
                    viewport={"width": 1366, "height": 900},
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                page.on("pageerror", lambda err: page_errors.append(str(err)))
                page.goto(f"http://127.0.0.1:{ui_port}", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
                page.locator("input[type=file]").first.set_input_files(str(csv_path))
                page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=45000)
                page.wait_for_selector("text=1. Preparação da amostra", timeout=15000)

                area = page.get_by_placeholder("ex.: 73,5")
                assert area.count() >= 1, (
                    "subject area field not found; body=" + page.inner_text("body")[:1200]
                )
                area.first.click()
                area.first.press("Control+A")
                page.keyboard.type("73,5", delay=80)
                page.keyboard.press("Tab")
                page.wait_for_timeout(400)

                start = page.get_by_role("button", name="Executar avaliação")
                if start.count() < 1:
                    start = page.locator("button[type='submit']").filter(has_text="Executar")
                assert start.count() >= 1, "form submit not found; body=" + page.inner_text("body")[:800]
                start.first.click()

                body = ""
                retried = False
                for _ in range(40):
                    body = page.inner_text("body")
                    if ("Valor da avaliação" in body or "Cálculo disponível" in body) and (
                        "735.000,00" in body or "735000" in body or "735.000" in body
                    ):
                        break
                    if (
                        not retried
                        and "Estado: Falha" in body
                        and "Característica 'area' ausente" not in body
                    ):
                        again = page.locator("button[type='submit']").filter(has_text="Executar")
                        if again.count() >= 1 and again.first.is_enabled():
                            again.first.click()
                            retried = True
                    refresh = page.get_by_role("button", name="Atualizar estado")
                    if refresh.count() >= 1 and refresh.first.is_enabled():
                        refresh.first.click()
                    page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshot), full_page=True)
                (tmp_path / "ui_body.txt").write_text(body, encoding="utf-8")
                _copy_evidence(tmp_path / "ui_body.txt", "ui_body.txt")
                _copy_evidence(tmp_path / "api.log", "ui_api.log")
                assert "Valor da avaliação" in body or "Cálculo disponível" in body, (
                    "UI did not reach a completed calculation; body=" + body[:2000]
                )
                assert "735.000,00" in body or "735000" in body, body[:1200]

                # Snapshot is persisted before PDF render finishes; keep
                # polling until the artifact is ready (or failed).
                download_btn = page.get_by_role("button", name="Baixar report.pdf")
                pdf_failed = False
                for _ in range(45):
                    body = page.inner_text("body")
                    if (
                        "Baixar cálculo (o PDF falhou)" in body
                        or "Documento PDF indisponível" in body
                    ):
                        pdf_failed = True
                        break
                    download_btn = page.get_by_role("button", name="Baixar report.pdf")
                    if download_btn.count() >= 1:
                        break
                    refresh = page.get_by_role("button", name="Atualizar estado")
                    if refresh.count() >= 1 and refresh.first.is_enabled():
                        refresh.first.click()
                    page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshot), full_page=True)
                (tmp_path / "ui_body.txt").write_text(body, encoding="utf-8")
                assert not pdf_failed, "PDF generation failed; body=" + body[:2000]
                assert download_btn.count() >= 1, "PDF download control missing; body=" + body[:2000]
                transfer = page.get_by_role("button", name="Transferência de report.pdf")
                for _ in range(12):
                    if transfer.count() >= 1:
                        break
                    baixar = page.get_by_role("button", name="Baixar report.pdf")
                    if baixar.count() >= 1:
                        baixar.first.click()
                    page.wait_for_timeout(1500)
                if transfer.count() < 1:
                    transfer = page.get_by_role("link", name="Transferência de report.pdf")
                assert transfer.count() >= 1, (
                    "Transferência de report.pdf missing; body=" + page.inner_text("body")[:2000]
                )
                with page.expect_download(timeout=30000) as pending:
                    transfer.first.click()
                download = pending.value
                download.save_as(str(pdf_path))
                context.tracing.stop(path=str(trace_zip))
                context.close()
                browser.close()

            assert not page_errors, page_errors
            assert pdf_path.exists() and pdf_path.stat().st_size > 1000
            assert pdf_path.read_bytes()[:4] == b"%PDF"
            assert_pdf_conclusion_point(pdf_path.read_bytes(), EXPECTED_POINT)
            _copy_evidence(screenshot, "c16_ui.png")
            _copy_evidence(trace_zip, "pw_trace.zip")
            _copy_evidence(har_path, "ui.har")
            _copy_evidence(pdf_path, "report.pdf")
        finally:
            for proc, log in ((ui, ui_log), (api, api_log)):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log.close()
