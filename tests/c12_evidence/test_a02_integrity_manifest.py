"""C12-A02: one-byte tamper is detected; manifest has no circular self-hash."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from modules.evidence_bundle import build_evidence_bundle, verify_bundle

from .helpers import make_complete_evaluation

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "c12_reproduce" / "reproduce.py"


def test_manifest_lists_file_digests_without_self_hash(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    manifest = build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    on_disk = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert "sha256" not in on_disk
    assert "self_hash" not in on_disk
    assert "manifest_sha256" not in json.dumps(on_disk)
    for entry in on_disk["files"]:
        for key in ("sha256", "size", "type", "version", "function", "path"):
            assert key in entry and entry[key] is not None and entry[key] != ""
        assert entry["path"] != "MANIFEST.json"
    assert on_disk["input_id"]
    assert on_disk["code_id"]
    assert on_disk["schema_id"]
    assert on_disk["policy_id"]
    result = verify_bundle(out)
    assert result["ok"] is True
    assert result["manifest_has_self_hash"] is False
    assert result["versions"]["compatible"] is True


def test_one_byte_change_is_detected_by_verify_and_cli(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    target = out / "data" / "used_sample.csv"
    data = bytearray(target.read_bytes())
    assert len(data) > 10
    data[10] = data[10] ^ 0x01
    target.write_bytes(bytes(data))

    result = verify_bundle(out)
    assert result["ok"] is False
    assert any("hash mismatch" in err for err in result["errors"])

    proc = subprocess.run(
        [sys.executable, str(CLI), "--bundle", str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["integrity"]["ok"] is False
