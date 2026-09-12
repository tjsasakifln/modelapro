from __future__ import annotations

import hashlib
import json

import pytest

from modules.evidence_bundle import (
    assess_bundle_status,
    build_evidence_bundle,
    reproduce_from_bundle,
    verify_bundle,
)
from modules.provenance import canonical_json
from modules.report_export import build_docx
from modules.report_presenter.qualification import signable_snapshot_sha256
from tests.c12_evidence.helpers import make_complete_evaluation

from .fixtures import qualification_context


def test_a04_maps_representations_reviews_and_separates_three_statuses(tmp_path):
    ev = make_complete_evaluation(n=220, n_excluded=10)
    ev["snapshot"].setdefault("provenance", {})["qualification_context"] = (
        qualification_context()
    )
    point = ev["snapshot"]["value"]["point"]
    ev["artifacts"]["value_policy"] = {
        "arbitration": {"method": "percent_around_point", "percent": 15},
        "admissible": {
            "method": "intersection",
            "inputs": ["mean_ci80", "arbitration_interval"],
        },
        "adopted": {"method": "point"},
    }
    ev["snapshot"]["value"]["arbitration_interval"] = {
        "lower": point * 0.85,
        "upper": point * 1.15,
    }
    mean = ev["snapshot"]["value"]["mean_ci80"]
    ev["snapshot"]["value"]["admissible_interval"] = {
        "lower": max(mean["lower"], point * 0.85),
        "upper": min(mean["upper"], point * 1.15),
    }
    ev["artifacts"]["report_docx"] = {
        "bytes": build_docx(ev["snapshot"], {}),
        "filename": "report.docx",
        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    out = tmp_path / "dossier"
    manifest = build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    assert (out / "qualification" / "context.json").is_file()
    assert (out / "data" / "identifier_map.json").is_file()
    assert (out / "data" / "representation_map.json").is_file()
    assert (out / "review" / "history.json").is_file()
    assert manifest["integrity_status"] == "assembled_unverified"
    reproduction = reproduce_from_bundle(out)
    assert reproduction["numerical_reproduction_status"] == "verified"
    assert reproduction["arbitration_interval"] == pytest.approx(
        ev["snapshot"]["value"]["arbitration_interval"]
    )
    assert reproduction["admissible_interval"] == pytest.approx(
        ev["snapshot"]["value"]["admissible_interval"]
    )
    statuses = assess_bundle_status(out)
    assert statuses["integrity_status"] == "verified"
    assert statuses["numerical_reproduction_status"] == "verified"
    assert statuses["completeness_status"] in {"complete", "incomplete"}
    representation = json.loads((out / "data" / "representation_map.json").read_text())
    assert representation["row_identity"] == "row_id"


def test_a04_signed_pdf_and_signature_record_must_cross_bind(tmp_path):
    ev = make_complete_evaluation()
    ev["snapshot"].setdefault("provenance", {})["qualification_context"] = (
        qualification_context()
    )
    unsigned = ev["artifacts"]["report_pdf"]["bytes"]
    foreign_signed = b"%PDF-1.7\nforeign signed content"
    ev["artifacts"]["signed_report_pdf"] = foreign_signed
    ev["artifacts"]["signature_record"] = {
        "schema_version": "MP-SIGN/1",
        "status": "valid",
        "backend": "pyHanko",
        "signature_count": 1,
        "incremental_base_verified": True,
        "unsigned_pdf_sha256": hashlib.sha256(unsigned).hexdigest(),
        "signed_pdf_sha256": hashlib.sha256(foreign_signed).hexdigest(),
        "snapshot_sha256": signable_snapshot_sha256(ev["snapshot"]),
        "result_fingerprint": ev["snapshot"]["provenance"]["qualification_context"][
            "result_fingerprint"
        ],
        "revision_id": "rev-test",
        "local_verification": {"status": "valid", "signature_count": 1},
    }
    out = tmp_path / "dossier"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    result = verify_bundle(out)
    assert result["ok"] is False
    assert any("not an incremental revision" in item for item in result["errors"])


def test_a04_refuses_snapshot_bytes_from_a_different_evaluation(tmp_path):
    ev = make_complete_evaluation()
    different = dict(ev["snapshot"], job_id="different-evaluation")
    ev["artifacts"]["snapshot_bytes"] = canonical_json(different).encode("utf-8")
    with pytest.raises(ValueError, match="does not represent"):
        build_evidence_bundle(
            ev["snapshot"],
            ev["input_bundle"],
            ev["prepared_dataset"],
            ev["artifacts"],
            tmp_path / "dossier",
        )
