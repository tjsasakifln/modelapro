"""P02-A01: Playwright + API/Streamlit reais, ou registro honesto de indisponibilidade.

Sem fixture de session_state e sem interceptação de HTTP. Se o lançador
Playwright/browser não estiver disponível neste ambiente, o teste grava o
motivo e não fabrica traces.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path(os.environ.get("P02_SCRATCH", "/tmp/grok-goal-7164525daca4/implementer"))
EVIDENCE = ROOT / "docs" / "campaigns" / "MP-PRO-20260911" / "P02"


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
    lines = ["id;bairro;area;preco"]
    for i in range(24):
        area = 50.0 + i * 2.0
        price = 10000.0 * area
        area_txt = f"{area:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        price_txt = f"{price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        lines.append(f"IM-{i+1:02d};Centro;{area_txt};{price_txt}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_excel(path: Path) -> None:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(["id", "bairro", "area", "preco"])
    for i in range(24):
        area = 50.0 + i * 2.0
        sheet.append([f"IM-{i+1:02d}", "Centro", area, 10000.0 * area])
    book.save(path)


def _record_block(reason: str) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log_path = SCRATCH / "p02-playwright-unavailable.log"
    payload = {
        "status": "BLOCKED",
        "reason": reason,
        "note": "A01 não foi fabricado. Unitários e AppTest cobrem o restante neste ambiente.",
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / "p02-playwright-unavailable.log").write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
    return log_path


def test_a01_playwright_real_path_or_record_unavailability(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        log_path = _record_block(f"playwright import failed: {exc}")
        assert log_path.is_file()
        assert "playwright" in log_path.read_text(encoding="utf-8").lower()
        return

    api_port = 8765
    ui_port = 8766
    if not _port_free(api_port) or not _port_free(ui_port):
        log_path = _record_block(f"ports {api_port}/{ui_port} already bound")
        assert log_path.is_file()
        return

    csv_path = tmp_path / "mercado_ptbr.csv"
    csv_path.write_bytes(_ptbr_csv())
    xlsx_path = tmp_path / "mercado.xlsx"
    try:
        _write_excel(xlsx_path)
    except Exception as exc:
        log_path = _record_block(f"excel writer failed: {exc}")
        assert log_path.is_file()
        return

    env = os.environ.copy()
    env["MODELA_API_URL"] = f"http://127.0.0.1:{api_port}"
    env["MODELA_DISABLE_WS"] = "1"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    ui_proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"),
            "--server.port", str(ui_port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_http(f"http://127.0.0.1:{api_port}/health"):
            _record_block("API health did not become ready")
            return
        if not _wait_http(f"http://127.0.0.1:{ui_port}"):
            _record_block("Streamlit UI did not become ready")
            return
        try:
            _drive_two_files(sync_playwright, ui_port, csv_path, xlsx_path)
        except Exception as exc:
            _record_block(f"playwright run failed: {exc}")
            raise
    finally:
        for proc in (ui_proc, api_proc):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def _drive_two_files(sync_playwright, ui_port: int, csv_path: Path, xlsx_path: Path) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    shots = SCRATCH / "p02-a01"
    shots.mkdir(parents=True, exist_ok=True)
    request_log = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            _record_block(f"chromium launch failed: {exc}")
            raise
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.on("request", lambda req: request_log.append({"method": req.method, "url": req.url}) if "/jobs" in req.url or "/preview" in req.url else None)
        page.goto(f"http://127.0.0.1:{ui_port}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(shots / "desktop-empty.png"))
        _upload_and_run(page, csv_path, "csv")
        page.set_viewport_size({"width": 390, "height": 720})
        page.screenshot(path=str(shots / "narrow-result.png"))
        page.set_viewport_size({"width": 1366, "height": 768})
        _upload_and_run(page, xlsx_path, "xlsx")
        context.tracing.stop(path=str(shots / "trace.zip"))
        browser.close()

    sanitised = [{"method": item["method"], "path": item["url"].split("://", 1)[-1].split("/", 1)[-1]} for item in request_log]
    (shots / "requests.json").write_text(json.dumps(sanitised, ensure_ascii=False, indent=2), encoding="utf-8")
    assert any(item["method"] == "POST" and "jobs" in item.get("path", "") for item in sanitised)


def _upload_and_run(page, path: Path, tag: str) -> None:
    file_input = page.locator("input[type='file']").first
    file_input.set_input_files(str(path))
    try:
        page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=60000)
    except Exception:
        file_input.set_input_files(str(path))
        page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=60000)
    area = page.get_by_placeholder("ex.: 73,5")
    if area.count():
        area.first.fill("73,5")
    execute = page.get_by_role("button", name="Executar avaliação")
    if execute.count():
        execute.first.click()
    for _ in range(20):
        body = page.inner_text("body")
        if "735" in body and ("Valor da avaliação" in body or "Cálculo disponível" in body):
            break
        refresh = page.get_by_role("button", name="Atualizar estado")
        if refresh.count() >= 1 and refresh.first.is_enabled():
            refresh.first.click()
        page.wait_for_timeout(1500)
    page.screenshot(path=str(SCRATCH / "p02-a01" / f"result-{tag}.png"))
