"""Browser acceptance for the real cost-quantification consumer.

Every monetary value, source, professional identity, and inspection entry in
this case is an explicitly labelled synthetic TEST fixture.  The test proves
the installed/source UI-to-HTTP-to-worker-to-persistence path; it is not a
professional review, a current-cost source, or institutional acceptance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from modules.job_store import JobStore
from tests.comercial.test_c06_browser_document_flow import (
    ROOT,
    _fill,
    _free_port_pair,
    _select,
    _wait_http,
)


def _choose_cost_path(page) -> None:
    radio = page.locator("[data-testid='stRadio']").filter(
        has_text="Percurso de cálculo"
    )
    radio.first.get_by_text("Quantificação de custo", exact=True).click(force=True)
    page.get_by_text(
        "Encomenda por quantificação de custo", exact=True
    ).wait_for(state="visible", timeout=30_000)


def _paste_cost_item(page) -> None:
    """Enter one actual row through Streamlit's editable-grid clipboard path."""
    # Do not paste into a grid that belongs to the preceding Streamlit rerun.
    page.wait_for_timeout(1_500)
    grid = page.locator("[data-testid='stDataFrame']").first
    assert grid.count() == 1, "cost item editor was not rendered"
    row = (
        "estrutura\tEstrutura SINTETICA DE TESTE\tbuilding_component\t10\t"
        "m2\t100\tBRL\t2026-09-12\tORCAMENTO-SINTETICO-TESTE item estrutura"
    )
    rendered_grid = ""
    for _ in range(3):
        page.evaluate("value => navigator.clipboard.writeText(value)", row)
        canvas = grid.locator("[data-testid='data-grid-canvas']")
        # Glide Data Grid exposes its accessible table as canvas fallback
        # content; selecting the first body cell and pasting TSV is its real
        # bulk-edit UI.
        canvas.click(position={"x": 70, "y": 55}, force=True)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(1_500)
        rendered_grid = grid.evaluate("element => element.outerHTML")
        if "Estrutura SINTETICA DE TESTE" in rendered_grid:
            break
    assert "Estrutura SINTETICA DE TESTE" in rendered_grid
    assert "ORCAMENTO-SINTETICO-TESTE item estrutura" in rendered_grid


def _wait_for_cost_result(page) -> str:
    body = ""
    for _ in range(80):
        body = page.inner_text("body")
        flattened = " ".join(body.split())
        if (
            "Valor da avaliação" in body
            and "920,00 BRL" in flattened
            and "Estado: Cálculo disponível" in flattened
        ):
            return body
        refresh = page.get_by_role("button", name="Atualizar estado")
        if refresh.count() and refresh.first.is_enabled():
            refresh.first.click()
        page.wait_for_timeout(1_000)
    raise AssertionError("cost calculation did not reach the real result UI\n" + body[-4_000:])


