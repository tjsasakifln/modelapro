"""P02-A01: Playwright + API/Streamlit reais, ou registro honesto de indisponibilidade.

Sem fixture de session_state e sem interceptação de HTTP. Se o lançador
Playwright/browser não estiver disponível neste ambiente, o teste grava o
motivo e não fabrica traces.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path(os.environ.get("P02_SCRATCH", "/tmp/grok-goal-7164525daca4/implementer"))


def _evidence_dir() -> Path:
    configured = os.environ.get("C17_UI_EVIDENCE")
    return Path(configured) / "P02" if configured else SCRATCH / "p02-a01"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
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
    evidence = _evidence_dir()
    evidence.mkdir(parents=True, exist_ok=True)
    log_path = evidence / "p02-playwright-unavailable.log"
    payload = {
        "status": "BLOCKED",
        "reason": reason,
        "note": "A01 não foi fabricado. Unitários e AppTest cobrem o restante neste ambiente.",
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return log_path


def test_a01_playwright_real_path_or_record_unavailability(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        log_path = _record_block(f"playwright import failed: {exc}")
        assert log_path.is_file()
        assert "playwright" in log_path.read_text(encoding="utf-8").lower()
        raise AssertionError("NOT_RUN: browser obligation unavailable; see recorded evidence")

    api_port = ui_port = None
    for candidate in range(18200, 18280, 2):
        if _port_free(candidate) and _port_free(candidate + 1):
            api_port, ui_port = candidate, candidate + 1
            break
    if api_port is None:
        log_path = _record_block("no free loopback ports in 18200-18280")
        assert log_path.is_file()
        raise AssertionError("NOT_RUN: browser obligation unavailable; see recorded evidence")

    csv_path = tmp_path / "mercado_ptbr.csv"
    csv_path.write_bytes(_ptbr_csv())
    xlsx_path = tmp_path / "mercado.xlsx"
    try:
        _write_excel(xlsx_path)
    except Exception as exc:
        log_path = _record_block(f"excel writer failed: {exc}")
        assert log_path.is_file()
        raise AssertionError("NOT_RUN: browser obligation unavailable; see recorded evidence")

    env = os.environ.copy()
    env["MODELA_API_URL"] = f"http://127.0.0.1:{api_port}"
    env["MODELA_API_TIMEOUT"] = "120"
    env["MODELA_DISABLE_WS"] = "1"
    env["MODELA_STORE_ROOT"] = str(tmp_path / "store")
    env["MODELA_RUNTIME_ROOT"] = str(tmp_path / "runtime")
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=str(ROOT),
        env=env,
        stdout=(tmp_path / "api.log").open("w", encoding="utf-8"),
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
        stdout=(tmp_path / "ui.log").open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_http(f"http://127.0.0.1:{api_port}/health"):
            _record_block("API health did not become ready")
            raise AssertionError("NOT_RUN: browser obligation unavailable; see recorded evidence")
        if not _wait_http(f"http://127.0.0.1:{ui_port}"):
            _record_block("Streamlit UI did not become ready")
            raise AssertionError("NOT_RUN: browser obligation unavailable; see recorded evidence")
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
    shots = _evidence_dir()
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
        page.get_by_text("MODELA PRO", exact=True).first.wait_for(
            state="visible", timeout=45000
        )
        page.screenshot(path=str(shots / "desktop-empty.png"))
        csv_job_id = _upload_and_run(page, csv_path, "csv")
        page.set_viewport_size({"width": 390, "height": 720})
        page.screenshot(path=str(shots / "narrow-result.png"))
        page.set_viewport_size({"width": 1366, "height": 768})
        xlsx_job_id = _upload_and_run(page, xlsx_path, "xlsx")
        assert xlsx_job_id != csv_job_id, "CSV and XLSX must execute as distinct jobs"
        context.tracing.stop(path=str(shots / "trace.zip"))
        browser.close()

    # Streamlit's ApiClient POSTs /jobs from the Python server, not the
    # browser; page.on("request") never sees it. The real path is the
    # visible calculation asserted in _upload_and_run.
    sanitised = [{"method": item["method"], "path": item["url"].split("://", 1)[-1].split("/", 1)[-1]} for item in request_log]
    (shots / "requests.json").write_text(json.dumps(sanitised, ensure_ascii=False, indent=2), encoding="utf-8")


def _market_file_input(page):
    labeled = page.locator("[data-testid='stFileUploader']").filter(
        has_text="Arquivo de dados de mercado"
    ).locator("input[type='file']")
    if labeled.count() >= 1:
        return labeled.first
    return page.locator("input[type='file']").first


def _upload_and_run(page, path: Path, tag: str) -> str:
    from playwright.sync_api import expect

    expect(page.get_by_role("heading", name="1. Encomenda e perfil", exact=True)).to_be_visible(
        timeout=45000
    )
    result_region = page.get_by_role("region", name="Valor da avaliação", exact=True)
    file_input = _market_file_input(page)
    file_input.set_input_files(str(path))
    expect(
        page.locator("[data-testid='stFileUploader']").filter(has_text=path.name)
    ).to_be_visible(timeout=45000)
    expect(
        page.get_by_role("heading", name="Interpretação recebida", exact=True)
    ).to_be_visible(timeout=90000)

    area = page.get_by_placeholder("ex.: 73,5").first
    expect(area).to_be_visible(timeout=90000)
    area.fill("73,5", timeout=45000)
    expect(area).to_have_value("73,5", timeout=45000)

    execute = page.get_by_role("button", name="Executar avaliação", exact=True).first
    expect(execute).to_be_visible(timeout=45000)
    expect(execute).to_be_enabled(timeout=45000)
    execute.click()

    accepted = page.get_by_text(re.compile(r"^Trabalho aceito: job_[a-f0-9]+\."))
    expect(accepted.first).to_be_visible(timeout=90000)
    accepted_text = accepted.first.inner_text()
    accepted_match = re.search(r"(job_[a-f0-9]+)", accepted_text)
    assert accepted_match is not None, accepted_text
    job_id = accepted_match.group(1)
    current_job = page.get_by_text(
        f"Identificador do trabalho: {job_id}", exact=True
    )

    # GET refresh is intentionally explicit in this WebSocket-disabled path.
    # Locator waits span Streamlit's DOM replacement instead of sampling a
    # transient count or sleeping after a stale element was found.
    for _ in range(12):
        try:
            expect(current_job).to_be_visible(timeout=10000)
            expect(result_region).to_be_visible(timeout=10000)
            break
        except AssertionError:
            refresh = page.get_by_role("button", name="Atualizar estado", exact=True).first
            expect(refresh).to_be_visible(timeout=20000)
            expect(refresh).to_be_enabled(timeout=20000)
            refresh.click()
    expect(current_job).to_be_visible(timeout=10000)
    expect(result_region).to_be_visible(timeout=10000)
    body = page.inner_text("body")
    page.screenshot(path=str(_evidence_dir() / f"result-{tag}.png"))
    assert "Valor da avaliação" in body or "Cálculo disponível" in body, body[:2000]
    assert "735.000" in body or "735000" in body or "735.000,00" in body, body[:1500]
    return job_id
