"""SYNTHETIC local installation: real ASGI guards stay enabled in every test."""
import asyncio
import base64
from datetime import date, timedelta
import io
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


@pytest.mark.parametrize("path", ["/preview", "/jobs", "/upload", "/projects", "/operations/backup", "/jobs/test/recipient-return"])
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


def test_credentials_in_urls_are_rejected_even_percent_encoded(installation):
    client, headers, _ = installation
    for query in ("access_token=secret", "%61ccess_token=secret", "token=secret"):
        assert client.get("/jobs/unknown/result?" + query, headers=headers).status_code == 403


def test_report_signature_context_requires_offline_revocation_even_when_empty(
    monkeypatch,
):
    from backend import document_routes
    import pyhanko_certvalidator

    monkeypatch.setenv("MODELA_REPORT_SIGNATURE_TRUST_ROOTS", "root.der")
    monkeypatch.delenv("MODELA_REPORT_SIGNATURE_CRLS", raising=False)
    monkeypatch.delenv("MODELA_REPORT_SIGNATURE_OCSPS", raising=False)
    loaded = {"MODELA_REPORT_SIGNATURE_TRUST_ROOTS": ["root"]}
    monkeypatch.setattr(
        document_routes,
        "_load_operator_asn1",
        lambda environment_name, *_args, **_kwargs: loaded.get(environment_name, []),
    )
    captured = {}

    class FakeValidationContext:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(pyhanko_certvalidator, "ValidationContext", FakeValidationContext)

    document_routes._configured_signature_validation_context()

    assert captured == {
        "trust_roots": ["root"],
        "crls": [],
        "ocsps": [],
        "revocation_mode": "require",
        "allow_fetching": False,
    }


def test_report_signature_context_loads_only_operator_paths(monkeypatch):
    from backend import document_routes
    import pyhanko_certvalidator

    monkeypatch.setenv("MODELA_REPORT_SIGNATURE_TRUST_ROOTS", "root.der")
    monkeypatch.setenv("MODELA_REPORT_SIGNATURE_CRLS", "issuer.crl")
    monkeypatch.setenv("MODELA_REPORT_SIGNATURE_OCSPS", "issuer.ocsp")
    loaded = {
        "MODELA_REPORT_SIGNATURE_TRUST_ROOTS": ["root"],
        "MODELA_REPORT_SIGNATURE_CRLS": ["crl"],
        "MODELA_REPORT_SIGNATURE_OCSPS": ["ocsp"],
    }
    calls = []

    def load(environment_name, *_args, **_kwargs):
        calls.append(environment_name)
        return loaded[environment_name]

    monkeypatch.setattr(document_routes, "_load_operator_asn1", load)
    captured = {}
    monkeypatch.setattr(
        pyhanko_certvalidator,
        "ValidationContext",
        lambda **kwargs: captured.update(kwargs) or captured,
    )

    assert document_routes._configured_signature_validation_context() is captured
    assert calls == [
        "MODELA_REPORT_SIGNATURE_TRUST_ROOTS",
        "MODELA_REPORT_SIGNATURE_CRLS",
        "MODELA_REPORT_SIGNATURE_OCSPS",
    ]
    assert captured["crls"] == ["crl"]
    assert captured["ocsps"] == ["ocsp"]
    assert captured["revocation_mode"] == "require"
    assert captured["allow_fetching"] is False


def test_signature_import_passes_offline_context_to_worker_thread(monkeypatch):
    from backend import document_routes
    from starlette.datastructures import UploadFile

    captured = {}

    class Workflow:
        class DocumentWorkflowError(Exception):
            pass

        @staticmethod
        def import_signed_report(store, job_id, *, signed_pdf, validation_context):
            captured.update(
                store=store,
                job_id=job_id,
                signed_pdf=signed_pdf,
                validation_context=validation_context,
            )
            return {"status": "received"}

    monkeypatch.setattr(document_routes, "_authorized_store", lambda *_args: "store")
    monkeypatch.setattr(document_routes, "_document_workflow", lambda: Workflow)
    monkeypatch.setattr(
        document_routes, "_configured_signature_validation_context", lambda: "offline-context"
    )
    upload = UploadFile(io.BytesIO(b"%PDF-SYNTHETIC"), filename="signed.pdf")

    result = asyncio.run(
        document_routes.document_signature_import("job", upload, "token")
    )

    assert result == {"status": "received"}
    assert captured == {
        "store": "store",
        "job_id": "job",
        "signed_pdf": b"%PDF-SYNTHETIC",
        "validation_context": "offline-context",
    }


