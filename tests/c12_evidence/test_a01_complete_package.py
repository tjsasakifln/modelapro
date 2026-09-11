"""C12-A01: package with n>200 keeps complete used/excluded tables and matching IDs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from modules.evidence_bundle import build_evidence_bundle

from .helpers import SYNTHETIC_LABEL, make_complete_evaluation


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_complete_package_n_gt_200_ids_match_sample_and_coefficients(tmp_path):
    ev = make_complete_evaluation(n=220, n_excluded=10)
    assert ev["label"] == SYNTHETIC_LABEL
    assert ev["n"] > 200

    out = tmp_path / "bundle"
    manifest = build_evidence_bundle(
        ev["snapshot"],
        ev["input_bundle"],
        ev["prepared_dataset"],
        ev["artifacts"],
        out,
    )

    used = _read_csv(out / "data" / "used_sample.csv")
    excluded = _read_csv(out / "data" / "excluded_rows.csv")
    original = _read_csv(out / "data" / "original_base.csv")
    ident = _read_csv(out / "data" / "identification_columns.csv")

    assert len(original) == ev["n"]
    assert len(used) == ev["n_used"] == ev["snapshot"]["sample"]["used"]
    assert len(excluded) == ev["n_excluded"] == ev["snapshot"]["sample"]["excluded"]
    assert [row["row_id"] for row in used] == ev["used_ids"]
    assert [row["row_id"] for row in excluded] == ev["excluded_ids"]

    ident_ids = [row["row_id"] for row in ident]
    assert ident_ids == [r["row_id"] for r in ev["input_bundle"]["raw_frame"]]
    assert all(row.get("endereco") for row in ident)
    assert all(row.get("fonte") == "fixture-synthetic" for row in ident)

    coef = json.loads((out / "model" / "coefficients.json").read_text(encoding="utf-8"))
    assert coef["order"] == ["const", "area", "quartos"]
    assert len(coef["order"]) == len(ev["snapshot"]["model"]["coefficients"])
    assert coef["values"]["const"]["text"]
    # Integral encoding, not the 4-decimal display formula.
    assert "20000.0000 +" not in json.dumps(coef)

    sample_audit = json.loads((out / "meta" / "sample_audit.json").read_text(encoding="utf-8"))
    assert sample_audit["used_table_rows"] == ev["n_used"]
    assert sample_audit["n_coefficients"] == 3
    assert sample_audit["received_rows"] == ev["n"]

    functions = {entry["function"] for entry in manifest["files"]}
    assert "c08_report_pdf" in functions
    assert "effective_sample" in functions
    # PDF present does not replace or truncate the market tables.
    assert len(used) > 200 or (len(used) + len(excluded)) > 200
    assert len(original) > 200

    for entry in manifest["files"]:
        assert entry["sha256"]
        assert isinstance(entry["size"], int) and entry["size"] >= 0
        assert entry["type"]
        assert entry["version"]
        assert entry["function"]
    assert manifest.get("input_id") == ev["snapshot"]["input_sha256"]
    assert manifest.get("code_id") == ev["snapshot"]["code_sha"]
    assert manifest.get("schema_id")
    assert manifest.get("policy_id")
    assert "sha256" not in manifest
    assert "manifest_sha256" not in manifest
    assert all(entry.get("path") != "MANIFEST.json" for entry in manifest["files"])

    # Reproduction is promised because coefficients + subject + y transform are on disk.
    assert manifest["reproduction"]["promised"] is True
    assert (out / "MANIFEST.json").is_file()
    assert (out / "snapshot" / "result_snapshot.json").is_file()
