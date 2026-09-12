"""Browser acceptance of C02 -> C01/C05 -> C03 with TEST-only signing.

The market data, professional identity, findings, review and certificate are
generated fixtures explicitly labelled TESTE. This is neither a professional
opinion, an ICP-Brasil certificate nor institutional acceptance.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.c17_integration.helpers import analytic_linear_csv

ROOT = Path(__file__).resolve().parents[2]


def _free_port_pair() -> tuple[int, int]:
    for candidate in range(18900, 19000, 2):
        sockets = []
        try:
            for port in (candidate, candidate + 1):
                sock = socket.socket()
                sock.bind(("127.0.0.1", port))
                sockets.append(sock)
            return candidate, candidate + 1
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise AssertionError("NOT_RUN: no free local port pair for browser acceptance")


def _wait_http(url: str, timeout: float = 45.0) -> bool:
    import http.client
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (http.client.HTTPException, OSError, TimeoutError, urllib.error.URLError):
            time.sleep(0.4)
    return False


def _test_signing_identity(tmp_path: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "MODELA PRO CERTIFICADO SINTETICO DE TESTE")]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    trust_root = tmp_path / "SYNTHETIC_TEST_report_trust_root.pem"
    trust_root.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    p12 = pkcs12.serialize_key_and_certificates(
        b"MODELA-PRO-TESTE",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(b"senha-sintetica-teste"),
    )
    return trust_root, p12


def _sign_pdf_for_test(unsigned: bytes, p12: bytes) -> bytes:
    try:
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import signers
    except ImportError as exc:
        raise AssertionError(
            "NOT_RUN: pyHanko is required for the real signed-PDF browser acceptance"
        ) from exc

    signer = signers.SimpleSigner.load_pkcs12_data(
        p12, other_certs=[], passphrase=b"senha-sintetica-teste"
    )
    assert signer is not None

    def sign_outside_playwright_event_loop() -> bytes:
        return signers.PdfSigner(
            signers.PdfSignatureMetadata(field_name="AssinaturaSinteticaTeste"), signer=signer
        ).sign_pdf(IncrementalPdfFileWriter(io.BytesIO(unsigned))).getvalue()

    with ThreadPoolExecutor(max_workers=1) as executor:
        signed = executor.submit(sign_outside_playwright_event_loop).result(timeout=60)
    assert signed.startswith(unsigned)
    return signed


def _field(page, label: str):
    # Streamlit tears down and recreates neighbouring controls on each widget
    # interaction. Give the real rerun time to publish the requested control.
    for _ in range(60):
        direct = page.get_by_label(label, exact=True)
        if direct.count():
            tag = direct.first.evaluate("element => element.tagName.toLowerCase()")
            if tag in {"input", "textarea"}:
                return direct.first
            nested = direct.first.locator("input, textarea")
            if nested.count():
                return nested.first
        for test_id in ("stTextInput", "stTextArea", "stDateInput"):
            candidate = page.locator(f"[data-testid='{test_id}']").filter(has_text=label)
            control = candidate.locator("input, textarea")
            if control.count():
                return control.first
        page.wait_for_timeout(250)
    raise AssertionError(f"UI field not found: {label}")


def _fill(page, label: str, value: str) -> None:
    control = _field(page, label)
    control.fill(value, force=True)
    page.keyboard.press("Tab")
    page.wait_for_timeout(150)


def _select(page, label: str, option: str, *, steps: int = 1) -> None:
    box = page.locator("[data-testid='stSelectbox']").filter(has_text=label)
    assert box.count(), f"UI selectbox not found: {label}"
    control = box.first.get_by_role("combobox")
    if not control.count():
        control = box.first.locator("[data-baseweb='select']")
    control.first.click()
    for _ in range(steps):
        page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)


def _multiselect(page, label: str, options: tuple[str, ...]) -> None:
    widget = page.locator("[data-testid='stMultiSelect']").filter(has_text=label)
    assert widget.count(), f"UI multiselect not found: {label}"
    control = widget.first.get_by_role("combobox")
    assert control.count(), f"UI multiselect control not found: {label}"
    for option in options:
        control.click()
        choice = page.get_by_role("option", name=option, exact=True)
        choice.wait_for(state="visible", timeout=10000)
        choice.click()


def _expand(page, title: str) -> None:
    heading = page.get_by_text(title, exact=True)
    for _ in range(30):
        if heading.count():
            break
        page.wait_for_timeout(200)
    assert heading.count(), f"UI expander not found: {title}"
    heading.first.click()
    page.wait_for_timeout(250)


def _wait_for_calculation(page) -> str:
    body = ""
    for _ in range(60):
        body = page.inner_text("body")
        if ("Valor da avaliação" in body or "Cálculo disponível" in body) and (
            "735.000" in body or "735000" in body or "735.000,00" in body
        ):
            return body
        refresh = page.get_by_role("button", name="Atualizar estado")
        if refresh.count() and refresh.first.is_enabled():
            refresh.first.click()
        page.wait_for_timeout(1500)
    raise AssertionError("calculation did not reach the real result UI\n" + body[:3000])


def _wait_for_dossier_ready(page) -> None:
    """Poll the product status until the worker's required dossier is ready."""
    body = ""
    for _ in range(60):
        body = page.inner_text("body")
        flattened = " ".join(body.split())
        if "evidence_bundle.zip: Pronto para baixar" in flattened:
            return
        refresh = page.get_by_role("button", name="Atualizar estado")
        if refresh.count() and refresh.first.is_enabled():
            refresh.first.click()
        page.wait_for_timeout(1000)
    raise AssertionError("required evidence_bundle.zip did not become ready\n" + body[-3000:])


