"""Evidence collection cannot copy private signing or runtime credential files."""
import json

from tests.comercial.browser_evidence import collect_browser_evidence


def test_browser_evidence_uses_namespaces_and_excludes_secrets(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "report.pdf").write_bytes(b"SYNTHETIC TEST collector fixture")
    (source / "private-key.pem").write_text("SYNTHETIC TEST SECRET")
    (source / "runtime-credentials.json").write_text("SYNTHETIC TEST SECRET")
    output = tmp_path / "evidence"
    monkeypatch.setenv("C17_UI_EVIDENCE", str(output))
    collect_browser_evidence(source, namespace="c06-document-flow")
    collect_browser_evidence(source, namespace="c06-cost-flow")
    for name in ("c06-document-flow", "c06-cost-flow"):
        files = {path.name for path in (output / name).iterdir()}
        assert files == {"report.pdf", "artifact-inventory.json"}
        inventory = json.loads((output / name / "artifact-inventory.json").read_text())
        assert inventory["synthetic_test_only"] is True
        assert inventory["files"][0]["path"] == "report.pdf"
        assert len(inventory["files"][0]["sha256"]) == 64
