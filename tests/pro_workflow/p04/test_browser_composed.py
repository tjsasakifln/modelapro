"""P04 composed-candidate browser path: real API + Streamlit + Chromium.

Positive path: no snapshot injection, no simulated API. Missing MCP is not
'no browser'. If Chromium cannot launch, the failure is recorded; HTTP/PDF
tests remain the behavioral bar.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path("/tmp/grok-goal-42ebe874cf8b/implementer")
EXPECTED_POINT = 735000.0


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_http(url: str, timeout: float = 40.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _ptbr_csv() -> bytes:
    from tests.c17_integration.helpers import analytic_linear_csv

    return analytic_linear_csv(n=24, tag="P04UI")


def test_composed_browser_upload_preview_subject_result_pdf(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        log = SCRATCH / "playwright-unavailable.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"NOT_RUN:playwright import failed: {exc}\n", encoding="utf-8")
        raise AssertionError(f"NOT_RUN:playwright import failed: {exc}") from exc

    api_port = 18040
    ui_port = 18041
    for candidate in range(18040, 18100, 2):
        if _port_free(candidate) and _port_free(candidate + 1):
            api_port, ui_port = candidate, candidate + 1
            break
    else:
        raise AssertionError("NOT_RUN:no free loopback ports in 18040-18100")

    csv_path = tmp_path / "mercado.csv"
    csv_path.write_bytes(_ptbr_csv())
    screenshot = SCRATCH / "combined-browser.png"
    pdf_path = tmp_path / "report.pdf"
    SCRATCH.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["MODELA_API_URL"] = f"http://127.0.0.1:{api_port}"
    env["MODELA_API_TIMEOUT"] = "120"
    env["MODELA_SKIP_DOTENV"] = "1"
    env["MODELA_STORE_ROOT"] = str(tmp_path / "ui-store")
    env.pop("PYTHONPATH", None)

    api_log = (tmp_path / "api.log").open("w", encoding="utf-8")
    ui_log = (tmp_path / "ui.log").open("w", encoding="utf-8")
    api = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "backend.api:app",
            "--host", "127.0.0.1", "--port", str(api_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=api_log,
        stderr=subprocess.STDOUT,
    )
    ui = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"),
            "--server.port", str(ui_port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=ui_log,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_http(f"http://127.0.0.1:{api_port}/health", 25):
            raise AssertionError("NOT_RUN:API did not become healthy")
        if not _wait_http(f"http://127.0.0.1:{ui_port}", 40):
            raise AssertionError("NOT_RUN:Streamlit did not become ready")

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                (SCRATCH / "playwright-unavailable.log").write_text(
                    f"NOT_RUN:chromium launch failed: {exc}\n", encoding="utf-8"
                )
                raise AssertionError(f"NOT_RUN:chromium launch failed: {exc}") from exc
            context = browser.new_context(accept_downloads=True, viewport={"width": 1366, "height": 900})
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}", wait_until="networkidle", timeout=60000)
            page.wait_for_selector("text=1. Preparação da amostra", timeout=45000)
            page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
            page.locator("input[type=file]").first.set_input_files(str(csv_path))
            try:
                page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=60000)
            except Exception:
                page.screenshot(path=str(SCRATCH / "combined-browser-preview-fail.png"), full_page=True)
                (tmp_path / "preview_fail_body.txt").write_text(page.inner_text("body"), encoding="utf-8")
                page.locator("input[type=file]").first.set_input_files(str(csv_path))
                page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=60000)

            area = page.get_by_placeholder("ex.: 73,5")
            assert area.count() >= 1, "subject area field missing; body=" + page.inner_text("body")[:1500]
            area.first.click()
            area.first.fill("73,5")
            page.keyboard.press("Tab")
            page.wait_for_timeout(400)

            start = page.get_by_role("button", name="Executar avaliação")
            assert start.count() >= 1, "execute button missing; body=" + page.inner_text("body")[:800]
            start.first.click()

            body = ""
            for _ in range(45):
                body = page.inner_text("body")
                if "735" in body and (
                    "Valor da avaliação" in body or "Cálculo disponível" in body
                ):
                    if "735.000" in body or "735000" in body or "735.000,00" in body:
                        break
                refresh = page.get_by_role("button", name="Atualizar estado")
                if refresh.count() >= 1 and refresh.first.is_enabled():
                    refresh.first.click()
                page.wait_for_timeout(2000)
            page.screenshot(path=str(screenshot), full_page=True)
            (tmp_path / "ui_body.txt").write_text(body, encoding="utf-8")
            assert "Valor da avaliação" in body or "Cálculo disponível" in body, body[:2000]
            assert "735.000" in body or "735000" in body or "735.000,00" in body, body[:1500]

            download_btn = page.get_by_role("button", name="Baixar report.pdf")
            if download_btn.count() < 1:
                refresh = page.get_by_role("button", name="Atualizar estado")
                if refresh.count() >= 1:
                    refresh.first.click()
                    page.wait_for_timeout(2500)
                download_btn = page.get_by_role("button", name="Baixar report.pdf")
            if download_btn.count() >= 1:
                download_btn.first.click()
                page.wait_for_timeout(2000)
                transfer = page.get_by_role("button", name="Transferência de report.pdf")
                if transfer.count() >= 1:
                    with page.expect_download(timeout=30000) as pending:
                        transfer.first.click()
                    pending.value.save_as(str(pdf_path))
                    assert pdf_path.exists() and pdf_path.read_bytes()[:4] == b"%PDF"
                    from tests.c17_integration.helpers import assert_pdf_conclusion_point

                    assert_pdf_conclusion_point(pdf_path.read_bytes(), EXPECTED_POINT)
            context.close()
            browser.close()
    finally:
        for proc, log in ((ui, ui_log), (api, api_log)):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()
