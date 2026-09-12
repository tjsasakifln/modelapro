"""Drive the installed Streamlit surface with a real Chromium controller.

This probe verifies the buyer-visible TEST label, the six packaged profile
options and the UI -> authenticated API preview path.  The companion Windows
install verifier exercises calculation, documents, persistence and recovery
against the same installed process; this script does not relabel those API
checks as browser actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


TEST_BUILD_LABEL = "BUILD SINTÉTICO DE TESTE — NÃO COMERCIAL"
EXPECTED_PROFILE_LABELS = {
    "Custo de reedição de benfeitoria por método da quantificação de custo",
    "Valor de mercado de imóvel urbano por método comparativo direto com regressão",
    "Banco do Brasil — laudo de avaliação de imóvel urbano (pessoa física), conforme MECI",
    "Resolução CMN nº 4.676/2018 — avaliação do imóvel em garantia (moldura regulatória)",
    "CAIXA — Relatórios de Precificação de Imóveis por AVM (credenciamento CR 012/2026)",
    "Seguro habitacional — cobertura DFI (danos físicos ao imóvel), conforme Res. CNSP 447/2022",
}
FORBIDDEN_BADGES = (
    "aceito pelo banco",
    "aceito pela seguradora",
    "homologado pelo banco",
    "homologado pela seguradora",
)


class BrowserVerificationError(RuntimeError):
    pass


def _synthetic_csv() -> bytes:
    rows = ["id;bairro;area;preco"]
    for index in range(36):
        area = 50.0 + index * 3.5
        bairro = "Sul" if index % 2 else "Centro"
        error = ((index % 7) - 3) * 713.0
        price = 200000.0 + 3500.0 * area + (40000.0 if bairro == "Sul" else 0.0) + error
        rows.append(f"UI-TESTE-{index + 1:03d};{bairro};{area:.6f};{price:.6f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(url: str, evidence: Path, phase: str) -> dict[str, Any]:
    evidence = evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    screenshot = evidence / f"{phase}-installed-ui.png"
    input_path = evidence / f"{phase}-ui-synthetic-input.csv"
    input_path.write_bytes(_synthetic_csv())
    result: dict[str, Any] = {
        "schema_version": "MP-COM-WINDOWS-INSTALLED-UI/1",
        "phase": phase,
        "status": "RUNNING",
        "scope": "browser_catalog_and_authenticated_preview",
        "synthetic_test_data": True,
        "professional_review": False,
        "institution_acceptance": False,
        "input_sha256": _sha256(input_path),
        "console_errors": [],
        "page_errors": [],
    }
    browser = None
    page = None
    try:
        try:
            from importlib.metadata import version
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserVerificationError(f"Playwright controller is not installed: {exc}") from exc
        result["playwright_version"] = version("playwright")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                raise BrowserVerificationError(f"Chromium did not start: {exc}") from exc
            result["browser_version"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.on(
                "console",
                lambda message: result["console_errors"].append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.get_by_text("MODELA PRO", exact=True).first.wait_for(timeout=90000)
            page.get_by_role(
                "heading", name="1. Encomenda e perfil", exact=True
            ).wait_for(state="visible", timeout=60000)
            build_label = page.get_by_text(TEST_BUILD_LABEL, exact=True).first
            try:
                build_label.wait_for(state="visible", timeout=30000)
                result["test_build_label_visible"] = True
            except Exception:
                result["test_build_label_visible"] = False

            profile = page.locator("[data-testid='stSelectbox']").filter(
                has_text="Perfil de qualificação (versionado, catálogo conhecido)"
            )
            if profile.count() != 1:
                raise BrowserVerificationError("installed UI profile selector is absent or duplicated")
            profile.locator("[data-baseweb='select']").click()
            options = page.locator("[role='option']")
            options.first.wait_for(timeout=15000)
            labels = {text.strip() for text in options.all_inner_texts() if text.strip()}
            if labels != EXPECTED_PROFILE_LABELS:
                raise BrowserVerificationError(
                    f"installed UI catalog differs from the six expected labels: {sorted(labels)}"
                )
            page.keyboard.press("Escape")

            uploader = page.locator("[data-testid='stFileUploader']").filter(
                has_text="Arquivo de dados de mercado"
            ).locator("input[type=file]")
            if uploader.count() != 1:
                raise BrowserVerificationError("installed UI market-data uploader is absent or duplicated")
            uploader.set_input_files(str(input_path))
            page.locator("input[placeholder='ex.: 73,5']").first.wait_for(timeout=90000)
            body = page.inner_text("body")
            lowered = body.lower()
            forbidden = [badge for badge in FORBIDDEN_BADGES if badge in lowered]
            if forbidden:
                raise BrowserVerificationError(f"installed UI displayed forbidden acceptance badges: {forbidden}")
            if "Dados não utilizados" not in body:
                raise BrowserVerificationError("installed UI did not render the API-backed sample preview")
            if result["page_errors"]:
                raise BrowserVerificationError(f"installed UI raised page errors: {result['page_errors']}")
            if not result["test_build_label_visible"]:
                raise BrowserVerificationError("installed UI omitted its mandatory synthetic TEST build label")
            result["profile_labels"] = sorted(labels)
            result["preview_visible"] = True
            result["status"] = "PASSED"
            page.screenshot(path=str(screenshot), full_page=True)
            result["screenshot"] = {
                "path": screenshot.name,
                "size": screenshot.stat().st_size,
                "sha256": _sha256(screenshot),
            }
            return result
    except BaseException as exc:
        result["status"] = "FAILED"
        result["error"] = {"type": type(exc).__name__, "detail": str(exc)}
        if page is not None:
            try:
                page.screenshot(path=str(screenshot), full_page=True)
                result["failure_screenshot"] = {
                    "path": screenshot.name,
                    "size": screenshot.stat().st_size,
                    "sha256": _sha256(screenshot),
                }
            except Exception as screenshot_error:
                result["failure_screenshot_error"] = str(screenshot_error)
        raise
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        (evidence / f"{phase}-installed-ui.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args(argv)
    verify(args.url, args.evidence, args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
