"""C12-A05: missing parts are completeness gaps; share copy does not remove original."""

from __future__ import annotations

import json

from modules.evidence_bundle import (
    build_evidence_bundle,
    export_share_copy,
    strip_dataset_from_log_payload,
)
from modules.provenance import COMPLETENESS_MISSING

from .helpers import SYNTHETIC_LABEL, make_complete_evaluation, make_incomplete_evaluation


def _statuses(bundle) -> dict:
    ledger = json.loads((bundle / "completeness" / "ledger.json").read_text(encoding="utf-8"))
    return {item["component"]: item for item in ledger["items"]}


def test_missing_base_policy_photo_and_version_are_faltante_not_fabricated(tmp_path):
    ev = make_incomplete_evaluation()
    out = tmp_path / "bundle"
    manifest = build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    items = _statuses(out)
    assert items["original_base"]["status"] == COMPLETENESS_MISSING
    assert items["interpreted_base"]["status"] == COMPLETENESS_MISSING
    assert items["missing_policy"]["status"] == COMPLETENESS_MISSING
    assert items["outlier_policy"]["status"] == COMPLETENESS_MISSING
    assert items["search_policy"]["status"] == COMPLETENESS_MISSING
    assert items["evaluation_policy"]["status"] == COMPLETENESS_MISSING
    assert items["photos_documents"]["status"] == COMPLETENESS_MISSING
    assert items["versions"]["status"] == COMPLETENESS_MISSING
    assert items["model_coefficients"]["status"] == COMPLETENESS_MISSING

    assert not (out / "data" / "original_base.csv").exists()
    assert not (out / "policies" / "missing_policy.json").exists()
    docs = list((out / "artifacts" / "documents").glob("*")) if (out / "artifacts" / "documents").exists() else []
    assert docs == []
    # No generated stand-in image or caption file.
    for path in out.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            text_head = path.read_bytes()[:200].lower()
            assert b"generated photo" not in text_head
            assert b"fachada sintet" not in text_head

    assert manifest["reproduction"]["promised"] is False
    assert "original_base" in manifest["completeness_missing"]
    assert "photos_documents" in manifest["completeness_missing"]


def test_share_copy_does_not_remove_original_and_log_guard_redacts_dataset(tmp_path):
    ev = make_complete_evaluation()
    original = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], original
    )
    dest = tmp_path / "share"
    result = export_share_copy(original, dest)
    assert result["original_retained"] is True
    assert (original / "data" / "original_base.csv").is_file()
    assert (original / "MANIFEST.json").is_file()
    # Default share selection omits the raw market base.
    assert not (dest / "data" / "original_base.csv").exists()
    assert (dest / "SHARE_MANIFEST.json").is_file()

    leaked = strip_dataset_from_log_payload(
        {
            "event": "bundle_built",
            "raw_frame": ev["input_bundle"]["raw_frame"],
            "n": ev["n"],
            "source_bytes": b"secret-market-file",
        }
    )
    assert leaked["raw_frame"] == "<redacted: dataset not logged>"
    assert "Rua Sintetica" not in json.dumps(leaked)
    assert "secret-market-file" not in json.dumps(leaked)
    assert leaked["n"] == ev["n"]
    assert ev["label"] == SYNTHETIC_LABEL