def test_browser_completes_test_report_review_and_external_signature(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AssertionError("NOT_RUN: Playwright is required for browser acceptance") from exc

    api_port, ui_port = _free_port_pair()
    trust_root, p12 = _test_signing_identity(tmp_path)
    market_file = tmp_path / "SYNTHETIC_TEST_mercado.csv"
    market_file.write_bytes(analytic_linear_csv(n=30, tag="SYNTHETIC-TEST"))
    attachment_file = tmp_path / "SYNTHETIC_TEST_vistoria.txt"
    attachment_file.write_text(
        "DOCUMENTO SINTETICO DE TESTE - SEM VALIDADE EXTERNA\n"
        "parte1.6.3.vistoria: vistoria sintética registrada para o caso de teste.\n"
        "8.2.1.5.2.campo_suficiente: campos sintéticos da amostra registrados.\n"
        "10.1.laudo_completo: conteúdo sintético de saída conferido no teste.\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "MODELA_API_URL": f"http://127.0.0.1:{api_port}",
            "MODELA_API_TIMEOUT": "120",
            "MODELA_DISABLE_WS": "1",
            "MODELA_STORE_ROOT": str(tmp_path / "store"),
            "MODELA_RUNTIME_ROOT": str(tmp_path / "runtime"),
            "MODELA_REPORT_SIGNATURE_TRUST_ROOTS": str(trust_root),
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
                "NOT_RUN: API did not become healthy\n" + api_log_path.read_text()[-3000:]
            )
            assert _wait_http(f"http://127.0.0.1:{ui_port}"), (
                "NOT_RUN: Streamlit did not become ready\n" + ui_log_path.read_text()[-3000:]
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    accept_downloads=True, viewport={"width": 1440, "height": 1000}
                )
                page = context.new_page()
                try:
                    page.goto(
                        f"http://127.0.0.1:{ui_port}",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.get_by_role(
                        "heading", name="1. Encomenda e perfil", exact=True
                    ).wait_for(state="visible", timeout=60000)
                    page.get_by_text(
                        "Caso composto exclusivamente com dados e atos sintéticos de TESTE",
                        exact=True,
                    ).click()
                    _fill(page, "Solicitante", "SYNTHETIC_TEST — solicitante")

                    market = page.locator("[data-testid='stFileUploader']").filter(
                        has_text="Arquivo de dados de mercado"
                    ).locator("input[type=file]")
                    assert market.count()
                    market.first.set_input_files(str(market_file))
                    page.wait_for_selector("input[placeholder='ex.: 73,5']", timeout=90000)

                    _fill(page, "Unidade do valor-alvo", "BRL")
                    page.get_by_text(
                        "Informar data da avaliação (data-base)", exact=True
                    ).click()
                    _fill(page, "Data da avaliação (data-base)", "2026-09-01")
                    page.get_by_text("Informar data da vistoria", exact=True).click()
                    _fill(page, "Data da vistoria", "2026-09-01")
                    _select(
                        page,
                        "Política do valor adotado",
                        "Adotar a estimativa pontual calculada",
                    )
                    _fill(
                        page,
                        "Fundamento da política do valor adotado",
                        "SYNTHETIC_TEST: estimativa pontual prevista na encomenda de teste",
                    )
                    _select(
                        page,
                        "Grau declarado de caracterização do imóvel avaliando (item documental)",
                        "1",
                        steps=2,
                    )
                    _select(
                        page,
                        "Grau declarado de identificação dos dados de mercado (item documental)",
                        "1",
                        steps=2,
                    )
                    _fill(
                        page,
                        "Evidência da caracterização do avaliando",
                        "SYNTHETIC_TEST_vistoria.txt",
                    )
                    _fill(
                        page,
                        "Evidência da identificação dos dados de mercado",
                        "SYNTHETIC_TEST_mercado.csv",
                    )

                    _expand(page, "Evidências do perfil e achados profissionais")
                    for requirement_id, reference in (
                        ("parte1.6.3.vistoria", "SYNTHETIC_TEST_vistoria.txt"),
                        ("8.2.1.5.2.campo_suficiente", "SYNTHETIC_TEST_report.pdf#campo"),
                        ("10.1.laudo_completo", "SYNTHETIC_TEST_report.pdf#conteudo"),
                    ):
                        _fill(page, f"Referência de evidência — {requirement_id}", reference)
                    for label in (
                        "Variáveis relevantes e interações",
                        "Coerência do avaliando com a multicolinearidade",
                        "Resíduos versus variáveis independentes",
                        "Pontos influenciantes",
                        "Agrupamentos e interações",
                    ):
                        _select(
                            page,
                            f"Conclusão profissional — {label}",
                            "Satisfeito — conclusão do profissional",
                        )
                        _fill(
                            page,
                            f"Justificativa profissional — {label}",
                            f"SYNTHETIC_TEST: exame de {label} registrado apenas para teste",
                        )

                    _select(page, "Procedência da vistoria", "Ato do profissional responsável")
                    _fill(page, "Responsável pela vistoria", "PROFISSIONAL SINTETICO DE TESTE")
                    _fill(page, "Características verificadas", "SYNTHETIC_TEST: área conferida")
                    _fill(page, "Nome do profissional responsável", "PROFISSIONAL SINTETICO DE TESTE")
                    _fill(page, "Registro profissional", "CREA-TESTE-000")
                    _fill(page, "Conselho (CREA/CAU/…)", "CREA-TESTE")
                    _fill(page, "ART/RRT ou referência documental", "ART-TESTE-000")

                    area = page.get_by_placeholder("ex.: 73,5").first
                    area.fill("73,5")
                    page.keyboard.press("Tab")
                    page.get_by_role("button", name="Executar avaliação").first.click()
                    body = _wait_for_calculation(page)
                    assert "TESTE SINTÉTICO" in body
                    _wait_for_dossier_ready(page)

                    _expand(page, "Arquivos integrais e procedência")
                    document_upload = page.locator("[data-testid='stFileUploader']").filter(
                        has_text="Documento ou anexo integral"
                    ).locator("input[type=file]")
                    document_upload.first.set_input_files(str(attachment_file))
                    _fill(
                        page,
                        "Fonte e autorização de acesso ao arquivo",
                        "SYNTHETIC_TEST: produzido pela fixture e autorizado somente para teste",
                    )
                    _fill(
                        page,
                        "Descrição do documento/anexo",
                        "SYNTHETIC_TEST: registro integral que explicita a cobertura dos três requisitos selecionados",
                    )
                    _multiselect(
                        page,
                        "Requisitos comprovados pelo arquivo",
                        (
                            "parte1.6.3.vistoria",
                            "8.2.1.5.2.campo_suficiente",
                            "10.1.laudo_completo",
                        ),
                    )
                    page.get_by_text(
                        "Tenho autorização para incluir estes bytes no laudo e dossiê",
                        exact=True,
                    ).click()
                    page.get_by_role("button", name="Anexar arquivo autorizado").click()
                    page.wait_for_selector(
                        "text=Bytes arquivados com hash", state="attached", timeout=30000
                    )

                    _expand(page, "Completar conteúdo e anexos do laudo")
                    for label, value in (
                        ("Identificação do bem", "SYNTHETIC_TEST — imóvel urbano fictício"),
                        ("Caracterização da região", "SYNTHETIC_TEST — região fictícia"),
                        ("Caracterização do imóvel", "SYNTHETIC_TEST — imóvel fictício de 73,5 m²"),
                        ("Justificativa do método", "SYNTHETIC_TEST — regressão sobre amostra sintética"),
                        ("Pressupostos, ressalvas e limitações", "SYNTHETIC_TEST — sem validade externa"),
                    ):
                        _fill(page, label, value)
                    page.get_by_role("button", name="Gerar PDF, DOCX e dossiê").click()
                    page.wait_for_selector(
                        "text=Documentos gerados", state="attached", timeout=60000
                    )

                    _fill(page, "Profissional responsável pela decisão", "CREA-TESTE-REVISOR-000")
                    _fill(
                        page,
                        "Motivo e evidências da revisão",
                        "SYNTHETIC_TEST: revisão independente simulada apenas para teste",
                    )
                    _fill(page, "Identificador da revisão documental", "SYNTHETIC-TEST-REV-1")
                    page.get_by_role("button", name="Registrar revisão (não assina o laudo)").click()
                    page.wait_for_selector("text=Revisão registrada pelo serviço", timeout=60000)
                    assert "ready_for_professional_signoff" in page.inner_text("body")

                    page.get_by_role("button", name="Exportar para assinador externo").click()
                    download_pdf = page.get_by_role(
                        "button", name="Baixar os bytes PDF para assinatura"
                    )
                    download_pdf.wait_for(state="visible", timeout=30000)
                    with page.expect_download(timeout=30000) as download_info:
                        download_pdf.click()
                    unsigned_path = tmp_path / "SYNTHETIC_TEST_unsigned_report.pdf"
                    download_info.value.save_as(str(unsigned_path))
                    unsigned = unsigned_path.read_bytes()
                    assert unsigned.startswith(b"%PDF")

                    signed_path = tmp_path / "SYNTHETIC_TEST_signed_report.pdf"
                    signed_path.write_bytes(_sign_pdf_for_test(unsigned, p12))
                    signed_upload = page.locator("[data-testid='stFileUploader']").filter(
                        has_text="Arquivo PDF assinado original"
                    ).locator("input[type=file]")
                    signed_upload.first.set_input_files(str(signed_path))
                    page.get_by_role(
                        "button", name="Verificar arquivo assinado importado"
                    ).click()
                    page.wait_for_selector("text=Verificação concluída pelo serviço", timeout=60000)
                    final_body = page.inner_text("body")
                    assert "signed_integrity_verified" in final_body
                    assert "signed_report.pdf" in final_body
                    assert "report.docx" in final_body
                    assert "submission.zip" in final_body
                    assert "document_history.zip" in final_body
                    assert "aceito pela instituição" not in final_body.lower()
                except Exception:
                    page.screenshot(path=str(tmp_path / "browser-document-flow-failure.png"), full_page=True)
                    (tmp_path / "browser-document-flow-body.txt").write_text(
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
            collect_browser_evidence(tmp_path, namespace="c06-document-flow")
