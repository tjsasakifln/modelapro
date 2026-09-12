from __future__ import annotations

import hashlib

from modules.digital_signatures import (
    prepare_signature_request,
    record_external_signature,
    verify_pdf_signature,
    verify_signature_binding,
)
from modules.report_presenter.qualification import (
    assess_document_state,
    report_content_fingerprint,
    signable_snapshot_sha256,
)
from modules.results_generator import render_report

from .fixtures import qualified_case


def test_a06_unsigned_or_missing_backend_never_becomes_valid():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    result = verify_pdf_signature(pdf)
    assert result["status"] in {"not_verified", "invalid"}
    assert result["status"] != "valid"


def test_a06_external_signature_record_is_bound_to_pdf_snapshot_and_revision():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    request = prepare_signature_request(
        pdf,
        snapshot,
        revision_id="rev-test-001",
        profile_id="urban-market-regression",
        report_context=context,
    )
    signed_pdf = (
        pdf
        + b"\n% synthetic external-signature placeholder; not cryptographically valid"
    )
    verification = {
        "status": "valid",
        "signed_pdf_sha256": __import__("hashlib").sha256(signed_pdf).hexdigest(),
        "backend": "synthetic-test-verifier",
        "findings": [],
    }
    record = record_external_signature(
        signed_pdf, request, unsigned_pdf=pdf, verification=verification
    )
    assert record["status"] != "valid"
    synthetic_valid_record = dict(
        record,
        status="valid",
        backend="pyHanko",
        incremental_base_verified=True,
        local_verification={"status": "valid", "signature_count": 1},
    )
    assert (
        verify_signature_binding(
            signed_pdf,
            synthetic_valid_record,
            snapshot,
            revision_id="rev-test-001",
            unsigned_pdf=pdf,
            report_context=context,
        )["ok"]
        is True
    )
    changed = verify_signature_binding(
        signed_pdf + b"x",
        synthetic_valid_record,
        snapshot,
        revision_id="rev-test-001",
        unsigned_pdf=pdf,
        report_context=context,
    )
    assert any(
        item["code"] == "SIGNED_PDF_HASH_MISMATCH" for item in changed["findings"]
    )
    wrong_revision = verify_signature_binding(
        signed_pdf,
        synthetic_valid_record,
        snapshot,
        revision_id="rev-test-002",
        unsigned_pdf=pdf,
        report_context=context,
    )
    assert any(
        item["code"] == "SIGNED_REVISION_MISMATCH"
        for item in wrong_revision["findings"]
    )


def test_a06_signed_revision_is_not_rerendered_with_a_false_seal():
    snapshot, context = qualified_case()
    snapshot["provenance"]["qualification_context"]["case_release_status"] = (
        "signed_integrity_verified"
    )
    context["digital_signature"] = {"status": "valid"}
    assert render_report(snapshot, context).startswith(b"%PDF")


def test_a06_validly_described_but_unrelated_pdf_cannot_bind_to_request():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    request = prepare_signature_request(
        pdf,
        snapshot,
        revision_id="rev-test-001",
        profile_id="urban-market-regression",
        report_context=context,
    )
    unrelated = b"%PDF-1.7\n% unrelated signed artifact"
    record = record_external_signature(
        unrelated,
        request,
        unsigned_pdf=pdf,
        verification={
            "status": "valid",
            "signed_pdf_sha256": __import__("hashlib").sha256(unrelated).hexdigest(),
        },
    )
    assert record["status"] == "invalid"
    assert any(
        item["code"] == "SIGNED_PDF_NOT_DERIVED_FROM_REQUESTED_UNSIGNED_BYTES"
        for item in record["findings"]
    )


def test_a06_forged_valid_mapping_cannot_release_unsigned_fake_bytes():
    snapshot, context = qualified_case()
    unsigned = render_report(snapshot, context)
    signed = unsigned + b"FAKE-SIGNATURE-BYTES"
    snapshot["provenance"]["qualification_context"]["case_release_status"] = (
        "signed_integrity_verified"
    )
    context["unsigned_pdf_bytes"] = unsigned
    context["signed_pdf_bytes"] = signed
    context["digital_signature"] = {
        "schema_version": "MP-SIGN/1",
        "status": "valid",
        "backend": "pyHanko",
        "unsigned_pdf_sha256": hashlib.sha256(unsigned).hexdigest(),
        "signed_pdf_sha256": hashlib.sha256(signed).hexdigest(),
        "snapshot_sha256": signable_snapshot_sha256(snapshot),
        "revision_id": "rev-test-001",
        "result_fingerprint": snapshot["provenance"]["qualification_context"][
            "result_fingerprint"
        ],
        "report_content_fingerprint": report_content_fingerprint(snapshot, context),
        "incremental_base_verified": True,
        "local_verification": {"status": "valid", "signature_count": 1},
    }
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "SIGNED_STATE_WITHOUT_VALID_SIGNATURE"
        for item in state["blockers"]
    )
