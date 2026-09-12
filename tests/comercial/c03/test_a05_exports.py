from __future__ import annotations

import base64
import io
import zipfile

from modules.report_export import build_docx, validate_pdfa, verify_docx_equivalence
from modules.results_generator import render_report

from .fixtures import qualified_case


def test_a05_docx_same_snapshot_and_external_edit_loses_equivalence():
    snapshot, context = qualified_case()
    docx = build_docx(snapshot, context)
    clean = verify_docx_equivalence(docx, snapshot, context)
    assert clean["status"] == "verified"
    assert clean["equivalent"] is True
    edited = docx[:-1] + bytes([docx[-1] ^ 1])
    changed = verify_docx_equivalence(edited, snapshot, context)
    assert changed["equivalent"] is False
    assert changed["status"] in {"work_document", "invalid"}


def test_a05_pdfa_absence_of_validator_is_not_pass():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    result = validate_pdfa(pdf)
    assert result["status"] == "unsupported"
    assert result["findings"][0]["code"] == "PDFA_VALIDATOR_NOT_RUN"


def test_a05_docx_contains_authorized_attachment_bytes_and_professional_sections():
    snapshot, context = qualified_case()
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    context["documentary_files"] = [
        {
            "filename": "authorized.png",
            "type": "image/png",
            "bytes": image,
            "authorized_for_report": True,
        }
    ]
    docx = build_docx(snapshot, context)
    with zipfile.ZipFile(io.BytesIO(docx), "r") as archive:
        assert archive.read("word/media/c03_attachment_1.png") == image
        document = archive.read("word/document.xml").decode("utf-8")
    for text in (
        context["region_characterization"],
        context["property_characterization"],
        context["assumptions"][0],
        "authorized.png",
    ):
        assert text in document
