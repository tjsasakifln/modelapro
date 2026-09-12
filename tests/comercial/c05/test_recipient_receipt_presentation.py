"""PDF/DOCX show a verified receipt sidecar without inventing institutional acceptance."""

from __future__ import annotations

import hashlib
import io
import zipfile

from modules.provenance import canonical_json
from modules.report_export.docx import build_docx
from modules.report_presenter.verifier import extract_pdf_text
from modules.results_generator import build_report_view, render_report
from tests.comercial.c03.fixtures import qualified_case


def _receipt(profile):
    identity = {
        "proof_sha256": "d" * 64,
        "recipient_id": profile["recipient_id"],
        "profile_id": profile["id"],
        "protocol": "PROTOCOLO-TESTE-PDF-001",
        "received_at": "2026-09-12T16:00:00-03:00",
        "source": "TESTE: retorno sintético",
        "synthetic_test_only": True,
        "authorized_for_report": True,
        "case_state_at_import": {
            "result_fingerprint": "2" * 64,
            "report_content_fingerprint": None,
            "artifact_sha256": {
                "report.pdf": "3" * 64,
                "signed_report.pdf": None,
                "submission.zip": None,
            },
            "association_to_sent_version_verified": False,
        },
    }
    record = {
        **identity,
        "record_id": hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        "event": "recipient_return",
        "decision": "received_declared_unverified",
        "status": "received_declared_unverified",
        "institution_acceptance": False,
        "authenticity_verified": False,
        "profile_version": profile["version"],
        "profile_source_set_sha256": profile["source_set_sha256"],
        "recorded_at": "2026-09-12T16:01:00-03:00",
        "operator_declaration": (
            "RECEIVED_DOCUMENT_RECORDED_WITHOUT_AUTHENTICITY_OR_ACCEPTANCE_VERIFICATION"
        ),
        "filename": "SYNTHETIC_TEST_retorno.txt",
        "stored_name": "recipient-return-" + "d" * 20 + "-SYNTHETIC_TEST_retorno.txt",
        "media_type": "text/plain",
        "size": 42,
        "bytes_integrity": "verified",
    }
    return {"recorded": True, "record": record, "detail": "untrusted caller detail"}


def test_nested_receipt_is_visible_as_unverified_in_view_pdf_and_docx():
    snapshot, context = qualified_case()
    qctx = snapshot["provenance"]["qualification_context"]
    profile = qctx["resolved_profile"]
    qctx["institution_acceptance"] = _receipt(profile)

    view = build_report_view(snapshot, context)
    display = view["institution_acceptance_display"]
    assert "Comprovante registrado" in display
    assert "NÃO VERIFICADO" in display
    assert "PROTOCOLO-TESTE-PDF-001" in display
    assert "d" * 64 in display
    assert "versão efetivamente enviada NÃO VERIFICADA" in display
    assert "Aceito" not in display

    pdf_text = extract_pdf_text(render_report(snapshot, context))
    assert "Comprovante registrado" in pdf_text
    assert "NÃO VERIFICADO" in pdf_text

    docx = build_docx(snapshot, context)
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "Comprovante registrado" in document_xml
    assert "NÃO VERIFICADO" in document_xml


def test_fake_accepted_wrapper_is_not_rendered_as_receipt_or_acceptance():
    snapshot, context = qualified_case()
    snapshot["provenance"]["qualification_context"]["institution_acceptance"] = {
        "recorded": True,
        "record": {"valid": True, "accepted": True, "status": "accepted"},
        "detail": "Aceito pela instituição",
    }

    view = build_report_view(snapshot, context)
    assert view["institution_acceptance_display"] == (
        "Não registrada; emissão do laudo não implica aceitação do destinatário."
    )
    text = extract_pdf_text(render_report(snapshot, context))
    assert "Aceito pela instituição" not in text
