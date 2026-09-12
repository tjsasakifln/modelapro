"""SYNTHETIC local installation: real ASGI guards stay enabled in every test."""
import base64
from datetime import date, timedelta
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from modules.commercial_license import make_signed_envelope
from modules.operacao_local.runtime import local_client_headers

pytestmark = pytest.mark.raw_local_auth


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "SYNTHETIC_TEST_bearer_0123456789")
    monkeypatch.setenv("LOCAL_CSRF_SECRET", base64.urlsafe_b64encode(b"SYNTHETIC_CSRF_TEST_SECRET_012345").decode())
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("MODELA_LICENSE_PUBLIC_KEY", base64.urlsafe_b64encode(public).decode())
    license_path = tmp_path / "SYNTHETIC_TEST_entitlement.json"
    monkeypatch.setenv("MODELA_LICENSE_PATH", str(license_path))

    def license_for(days):
        license_path.write_text(json.dumps(make_signed_envelope({
            "license_id": "SYNTHETIC_TEST_ONLY", "expires_on": (date.today() + timedelta(days=days)).isoformat(),
            "rights": ["calculate", "read", "export"],
        }, private)))
    license_for(2)
    from backend import api
    from modules.job_store import JobStore
    from modules.project_store import ProjectStore
    store = JobStore(tmp_path / "store")
    api.bind_runtime(job_store=store, project_store=ProjectStore(store.root))
    with TestClient(api.app) as client:
        yield client, local_client_headers(), license_for
    api.reset_runtime()


@pytest.mark.parametrize("path", ["/preview", "/jobs", "/upload", "/projects", "/operations/backup"])
def test_missing_bearer_rejected_on_actual_routes(installation, path):
    client, _, _ = installation
    assert client.request("GET" if path in {"/projects", "/operations/backup"} else "POST", path).status_code == 403


@pytest.mark.parametrize("field,value", [("Authorization", "Bearer wrong"), ("Origin", "http://evil.example"),
                                        ("X-CSRF-Token", ""), ("X-Workspace-ID", "other")])
def test_bad_credentials_origin_csrf_workspace_rejected(installation, field, value):
    client, headers, _ = installation
    headers[field] = value
    assert client.post("/preview", headers=headers).status_code == 403


def test_legitimate_guards_reach_real_parser_and_reject_traversal(installation):
    client, headers, _ = installation
    assert client.get("/projects", headers=headers).status_code == 200
    spec = {"schema_version": "MP/1", "target_col": "preco", "candidate_cols": ["area"],
            "roles": {"preco": "target", "area": "predictor"}}
    data = {"request_json": json.dumps(spec)}
    csv = b"area,preco\n10,100\n20,200\n30,300\n"
    assert client.post("/preview", headers=headers, data=data, files={"file": ("../data.csv", csv)}).status_code == 400
    response = client.post("/preview", headers=headers, data=data, files={"file": ("data.csv", csv)})
    assert response.status_code == 200, response.text


def test_expired_license_preserves_read_but_blocks_new_calculation(installation):
    client, headers, license_for = installation
    license_for(-1)
    assert client.get("/projects", headers=headers).status_code == 200
    response = client.post("/jobs", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"] == "LICENSE_CALCULATION_NOT_PERMITTED"


def test_websocket_cross_origin_and_url_secret_rejected(installation):
    from starlette.websockets import WebSocketDisconnect
    client, headers, _ = installation
    for path, origin in [("/ws", "http://evil.example"), ("/ws?token=secret", headers["Origin"])]:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path, headers={**headers, "Origin": origin}):
                pytest.fail("guard accepted forbidden WebSocket")


def test_job_token_recovery_requires_authenticated_workspace_and_csrf(installation):
    from backend import api
    client, headers, _ = installation
    record = api.get_job_store().create(payload={"filename": "SYNTHETIC_TEST.csv"})
    path = f"/jobs/{record['job_id']}/access-token"
    assert client.post(path).status_code == 403
    assert client.post(path, headers={**headers, "X-CSRF-Token": "wrong"}).status_code == 403
    response = client.post(path, headers=headers)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["access_token"] == record["access_token"]


def test_real_backup_restore_preserves_bytes_and_survives_runtime_reset(installation, monkeypatch, tmp_path):
    from backend import api
    from modules.job_store import JobStore
    from modules.project_store import ProjectStore
    client, headers, license_for = installation
    store = api.get_job_store()
    record = store.create(payload={"filename": "SYNTHETIC_TEST.csv"})
    store.save_artifact(record["job_id"], "report.pdf", b"%PDF-SYNTHETIC_TEST")
    license_for(-1)
    exported = client.get("/operations/backup", headers=headers)
    assert exported.status_code == 200
    assert exported.content.startswith(b"PK")
    # Restoration over evidence is refused; a clean workspace is explicitly used.
    files = {"file": ("backup.zip", exported.content, "application/zip")}
    assert client.post("/operations/restore", headers=headers, files=files).status_code == 409
    empty = JobStore(tmp_path / "clean")
    api.bind_runtime(job_store=empty, project_store=ProjectStore(empty.root))
    restored = client.post("/operations/restore", headers=headers, files=files)
    assert restored.status_code == 200, restored.text
    api.reset_runtime()
    assert api.get_job_store().get_artifact(record["job_id"], "report.pdf") == b"%PDF-SYNTHETIC_TEST"


@pytest.mark.parametrize("member", ["../escape", "C:/escape", "..\\escape"])
def test_restore_refuses_unsafe_archive_members(installation, member):
    import io
    import zipfile
    client, headers, _ = installation
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "SYNTHETIC_TEST")
    response = client.post("/operations/restore", headers=headers,
                           files={"file": ("backup.zip", buffer.getvalue())})
    assert response.status_code == 400
