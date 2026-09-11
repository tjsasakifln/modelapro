"""C12-A04: raw formula cells preserved; visualization neutralized; traversal rejected."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from modules.evidence_bundle import build_evidence_bundle, verify_bundle
from modules.provenance import is_formula_cell, neutralize_formula_cell, resolve_inside

from .helpers import FORMULA_CELL, make_complete_evaluation


def test_raw_csv_keeps_formula_and_visualization_is_safe(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    raw_path = out / "data" / "original_base.csv"
    viz_path = out / "data" / "visualization" / "original_base.safe.csv"
    raw_text = raw_path.read_text(encoding="utf-8")
    viz_text = viz_path.read_text(encoding="utf-8")
    assert FORMULA_CELL in raw_text
    assert FORMULA_CELL in ev["input_bundle"]["raw_frame"][0]["observacao"]
    # Visualization must not leave an executable leading '=' cell.
    with viz_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with raw_path.open("r", encoding="utf-8", newline="") as fh:
        raw_rows = list(csv.DictReader(fh))
    assert raw_rows[0]["observacao"] == FORMULA_CELL
    assert is_formula_cell(raw_rows[0]["observacao"])
    safe = rows[0]["observacao"]
    assert safe == neutralize_formula_cell(FORMULA_CELL)
    assert safe.startswith("'")
    assert not safe.startswith("=")
    assert FORMULA_CELL not in viz_text.splitlines()[1] or safe.startswith("'")
    # Units / encoding documented next to the CSV.
    meta = (out / "data" / "original_base.csv.meta.json").read_text(encoding="utf-8")
    assert "utf-8" in meta
    assert "BRL" in meta
    assert "m2" in meta


def test_path_traversal_artifact_stays_inside_bundle(tmp_path):
    ev = make_complete_evaluation()
    ev["artifacts"]["files"] = {
        "../../etc/passwd": {"bytes": b"not-a-secret", "filename": "../../etc/passwd"}
    }
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    # Nothing written outside the bundle root.
    escaped = tmp_path / "etc" / "passwd"
    assert not escaped.exists()
    outside = Path("/tmp/c12-should-not-exist-passwd")
    assert not outside.exists() or outside.read_bytes() != b"not-a-secret"
    stored = list((out / "artifacts").rglob("*"))
    assert stored
    for path in stored:
        path.resolve().relative_to(out.resolve())


def test_resolve_inside_rejects_traversal(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_inside(root, "../secret")
    with pytest.raises(ValueError):
        resolve_inside(root, "/etc/passwd")
    with pytest.raises(ValueError):
        resolve_inside(root, "ok/../../etc/passwd")


def test_unexpected_python_file_is_not_executed(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    marker = tmp_path / "executed.flag"
    evil = out / "pwn.py"
    evil.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    result = verify_bundle(out)
    assert result["ok"] is False
    assert any("unexpected" in err for err in result["errors"])
    assert not marker.exists()