def test_docx_served_with_office_mime_and_attachment(installation):
    from backend import api
    client, headers, _ = installation
    store = api.get_job_store()
    job = store.create()
    store.save_artifact(job["job_id"], "report.docx", b"SYNTHETIC_DOCX_BYTES")
    response = client.get(f"/jobs/{job['job_id']}/artifacts/report.docx", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.headers["content-disposition"] == 'attachment; filename="report.docx"'


def test_saved_revision_uses_linked_job_not_edited_form_or_other_snapshot(installation):
    from backend import api
    client, headers, _ = installation
    jobs = api.get_job_store()
    job = jobs.create(payload={"synthetic_test_only": True})
    jid = job["job_id"]
    frozen = {"schema_version": "MP/1", "request_spec": {"reference_date": "2026-09-12"},
              "model_state": {"coefficients": [1, 2]}, "value": {"point": 920}}
    snapshot = {"schema_version": "MP/1", "job_id": jid, "value": {"point": 920}}
    jobs.save_snapshot(jid, snapshot)
    jobs.save_artifact(jid, "frozen_project.json", json.dumps(frozen).encode())
    url = "/projects/SYNTHETIC_TEST/revisions"
    for delta in ({"request_spec": {"reference_date": "2020-01-01"}},
                  {"value": {"point": 999}}, {"model_state": {"coefficients": [9, 9]}},
                  {"snapshot_ref": {"job_id": "other"}}):
        assert client.post(url, headers=headers, json={"job_id": jid, **delta}).status_code == 409
    result = client.post(url, headers=headers, json={"job_id": jid, "snapshot_ref": {"job_id": jid}})
    assert result.status_code == 201, result.text
    revision = api.get_project_store().load_revision("SYNTHETIC_TEST", result.json()["revision_id"])
    assert revision["request_spec"] == frozen["request_spec"]
    assert revision["value"] == snapshot["value"]
    assert revision["model_state"] == frozen["model_state"]
    assert len(revision["frozen_project_sha256"]) == len(revision["snapshot_sha256"]) == 64


def test_license_body_cap_precedes_parser_with_length_and_chunked(installation):
    client, headers, _ = installation
    assert client.post("/operations/license", content=b"x" * 65537, headers=headers).status_code == 413
    consumed = []
    def chunks():
        for index in range(3):
            consumed.append(index)
            yield b"x" * 32768
    response = client.post("/operations/license", content=chunks(), headers=headers)
    assert response.status_code == 413
    # The ASGI boundary, not json.loads/install_license, rejects these bytes.
    assert "REQUEST_BODY_TOO_LARGE" in response.text


def test_restore_excludes_concurrent_submission_and_second_restore(installation, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from starlette.datastructures import UploadFile
    from backend import api
    client, headers, _ = installation
    archive = client.get("/operations/backup", headers=headers).content
    entered, release = Event(), Event()
    original_read = UploadFile.read
    async def paused_read(file, size=-1):
        if file.filename == "SYNTHETIC_restore.zip":
            entered.set()
            assert release.wait(10), "test barrier timeout"
        return await original_read(file, size)
    monkeypatch.setattr(UploadFile, "read", paused_read)
    def restore():
        with TestClient(api.app) as other:
            return other.post("/operations/restore", headers=headers,
                              files={"file": ("SYNTHETIC_restore.zip", archive, "application/zip")})
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(restore)
        try:
            assert entered.wait(10), "restore did not reach guarded upload"
            assert client.post("/jobs", headers=headers).status_code == 409
            assert client.post("/operations/restore", headers=headers).status_code == 409
            assert not api.get_job_store().list_jobs()
        finally:
            release.set()
        response = pending.result(timeout=10)
    assert response.status_code == 200, response.text


def test_real_ui_websocket_consumer_with_enabled_guards(installation, monkeypatch):
    import socket
    import threading
    import time
    import uvicorn
    from backend import api
    from frontend.app import _maybe_listen_websocket
    monkeypatch.delenv("MODELA_DISABLE_WS", raising=False)
    record = api.get_job_store().create()
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", access_log=False, lifespan="off"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "NOT_RUN: real WebSocket server failed to start"
            url = f"ws://127.0.0.1:{port}/ws"
            result = _maybe_listen_websocket(record["job_id"], url, record["access_token"])
            assert result == {"status": "connected", "job_id": record["job_id"]}
            assert _maybe_listen_websocket(record["job_id"], url, "wrong")["status"] == "rejected_job"
            assert _maybe_listen_websocket(record["job_id"], "ws://evil.example/ws", "TEST")["status"] == "rejected_destination"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert not thread.is_alive()


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
