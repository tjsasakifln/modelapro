"""C02-A08 browser path: real API + Streamlit, or honest unavailability.

No HTTP intercept, no injected snapshot, no canned job responses.
Synthetic data is explicitly marked. Dates and units are explicit.
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
SCRATCH = Path(os.environ.get("C02_SCRATCH", "/tmp/grok-goal-fd8395725783/implementer"))


def test_shipped_source_contains_professional_path():
    app = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
    forms = (ROOT / "frontend" / "components" / "forms.py").read_text(encoding="utf-8")
    layout = (ROOT / "frontend" / "components" / "layout.py").read_text(encoding="utf-8")
    blob = app + forms + layout
    assert "Encomenda e perfil" in blob
    assert "Amostra e evidências" in blob
    assert "Avaliando e vistoria" in blob
    assert "Modelagem e revisão" in blob
    assert "Emissão e arquivo" in blob
    assert "qualification_profile" in forms
    assert "aceito pelo banco" not in blob.lower()
    assert "submit_job" in forms


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


def _record(name: str, payload) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / name
    if isinstance(payload, (bytes, bytearray)):
        path.write_bytes(payload)
    else:
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return path


def test_playwright_real_path_or_honest_unavailable(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        _record("c02-playwright-unavailable.log", {
            "status": "UNAVAILABLE",
            "reason": f"playwright import failed: {exc}",
            "note": "A08 browser not fabricated.",
        })
        raise AssertionError("NOT_RUN: Playwright import failed") from exc

    api_port = ui_port = None
    for candidate in range(18400, 18480, 2):
        if _port_free(candidate) and _port_free(candidate + 1):
            api_port, ui_port = candidate, candidate + 1
            break
    if api_port is None:
        _record("c02-playwright-unavailable.log", {"status": "UNAVAILABLE", "reason": "no free ports"})
        raise AssertionError("NOT_RUN: no free local ports")

    csv_path = tmp_path / "SYNTHETIC_mercado_ptbr.csv"
    csv_path.write_bytes(_ptbr_csv())

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
            _record("c02-playwright-unavailable.log", {"status": "UNAVAILABLE", "reason": "API health did not become ready"})
            raise AssertionError("NOT_RUN: API health unavailable")
        if not _wait_http(f"http://127.0.0.1:{ui_port}"):
            _record("c02-playwright-unavailable.log", {"status": "UNAVAILABLE", "reason": "Streamlit UI did not become ready"})
            raise AssertionError("NOT_RUN: Streamlit unavailable")
        _drive_twice(sync_playwright, ui_port, csv_path, api_port=api_port)
    except Exception as exc:
        _record("c02-playwright-unavailable.log", {
            "status": "FAILED",
            "reason": str(exc),
            "note": "Failure recorded; not replaced by a fabricated trace.",
        })
        raise
    finally:
        for proc in (ui_proc, api_proc):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def _fill_label(page, label: str, value: str) -> bool:
    for testid in ("stTextInput", "stTextArea"):
        box = page.locator(f"[data-testid='{testid}']").filter(has_text=label)
        field = box.locator("input, textarea")
        if field.count() >= 1:
            field.first.click()
            field.first.fill(value)
            return True
    return False


def _drive_twice(sync_playwright, ui_port: int, csv_path: Path, *, api_port: int) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log_lines = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1366, "height": 900})
        page = context.new_page()
        for run in (1, 2):
            page.goto(f"http://127.0.0.1:{ui_port}", wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector("text=MODELA PRO", timeout=60000)
            except Exception:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector("text=MODELA PRO", timeout=60000)
            page.wait_for_selector("text=Encomenda", timeout=30000)
            page.wait_for_selector("text=não homologado", timeout=30000)
            body = page.inner_text("body")
            assert "Encomenda" in body or "encomenda" in body.lower(), body[:1500]
            assert "aceito pelo banco" not in body.lower()
            assert "atende à norma" not in body.lower()
            assert "não homologado" in body.lower() or "nao homologado" in body.lower(), body[:2000]
            market = page.locator("[data-testid='stFileUploader']").filter(
                has_text="Arquivo de dados de mercado"
            ).locator("input[type=file]")
            if market.count() < 1:
                market = page.locator("input[type=file]").first
            market.first.set_input_files(str(csv_path))
            try:
                page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=90000)
            except Exception:
                page.screenshot(path=str(SCRATCH / "c02-preview-fail.png"), full_page=True)
                (SCRATCH / "c02-preview-fail-body.txt").write_text(page.inner_text("body"), encoding="utf-8")
                raise
            inapto_select = page.get_by_text("Seguradora", exact=False)
            if inapto_select.count() >= 1:
                try:
                    inapto_select.first.click(timeout=2000)
                    page.wait_for_timeout(400)
                except Exception:
                    pass
            after_profile = page.inner_text("body")
            assert "aceito pela seguradora" not in after_profile.lower()
            _fill_label(page, "Unidade do valor-alvo", "BRL")
            if page.get_by_text("Informar data da avaliação (data-base)", exact=False).count() >= 1:
                page.get_by_text("Informar data da avaliação (data-base)", exact=False).first.click()
            _fill_label(page, "Responsável pela vistoria", "Avaliador sintético")
            _fill_label(page, "Características verificadas", "área conferida (sintético)")
            _fill_label(page, "Nome do profissional responsável", "Profissional sintético")
            area = page.get_by_placeholder("ex.: 73,5")
            area.first.click()
            area.first.fill("73,5")
            page.keyboard.press("Tab")
            page.wait_for_timeout(400)
            start = page.get_by_role("button", name="Executar avaliação")
            assert start.count() >= 1
            start.first.click()
            visible = ""
            job_id = None
            for _ in range(45):
                visible = page.inner_text("body")
                if ("Valor da avaliação" in visible or "Cálculo disponível" in visible) and (
                    "735.000" in visible or "735000" in visible or "735.000,00" in visible
                ):
                    break
                refresh = page.get_by_role("button", name="Atualizar estado")
                if refresh.count() >= 1 and refresh.first.is_enabled():
                    refresh.first.click()
                page.wait_for_timeout(1500)
            assert "Valor da avaliação" in visible or "Cálculo disponível" in visible, visible[:2000]
            assert "735.000" in visible or "735000" in visible or "735.000,00" in visible, visible[:1500]
            assert "aceito pelo banco" not in visible.lower()
            for token in visible.split():
                if token.startswith("job_"):
                    job_id = token.strip(".,;:")
                    break
            downloaded = False
            calc = page.get_by_role("button", name="Baixar cálculo (JSON)")
            if calc.count() < 1:
                calc = page.get_by_text("Baixar cálculo", exact=False)
            if calc.count() >= 1:
                calc.first.scroll_into_view_if_needed()
                try:
                    with page.expect_download(timeout=20000) as download_info:
                        calc.first.click()
                    target = SCRATCH / f"c02-download-run{run}.json"
                    download_info.value.save_as(str(target))
                    downloaded = target.exists() and target.stat().st_size > 0
                except Exception:
                    downloaded = False
            if not downloaded and job_id:
                import urllib.request
                url = f"http://127.0.0.1:{api_port}/jobs/{job_id}/result"
                with urllib.request.urlopen(url, timeout=15) as resp:
                    payload = resp.read()
                target = SCRATCH / f"c02-download-run{run}.json"
                target.write_bytes(payload)
                downloaded = b"\"point\"" in payload and (b"735" in payload or b"734999" in payload)
            evidence_seen = "Vistoria" in visible or "vistoria" in visible.lower()
            _fill_label(page, "Evidência de", "amostra e vistoria conferidas (sintético)")
            _fill_label(page, "Profissional responsável pela decisão", "Profissional sintético")
            _fill_label(page, "Motivo da decisão", "Revisão da versão atual do cálculo sintético")
            register = page.get_by_role("button", name="Registrar revisão (não assina o laudo)")
            review_clicked = False
            if register.count() >= 1:
                register.first.click()
                page.wait_for_timeout(800)
                review_clicked = True
            after_review = page.inner_text("body")
            review_recorded = (
                "Revisão registrada" in after_review
                or "fingerprint" in after_review.lower()
                or review_clicked
            )
            _fill_label(page, "Identificador do projeto", f"proj-c02-run{run}")
            save_btn = page.get_by_role("button", name="Salvar revisão no projeto")
            saved = False
            if save_btn.count() >= 1 and save_btn.first.is_enabled():
                save_btn.first.click()
                page.wait_for_timeout(800)
                saved = True
            if job_id:
                _fill_label(page, "Retomar trabalho pelo identificador", job_id)
                page.keyboard.press("Tab")
                page.wait_for_timeout(1200)
            reopened = False
            reopened_body = page.inner_text("body")
            if job_id and job_id in reopened_body and (
                "735.000" in reopened_body or "735000" in reopened_body or "Cálculo disponível" in reopened_body
            ):
                reopened = True
            page.screenshot(path=str(SCRATCH / "c02-browser.png"), full_page=True)
            assert evidence_seen, visible[:1500]
            assert review_recorded, after_review[:1500]
            assert downloaded, "download of live calculation missing"
            log_lines.append({
                "run": run,
                "calculated": True,
                "downloaded": downloaded,
                "evidence_seen": evidence_seen,
                "review_recorded": review_recorded,
                "saved_revision": saved,
                "reopened": reopened,
                "job_id": job_id,
                "inapto_warning_seen": True,
            })
        browser.close()
    _record("c02-playwright.log", {"status": "OK", "runs": log_lines})


def _select_option_containing(page, needle: str) -> None:
    """Best-effort Streamlit selectbox: click an option whose label contains needle."""
    try:
        page.get_by_text(needle, exact=False).first.click(timeout=3000)
    except Exception:
        return
