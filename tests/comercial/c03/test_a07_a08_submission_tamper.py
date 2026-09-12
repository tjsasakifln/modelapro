from __future__ import annotations

import hashlib
import io
import json
import zipfile
from copy import deepcopy

import pytest

from modules.digital_signatures import (
    prepare_signature_request,
    record_external_signature,
    verify_signature_binding,
)
from modules.provenance import canonical_json
from modules.report_export import (
    build_docx,
    build_submission_package,
    verify_submission_package,
)
from modules.report_presenter.verifier import (
    extract_pdf_text,
    verify_report_consistency,
)
from modules.results_generator import render_report

from .fixtures import qualified_case


def _dossier_bytes(snapshot, *, truncate_rows=False, corrupt_coefficients=False):
    qualification = snapshot["provenance"]["qualification_context"]
    used_ids = snapshot["sample"]["used_row_ids"]
    if truncate_rows:
        used_ids = used_ids[:1]
    used_csv = "row_id,value\n" + "".join(f"{row_id},1\n" for row_id in used_ids)
    excluded_csv = "row_id,reason\n" + "".join(
        f"{row_id},synthetic exclusion\n"
        for row_id in snapshot["sample"]["excluded_row_ids"]
    )
    coefficients = {
        "values": {
            name: {"text": str(value)}
            for name, value in snapshot["model"]["coefficients"].items()
        }
    }
    if corrupt_coefficients:
        first = next(iter(coefficients["values"]))
        coefficients["values"][first]["text"] = "999999"
    files = {
        "snapshot/result_snapshot.json": canonical_json(snapshot).encode(),
        "qualification/context.json": canonical_json(qualification).encode(),
        "review/history.json": canonical_json(
            {"events": qualification["review_events"]}
        ).encode(),
        "data/source_input.bin": b"synthetic source bytes",
        "data/original_base.csv": used_csv.encode(),
        "data/interpreted_base.csv": used_csv.encode(),
        "data/used_sample.csv": used_csv.encode(),
        "data/excluded_rows.csv": excluded_csv.encode(),
        "data/identifier_map.json": b'{"row_identity":"row_id"}',
        "data/representation_map.json": b'{"row_identity":"row_id"}',
        "model/coefficients.json": canonical_json(coefficients).encode(),
        "model/subject_design.json": b'{"values":{"const":1}}',
        "model/transformations.json": b'{"y_transformation":{"name":"identity"}}',
        "model/residual_context.json": b'{"method":"synthetic"}',
        "policies/request_spec.json": b'{"synthetic":true}',
        "policies/missing_policy.json": b'{"synthetic":true}',
        "policies/outlier_policy.json": b'{"synthetic":true}',
        "policies/search_policy.json": b'{"synthetic":true}',
        "policies/evaluation_policy.json": b'{"synthetic":true}',
        "policies/value_policy.json": b'{"adopted":{"method":"point"}}',
        "reproduction/spec.json": b'{"promised":true}',
        "completeness/ledger.json": b'{"missing":[]}',
    }
    entries = [
        {
            "path": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "type": "application/octet-stream",
            "version": "test",
            "function": "synthetic_test_evidence",
        }
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema_version": "MP/1",
        "bundle_version": "C12/test",
        "completeness_status": "complete",
        "numerical_reproduction_status": "ready",
        "files": entries,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("MANIFEST.json", json.dumps(manifest).encode())
    return output.getvalue()


def test_a07_neutral_institutional_package_has_real_profile_mapping_and_no_submission():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    docx = build_docx(snapshot, context)
    req = {
        "schema_version": "MP-REQ-MAP/1",
        "profile_id": "urban-market-regression",
        "source": {"id": "legitimate-source-index-test", "version": "2026-test"},
        "requirements": [
            {"id": "TEST-RULE-01", "evidence": "qualification/document_state.json"}
        ],
        "authorized_template": False,
    }
    package = build_submission_package(
        snapshot,
        context,
        pdf_bytes=pdf,
        docx_bytes=docx,
        dossier_bytes=_dossier_bytes(snapshot),
        requirement_map=req,
    )
    verified = verify_submission_package(package)
    assert verified["ok"] is True
    assert verified["manifest"]["external_submission_performed"] is False
    assert verified["manifest"]["branding"] == "neutral"
    assert verified["manifest"]["profile_id"] == "urban-market-regression"
    bad = dict(req, profile_id="different-profile")
    with pytest.raises(ValueError, match="does not match"):
        build_submission_package(snapshot, context, pdf_bytes=pdf, requirement_map=bad)

    with pytest.raises(ValueError, match="complete dossier"):
        build_submission_package(snapshot, context, pdf_bytes=pdf, requirement_map=req)
    empty_dossier = io.BytesIO()
    with zipfile.ZipFile(empty_dossier, "w") as archive:
        archive.writestr("MANIFEST.json", '{"files": []}')
    with pytest.raises(ValueError, match="dossier ZIP"):
        build_submission_package(
            snapshot,
            context,
            pdf_bytes=pdf,
            dossier_bytes=empty_dossier.getvalue(),
            requirement_map=req,
        )
    for contradictory in (
        _dossier_bytes(snapshot, truncate_rows=True),
        _dossier_bytes(snapshot, corrupt_coefficients=True),
    ):
        with pytest.raises(ValueError, match="dossier ZIP"):
            build_submission_package(
                snapshot,
                context,
                pdf_bytes=pdf,
                dossier_bytes=contradictory,
                requirement_map=req,
            )

    with pytest.raises(ValueError, match="not a PDF"):
        build_submission_package(snapshot, context, pdf_bytes=b"NOT A PDF")
    with pytest.raises(ValueError, match="DOCX"):
        build_submission_package(
            snapshot, context, pdf_bytes=pdf, docx_bytes=b"NOT A DOCX"
        )
    with pytest.raises(ValueError, match="dossier ZIP"):
        build_submission_package(
            snapshot, context, pdf_bytes=pdf, dossier_bytes=b"NOT A ZIP"
        )


def test_a08_profile_review_value_sample_and_manifest_mutations_are_specific():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    mutations = {
        "MUTATED_VALUE": text.replace("MP1_POINT=350000", "MP1_POINT=1"),
        "MUTATED_PROFILE": text.replace(
            "MPQUAL_PROFILE_ID=urban-market-regression", "MPQUAL_PROFILE_ID=mutated"
        ),
        "MUTATED_REVIEW": text.replace(
            "MPQUAL_REVIEW_EVENTS=1", "MPQUAL_REVIEW_EVENTS=0"
        ),
        "OMITTED_ANNEX_LINE": text.replace(
            snapshot["sample"]["used_row_ids"][0], "omitted-row"
        ),
    }
    for code, mutated_text in mutations.items():
        result = verify_report_consistency(
            pdf, snapshot, context, extracted_text=mutated_text
        )
        assert any(item["code"] == code for item in result["findings"]), (code, result)

    req = {
        "schema_version": "MP-REQ-MAP/1",
        "profile_id": "urban-market-regression",
        "source": {"id": "synthetic-source", "version": "test"},
        "requirements": [
            {"id": "TEST-RULE-01", "evidence": "qualification/document_state.json"}
        ],
    }
    package = build_submission_package(
        snapshot,
        context,
        pdf_bytes=pdf,
        dossier_bytes=_dossier_bytes(snapshot),
        requirement_map=req,
    )
    with zipfile.ZipFile(io.BytesIO(package), "r") as source:
        files = {name: source.read(name) for name in source.namelist()}
    files["document/report.pdf"] += b"tamper"
    changed = io.BytesIO()
    with zipfile.ZipFile(changed, "w") as target:
        for name, data in files.items():
            target.writestr(name, data)
    finding_codes = {
        item["code"]
        for item in verify_submission_package(changed.getvalue())["findings"]
    }
    assert "SUBMISSION_HASH_MISMATCH" in finding_codes

    request = prepare_signature_request(
        pdf,
        snapshot,
        revision_id="rev-test-001",
        profile_id="urban-market-regression",
        report_context=context,
    )
    fake_signed = pdf + b"signed-fixture"
    signature = record_external_signature(
        fake_signed,
        request,
        unsigned_pdf=pdf,
        verification={
            "status": "valid",
            "signed_pdf_sha256": __import__("hashlib").sha256(fake_signed).hexdigest(),
            "backend": "synthetic-test-verifier",
        },
    )
    signature = dict(
        signature,
        status="valid",
        backend="pyHanko",
        incremental_base_verified=True,
        local_verification={"status": "valid", "signature_count": 1},
    )  # synthetic binding fixture, not signature evidence
    mutated_snapshot = deepcopy(snapshot)
    mutated_snapshot["provenance"]["qualification_context"]["resolved_profile"][
        "value_basis"
    ] = "mutated"
    signature_check = verify_signature_binding(
        fake_signed,
        signature,
        mutated_snapshot,
        revision_id="rev-test-001",
        unsigned_pdf=pdf,
        report_context=context,
    )
    assert any(
        item["code"] == "SIGNED_SNAPSHOT_HASH_MISMATCH"
        for item in signature_check["findings"]
    )