@pytest.mark.raw_local_auth
def test_browser_cost_calculation_without_market_file_can_be_saved_and_reopened(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AssertionError("NOT_RUN: Playwright is required for browser acceptance") from exc

    api_port, ui_port = _free_port_pair()
    store_root = tmp_path / "store"
    env = os.environ.copy()
    env.update(
        {
            "MODELA_API_URL": f"http://127.0.0.1:{api_port}",
            "MODELA_API_TIMEOUT": "120",
            "MODELA_DISABLE_WS": "1",
            "MODELA_STORE_ROOT": str(store_root),
            "MODELA_RUNTIME_ROOT": str(tmp_path / "runtime"),
            "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    api_log_path = tmp_path / "api.log"
    ui_log_path = tmp_path / "ui.log"
    with api_log_path.open("w", encoding="utf-8") as api_log, ui_log_path.open(
        "w", encoding="utf-8"
    ) as ui_log:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        ui = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "frontend" / "app.py"),
                "--server.port",
                str(ui_port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=ui_log,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_http(f"http://127.0.0.1:{api_port}/health"), (
                "NOT_RUN: API did not become healthy\n" + api_log_path.read_text()[-3_000:]
            )
            assert _wait_http(f"http://127.0.0.1:{ui_port}"), (
                "NOT_RUN: Streamlit did not become ready\n"
                + ui_log_path.read_text()[-3_000:]
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    permissions=["clipboard-read", "clipboard-write"],
                    viewport={"width": 1_440, "height": 1_000},
                )
                page = context.new_page()
                try:
                    page.goto(
                        f"http://127.0.0.1:{ui_port}",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    page.get_by_role(
                        "heading", name="1. Encomenda e perfil", exact=True
                    ).wait_for(state="visible", timeout=60_000)
                    _fill(page, "Identificador do projeto", "COST-BROWSER-TEST")
                    _choose_cost_path(page)

                    assert page.get_by_text(
                        "Custo de reedição de benfeitoria por método da quantificação de custo",
                        exact=False,
                    ).count()
                    assert not page.get_by_text(
                        "Arquivo de dados de mercado", exact=True
                    ).count()

                    _fill(page, "Solicitante do custo", "SOLICITANTE SINTETICO DE TESTE")
                    _fill(page, "Direitos avaliados no custo", "DIREITOS SINTETICOS DE TESTE")
                    page.get_by_text(
                        "Caso de custo SINTÉTICO DE TESTE — não é evidência externa",
                        exact=True,
                    ).click()
                    _fill(page, "Localidade de referência do custo", "TESTE")
                    _fill(page, "Data-base do custo", "2026-09-12")
                    _fill(page, "Data da vistoria do custo", "2026-09-12")
                    _select(page, "Moeda do orçamento", "BRL")
                    _select(page, "Grau mínimo solicitado no custo", "1")
                    _fill(
                        page,
                        "Fonte documental do custo direto",
                        "ORCAMENTO-SINTETICO-TESTE",
                    )
                    _fill(
                        page,
                        "Justificativa do orçamento / semelhança / ajustes",
                        "Memória sintética autorizada exclusivamente para este teste.",
                    )
                    _paste_cost_item(page)

                    _fill(page, "BDI — taxa (fração: 0,10 = 10%)", "0.15")
                    _fill(page, "BDI — justificativa", "BDI SINTETICO DE TESTE")
                    _fill(page, "BDI — fonte", "MEMORIA-BDI-SINTETICA-TESTE")
                    _fill(
                        page,
                        "BDI calculado — componentes (objeto JSON conforme memória de cálculo)",
                        json.dumps({"administracao": 0.10, "risco": 0.05}),
                    )
                    _select(page, "Depreciação — método", "technical_method", steps=2)
                    _fill(page, "Depreciação — taxa (fração)", "0.2")
                    _fill(page, "Método técnico de depreciação", "METODO SINTETICO DE TESTE")
                    _fill(page, "Idade (anos)", "10")
                    _fill(page, "Vida útil (anos)", "50")
                    _fill(page, "Estado de conservação", "regular TESTE")
                    _fill(
                        page,
                        "Depreciação — justificativa / recuperação",
                        "Depreciação técnica sintética para o teste.",
                    )
                    _fill(page, "Depreciação — fonte", "VISTORIA-SINTETICA-TESTE")

                    _select(page, "Procedência da vistoria", "professional_act")
                    _fill(page, "Responsável pela vistoria", "PROFISSIONAL SINTETICO DE TESTE")
                    _fill(
                        page,
                        "Características verificadas",
                        "Estrutura sintética conferida somente para teste.",
                    )
                    _fill(
                        page,
                        "Nome do profissional responsável",
                        "PROFISSIONAL SINTETICO DE TESTE",
                    )
                    _fill(page, "Registro profissional", "CREA-TESTE-000")
                    _fill(page, "Conselho (CREA/CAU/…)", "CREA-TESTE")
                    _fill(page, "ART/RRT ou referência documental", "ART-TESTE-000")

                    calculate = page.get_by_role("button", name="Calcular custo")
                    calculate.wait_for(state="visible", timeout=30_000)
                    assert calculate.is_enabled(), page.inner_text("body")[-4_000:]
                    calculate.click()
                    # Let the submit rerun persist job_id/token before any
                    # refresh action starts another Streamlit rerun.
                    page.get_by_text("Trabalho aceito:", exact=False).wait_for(
                        state="visible", timeout=30_000
                    )
                    result_body = _wait_for_cost_result(page)
                    assert "BUILD SINTÉTICO DE TESTE — NÃO COMERCIAL" in result_body
                    assert "Cálculo disponível" in result_body
                    assert "Custo de reedição de benfeitoria" in result_body

                    jobs = list(JobStore(store_root, recover_abandoned=False).list_jobs())
                    assert len(jobs) == 1
                    persisted = jobs[0]
                    assert persisted["request_spec"]["target_col"] == ""
                    assert persisted["request_spec"]["candidate_cols"] == []
                    assert persisted["request_spec"]["cost_bom"]["items"][0][
                        "source"
                    ] == "ORCAMENTO-SINTETICO-TESTE item estrutura"
                    snapshot = JobStore(store_root, recover_abandoned=False).get_snapshot(
                        persisted["job_id"]
                    )
                    assert snapshot["sample"]["received"] == 0
                    assert snapshot["value"]["point"] == pytest.approx(920)
                    assert snapshot["provenance"]["qualification_context"]["profile"][
                        "id"
                    ] == "abnt-14653-2-custo-reedicao"

                    save = page.get_by_role("button", name="Salvar revisão no projeto")
                    assert save.is_enabled()
                    save.click()
                    page.get_by_text("Nova revisão registrada:", exact=False).wait_for(
                        state="visible", timeout=30_000
                    )
                    page.get_by_role("button", name="Atualizar lista de projetos").click()
                    project_rendered = False
                    for _ in range(30):
                        tables = page.locator("[data-testid='stDataFrame']").evaluate_all(
                            "elements => elements.map(element => element.outerHTML)"
                        )
                        if any("COST-BROWSER-TEST" in table for table in tables):
                            project_rendered = True
                            break
                        page.wait_for_timeout(500)
                    assert project_rendered, "saved project did not reach the project grid"
                    open_project = page.get_by_role(
                        "button", name="Abrir revisão selecionada"
                    )
                    open_project.wait_for(state="visible", timeout=30_000)
                    assert open_project.is_enabled()
                    open_project.click()
                    page.get_by_text(
                        "Recuperação canônica via GET /jobs/{id}/result", exact=False
                    ).wait_for(state="visible", timeout=30_000)
                    # The selected project is stored after this run's panel was
                    # rendered. A normal subsequent UI rerun displays it.
                    page.get_by_role("button", name="Atualizar estado").click()
                    page.get_by_text("Revisão carregada", exact=True).wait_for(
                        state="visible", timeout=30_000
                    )
                    reopened_body = page.inner_text("body")
                    assert "920,00 BRL" in " ".join(reopened_body.split())
                    assert "CUSTO de reedição".lower() in reopened_body.lower()
                except Exception:
                    page.screenshot(
                        path=str(tmp_path / "browser-cost-flow-failure.png"),
                        full_page=True,
                    )
                    (tmp_path / "browser-cost-flow-body.txt").write_text(
                        page.inner_text("body"), encoding="utf-8"
                    )
                    raise
                finally:
                    context.close()
                    browser.close()
        finally:
            for process in (ui, api):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            from tests.comercial.browser_evidence import collect_browser_evidence
            collect_browser_evidence(tmp_path, namespace="c06-cost-flow")
