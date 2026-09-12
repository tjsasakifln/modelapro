"""Persisted recipient-return records remain evidence, never fabricated acceptance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import RuntimeBindings, bind_runtime
from backend.recipient_routes import router
from modules.job_store import JobStore
from modules.qualification_profile import resolve_profile
from modules.report_export.recipient import (
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
    }
    fields.update(overrides)
    return store_recipient_return(store, job_id, **fields)


def test_persists_original_bytes_hash_profile_and_unverified_status(tmp_path):
    store, job, original_snapshot = _case(tmp_path)

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
    assert record["recipient_id"] == "banco-do-brasil"
    assert record["profile_id"] == "bb-meci-avaliacao-imovel-pf"
    assert record["protocol"] == "PROTOCOLO-TESTE-001"
    assert record["synthetic_test_only"] is True
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


def test_rejects_recipient_mismatch_and_missing_operator_declaration(tmp_path):
    store, job, _snapshot = _case(tmp_path)

    with pytest.raises(RecipientReturnError, match="recipient does not match") as mismatch:
        _store_return(store, job["job_id"], recipient_id="caixa-economica-federal")
    assert mismatch.value.code == "RECIPIENT_PROFILE_MISMATCH"

    with pytest.raises(RecipientReturnError, match="operator declaration") as declaration:
        _store_return(store, job["job_id"], operator_declaration="valid=true")
    assert declaration.value.code == "RECIPIENT_DECLARATION_REQUIRED"
    assert get_recipient_return_status(store, job["job_id"])["records"] == []


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
                    # A field named valid is ignored by the declared route and
                    # cannot launder this evidence into an acceptance.
                    "valid": "true",
                },
            )
            assert created.status_code == 200
            record = created.json()["record"]
            assert record["institution_acceptance"] is False

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
