from io import BytesIO
import zipfile

import pytest

from modules.operacao_local import (
    AccessDenied, LocalSecurityPolicy, UploadPolicy, WorkspacePathResolver,
    redact_diagnostic, validate_upload,
)


def policy():
    return LocalSecurityPolicy("a" * 24, frozenset({"http://127.0.0.1:8501"}), b"b" * 32)


def test_loopback_does_not_bypass_bearer_origin_or_csrf():
    security = policy()
    with pytest.raises(AccessDenied):
        security.authorize(
            method="POST", authorization=None,
            origin="http://127.0.0.1:8501", csrf_token=security.csrf_token(),
        )
    with pytest.raises(AccessDenied):
        security.authorize(
            method="POST", authorization="Bearer " + "a" * 24,
            origin="http://evil.example", csrf_token=security.csrf_token(),
        )
    with pytest.raises(AccessDenied):
        security.authorize(method="POST", authorization="Bearer " + "a" * 24, origin="http://127.0.0.1:8501")
    security.authorize(method="POST", authorization="Bearer " + "a" * 24,
                       origin="http://127.0.0.1:8501", csrf_token=security.csrf_token())


def test_upload_validation_rejects_path_magic_and_zip_bomb():
    with pytest.raises(ValueError):
        validate_upload("../private.csv", b"a,b\n1,2\n")
    with pytest.raises(ValueError):
        validate_upload("market.csv", b"%PDF-not-csv")
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("../escape.csv", "x" * 10)
    archive_policy = UploadPolicy(allowed_extensions=frozenset({".zip"}))
    with pytest.raises(ValueError, match="unsafe"):
        validate_upload("input.zip", stream.getvalue(), archive_policy)
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("..\\escape.csv", "x" * 10)
    with pytest.raises(ValueError, match="unsafe"):
        validate_upload("input.zip", stream.getvalue(), archive_policy)
    with pytest.raises(ValueError, match="not allowed"):
        validate_upload("report.pdf", b"%PDF-synthetic")
    meta = validate_upload("market.csv", b"price,area\n100,10\n")
    assert meta["filename"] == "market.csv" and "sha256" in meta
    legacy = validate_upload("market.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic")
    assert legacy["extension"] == ".xls"


def test_workspace_isolation_and_diagnostics_redaction(tmp_path):
    paths = WorkspacePathResolver(tmp_path)
    assert paths.project_path("customer-a", "project-1") == (tmp_path / "customer-a" / "project-1").resolve()
    with pytest.raises(AccessDenied):
        paths.project_path("customer-a", "../../other")
    with pytest.raises(AccessDenied):
        paths.require_workspace("customer-a", "customer-b")
    safe = redact_diagnostic({
        "token": "do-not-log",
        "email": "ana@example.test",
        "raw": b"private",
        "client_name": "Pessoa identificada",
        "message": "CNPJ 12.345.678/0001-90",
    })
    assert safe["token"] == "<redacted>"
    assert "ana@example.test" not in safe["email"]
    assert "private" not in safe["raw"]
    assert safe["client_name"] == "<redacted>"
    assert "12.345.678/0001-90" not in safe["message"]
