"""Allowlisted synthetic browser evidence for CI; never collect credentials."""
import hashlib
import json
import os
from pathlib import Path
import shutil


def collect_browser_evidence(root: Path, *, namespace: str) -> None:
    configured = os.environ.get("C17_UI_EVIDENCE")
    if not configured:
        return
    target = Path(configured) / namespace
    target.mkdir(parents=True, exist_ok=True)
    allowed = {
        "report.pdf", "report.docx", "signed_report.pdf", "evidence_bundle.zip",
        "submission.zip", "document_history.zip", "signature_request.json",
        "SYNTHETIC_TEST_unsigned_report.pdf", "SYNTHETIC_TEST_signed_report.pdf",
        "browser-document-flow-failure.png", "browser-document-flow-body.txt",
        "browser-cost-flow-failure.png", "browser-cost-flow-body.txt",
    }
    inventory = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name not in allowed:
            continue
        relative = path.relative_to(root)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        data = destination.read_bytes()
        inventory.append({"path": relative.as_posix(), "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
    (target / "artifact-inventory.json").write_text(json.dumps({
        "schema": "MP-C06-BROWSER-EVIDENCE/1", "synthetic_test_only": True,
        "files": inventory, "credentials_collected": False,
    }, indent=2), encoding="utf-8")
