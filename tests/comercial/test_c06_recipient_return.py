"""Persisted recipient-return records remain evidence, never fabricated acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import RuntimeBindings, bind_runtime
from backend.recipient_routes import router
from modules.job_store import JobStore
from modules.provenance import canonical_json
from modules.qualification_profile import resolve_profile
from modules.qualification_profile.assessment import normalize_institution_receipt
from modules.report_export.recipient import (
    REGISTRY_ARTIFACT,
    RecipientReturnError,
    get_recipient_return_status,
    store_recipient_return,
)

DECLARATION = "RECEIVED_DOCUMENT_RECORDED_WITHOUT_AUTHENTICITY_OR_ACCEPTANCE_VERIFICATION"


def _case(tmp_path):
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    resolved = resolve_profile({"id": "bb-meci-avaliacao-imovel-pf"})
    profile = {
        key: resolved.get(key)
        for key in (
            "id",
            "version",
            "source_set_sha256",
            "purpose",
            "value_basis",
            "method",
            "asset_scope",
            "recipient_id",
        )
    }
    job = store.create(
        request_spec={
            "schema_version": "MP/1",
            "qualification_profile": profile,
            "recipient_id": profile["recipient_id"],
            "synthetic_test_only": True,
        },
        payload={"filename": "SYNTHETIC_TEST.csv"},
    )
    snapshot = {
        "schema_version": "MP/1",
        "job_id": job["job_id"],
        "value": {"point": 735000},
        "provenance": {"qualification_context": {"result_fingerprint": "a" * 64}},
    }
    store.save_snapshot(job["job_id"], snapshot)
    return store, job, snapshot


def _store_return(store, job_id, **overrides):
    fields = {
        "filename": "SYNTHETIC_TEST_retorno.txt",
        "media_type": "text/plain",
        "content": b"RETORNO SINTETICO DE TESTE - SEM VALIDADE EXTERNA",
        "recipient_id": "banco-do-brasil",
        "protocol": "PROTOCOLO-TESTE-001",
        "received_at": "2026-09-12T16:00:00-03:00",
        "source": "SYNTHETIC_TEST: importado localmente pelo operador",
        "operator_declaration": DECLARATION,
        "synthetic_test_only": True,
        "authorized_for_report": False,
    }
    fields.update(overrides)
    return store_recipient_return(store, job_id, **fields)


def test_persists_original_bytes_hash_profile_and_unverified_status(tmp_path):
    store, job, original_snapshot = _case(tmp_path)
    observed_artifacts = {
        "report.pdf": b"REPORT PDF BEFORE IMPORT",
        "signed_report.pdf": b"SIGNED PDF BEFORE IMPORT",
        "submission.zip": b"SUBMISSION BEFORE IMPORT",
    }
    for name, content in observed_artifacts.items():
        store.save_artifact(job["job_id"], name, content)

    result = _store_return(store, job["job_id"])

    record = result["record"]
    assert result["schema_version"] == "MP-RECIPIENT-RETURN/1"
    assert result["institution_acceptance"] == {
        "recorded": True,
        "record": record,
        "detail": (
            "Comprovante recebido e declarado pelo operador; autenticidade e "
            "aceite institucional não foram verificados."
        ),
    }
    assert record["status"] == "received_declared_unverified"
    assert record["institution_acceptance"] is False
    assert record["authenticity_verified"] is False
    assert record["bytes_integrity"] == "verified"
    immutable_record = {
        key: value
        for key, value in record.items()
        if key not in {"record_id", "bytes_integrity"}
    }
    assert record["record_id"] == hashlib.sha256(
        canonical_json(immutable_record).encode("utf-8")
    ).hexdigest()
    assert len(record["idempotency_key"]) == 64
    assert record["recipient_id"] == "banco-do-brasil"
    assert record["profile_id"] == "bb-meci-avaliacao-imovel-pf"
    assert record["protocol"] == "PROTOCOLO-TESTE-001"
    assert record["synthetic_test_only"] is True
    assert record["authorized_for_report"] is False
    state = record["case_state_at_import"]
    assert state["result_fingerprint"] == "a" * 64
    assert state["report_content_fingerprint"] is None
    assert state["association_to_sent_version_verified"] is False
    assert state["artifact_sha256"] == {
        name: hashlib.sha256(content).hexdigest()
        for name, content in observed_artifacts.items()
    }
    assert datetime.fromisoformat(record["received_at"]).tzinfo is not None
    assert store.get_artifact(job["job_id"], record["stored_name"]) == (
        b"RETORNO SINTETICO DE TESTE - SEM VALIDADE EXTERNA"
    )
    # A receipt received after signing is not allowed to rewrite numerical or
    # signed-report state. Future document composition consumes the sidecar.
    assert store.get_snapshot(job["job_id"]) == original_snapshot

    status = get_recipient_return_status(store, job["job_id"])
    assert status["latest"]["proof_sha256"] == record["proof_sha256"]
    assert status["latest"]["bytes_integrity"] == "verified"
    assert status["records"][0]["record_id"] == record["record_id"]
    assert normalize_institution_receipt(
        status["institution_acceptance"], resolve_profile(status["profile"])
    )["recorded"] is True


def test_rejects_recipient_mismatch_and_missing_operator_declaration(tmp_path):
    store, job, _snapshot = _case(tmp_path)

    with pytest.raises(RecipientReturnError, match="recipient does not match") as mismatch:
        _store_return(store, job["job_id"], recipient_id="caixa-economica-federal")
    assert mismatch.value.code == "RECIPIENT_PROFILE_MISMATCH"

    with pytest.raises(RecipientReturnError, match="operator declaration") as declaration:
        _store_return(store, job["job_id"], operator_declaration="valid=true")
    assert declaration.value.code == "RECIPIENT_DECLARATION_REQUIRED"
    assert get_recipient_return_status(store, job["job_id"])["records"] == []

    with pytest.raises(RecipientReturnError) as invalid_flag:
        _store_return(store, job["job_id"], authorized_for_report="false")
    assert invalid_flag.value.code == "RECIPIENT_RETURN_FLAGS_INVALID"


def test_same_exact_return_is_idempotent_and_preserves_history(tmp_path):
    store, job, _snapshot = _case(tmp_path)

    first = _store_return(store, job["job_id"])
    second = _store_return(store, job["job_id"])
    third = _store_return(
        store,
        job["job_id"],
        content=b"SEGUNDO RETORNO SINTETICO DE TESTE",
        filename="SYNTHETIC_TEST_retorno_2.txt",
        protocol="PROTOCOLO-TESTE-002",
        received_at=datetime.now(UTC).isoformat(),
    )

    assert second["record"]["record_id"] == first["record"]["record_id"]
    status = get_recipient_return_status(store, job["job_id"])
    assert [item["protocol"] for item in status["records"]] == [
        "PROTOCOLO-TESTE-001",
        "PROTOCOLO-TESTE-002",
    ]
    assert status["latest"]["record_id"] == third["record"]["record_id"]


def test_neutral_profile_cannot_invent_an_institution_from_root_recipient(tmp_path):
    store = JobStore(tmp_path / "neutral-store", recover_abandoned=False)
    profile = resolve_profile({"id": "abnt-14653-2-regressao-mercado"})
    job = store.create(
        request_spec={
            "schema_version": "MP/1",
            "qualification_profile": profile,
            "recipient_id": "banco-do-brasil",
        },
        payload={"filename": "SYNTHETIC_TEST.csv"},
    )

    with pytest.raises(RecipientReturnError) as missing:
        _store_return(store, job["job_id"])
    assert missing.value.code == "RECIPIENT_NOT_CONFIGURED"


def test_idempotent_retry_refuses_missing_or_tampered_original_bytes(tmp_path):
    store, job, _snapshot = _case(tmp_path)
    first = _store_return(store, job["job_id"])["record"]
    store.save_artifact(job["job_id"], first["stored_name"], b"TAMPERED")

    with pytest.raises(RecipientReturnError) as tampered:
        _store_return(store, job["job_id"])
    assert tampered.value.code == "RECIPIENT_RETURN_INTEGRITY_FAILED"


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("filename", "changed-name.pdf"),
        ("media_type", "application/pdf"),
        ("size", 999),
        ("recorded_at", "2026-09-12T23:59:00+00:00"),
        ("status", "accepted"),
    ],
)
def test_registry_metadata_tampering_invalidates_immutable_record(
    tmp_path, field, changed
):
    store, job, _snapshot = _case(tmp_path)
    _store_return(store, job["job_id"])
    registry = json.loads(
        store.get_artifact(job["job_id"], REGISTRY_ARTIFACT).decode("utf-8")
    )
    registry["records"][0][field] = changed
    store.save_artifact(
        job["job_id"],
        REGISTRY_ARTIFACT,
        canonical_json(registry).encode("utf-8"),
    )

    with pytest.raises(RecipientReturnError) as corrupted:
        get_recipient_return_status(store, job["job_id"])
    assert corrupted.value.code == "RECIPIENT_RETURN_RECORD_INVALID"


def test_rehashed_size_claim_still_must_match_original_bytes(tmp_path):
    store, job, _snapshot = _case(tmp_path)
    _store_return(store, job["job_id"])
    registry = json.loads(
        store.get_artifact(job["job_id"], REGISTRY_ARTIFACT).decode("utf-8")
    )
    record = registry["records"][0]
    record["size"] += 1
    immutable = {
        key: value
        for key, value in record.items()
        if key not in {"record_id", "bytes_integrity"}
    }
    record["record_id"] = hashlib.sha256(
        canonical_json(immutable).encode("utf-8")
    ).hexdigest()
    store.save_artifact(
        job["job_id"],
        REGISTRY_ARTIFACT,
        canonical_json(registry).encode("utf-8"),
    )

    with pytest.raises(RecipientReturnError) as corrupted:
        get_recipient_return_status(store, job["job_id"])
    assert corrupted.value.code == "RECIPIENT_RETURN_INTEGRITY_FAILED"


def test_authenticated_http_roundtrip_returns_exact_original_bytes(tmp_path):
    store, job, _snapshot = _case(tmp_path)
    app = FastAPI()
    app.include_router(router)
    bind_runtime(job_store=store)
    try:
        with TestClient(app) as client:
            unauthorized = client.get(f"/jobs/{job['job_id']}/recipient-return")
            assert unauthorized.status_code == 403

            headers = {"X-Job-Token": job["access_token"]}
            created = client.post(
                f"/jobs/{job['job_id']}/recipient-return",
                headers=headers,
                files={
                    "file": (
                        "SYNTHETIC_TEST_retorno.txt",
                        b"RETORNO SINTETICO DE TESTE - SEM VALIDADE EXTERNA",
                        "text/plain",
                    )
                },
                data={
                    "recipient_id": "banco-do-brasil",
                    "protocol": "PROTOCOLO-TESTE-HTTP-001",
                    "received_at": "2026-09-12T16:00:00-03:00",
                    "source": "SYNTHETIC_TEST: fixture HTTP local",
                    "operator_declaration": DECLARATION,
                    "synthetic_test_only": "true",
                    "authorized_for_report": "true",
                    # A field named valid is ignored by the declared route and
                    # cannot launder this evidence into an acceptance.
                    "valid": "true",
                },
            )
            assert created.status_code == 200
            record = created.json()["record"]
            assert record["institution_acceptance"] is False
            assert record["synthetic_test_only"] is True
            assert record["authorized_for_report"] is True

            status = client.get(
                f"/jobs/{job['job_id']}/recipient-return", headers=headers
            )
            assert status.status_code == 200
            assert status.json()["latest"]["bytes_integrity"] == "verified"

            exact = client.get(
                f"/jobs/{job['job_id']}/recipient-return/{record['record_id']}/file",
                headers=headers,
            )
            assert exact.status_code == 200
            assert exact.content == b"RETORNO SINTETICO DE TESTE - SEM VALIDADE EXTERNA"
    finally:
        RuntimeBindings.job_store = None


def test_unicode_filename_download_uses_safe_headers_and_exact_bytes(tmp_path):
    store, job, _snapshot = _case(tmp_path)
    app = FastAPI()
    app.include_router(router)
    bind_runtime(job_store=store)
    try:
        with TestClient(app) as client:
            headers = {"X-Job-Token": job["access_token"]}
            created = client.post(
                f"/jobs/{job['job_id']}/recipient-return",
                headers=headers,
                files={"file": ("retorno-📄-ç.txt", b"UNICODE TEST", "text/plain")},
                data={
                    "recipient_id": "banco-do-brasil",
                    "protocol": "PROTOCOLO-TESTE-UNICODE",
                    "received_at": "2026-09-12T16:00:00-03:00",
                    "source": "SYNTHETIC_TEST: unicode filename",
                    "operator_declaration": DECLARATION,
                },
            )
            assert created.status_code == 200
            record_id = created.json()["record"]["record_id"]
            downloaded = client.get(
                f"/jobs/{job['job_id']}/recipient-return/{record_id}/file",
                headers=headers,
            )
            assert downloaded.status_code == 200
            assert downloaded.content == b"UNICODE TEST"
            disposition = downloaded.headers["content-disposition"]
            assert "filename=\"retorno-c.txt\"" in disposition
            assert "filename*=UTF-8''retorno-%F0%9F%93%84-%C3%A7.txt" in disposition
            assert downloaded.headers["x-content-type-options"] == "nosniff"
            assert downloaded.headers["cache-control"] == "no-store"
    finally:
        RuntimeBindings.job_store = None
