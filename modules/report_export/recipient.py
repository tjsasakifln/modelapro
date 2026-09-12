"""Persist exact recipient-return evidence without declaring institutional acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ..provenance import canonical_json
from ..qualification_profile import resolve_profile

SCHEMA_VERSION = "MP-RECIPIENT-RETURN/1"
REGISTRY_ARTIFACT = "recipient_returns.json"
OPERATOR_DECLARATION = (
    "RECEIVED_DOCUMENT_RECORDED_WITHOUT_AUTHENTICITY_OR_ACCEPTANCE_VERIFICATION"
)
UNVERIFIED_DETAIL = (
    "Comprovante recebido e declarado pelo operador; autenticidade e "
    "aceite institucional não foram verificados."
)
MAX_RETURN_BYTES = 20 * 1024 * 1024


class RecipientReturnError(RuntimeError):
    """Stable, fail-closed recipient-return error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_registry(store: Any, job_id: str) -> list[dict[str, Any]]:
    raw = store.get_artifact(job_id, REGISTRY_ARTIFACT)
    if raw is None:
        return []
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecipientReturnError(
            "RECIPIENT_RETURN_REGISTRY_INVALID",
            "recipient-return registry is not valid JSON",
            status_code=409,
        ) from exc
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, list) or not all(isinstance(item, Mapping) for item in records):
        raise RecipientReturnError(
            "RECIPIENT_RETURN_REGISTRY_INVALID",
            "recipient-return registry has an invalid record list",
            status_code=409,
        )
    return [dict(item) for item in records]


def _profile_for_job(job: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    request_spec = job.get("request_spec") or {}
    if not isinstance(request_spec, Mapping):
        raise RecipientReturnError(
            "RECIPIENT_PROFILE_MISSING", "job RequestSpec is unavailable", status_code=409
        )
    profile = resolve_profile(request_spec.get("qualification_profile") or {})
    if not profile.get("resolved"):
        raise RecipientReturnError(
            "RECIPIENT_PROFILE_MISSING", "job qualification profile is unresolved", status_code=409
        )
    # Only an institution-specific catalogue profile establishes this binding.
    # A free root-level recipient on a neutral profile must not invent one.
    recipient_id = profile.get("recipient_id")
    if not isinstance(recipient_id, str) or not recipient_id.strip():
        raise RecipientReturnError(
            "RECIPIENT_NOT_CONFIGURED",
            "job profile does not establish an institutional recipient",
            status_code=409,
        )
    return dict(profile), recipient_id.strip()


def _normalized_timestamp(value: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RecipientReturnError(
            "RECIPIENT_RECEIVED_AT_INVALID", "received_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise RecipientReturnError(
            "RECIPIENT_RECEIVED_AT_INVALID", "received_at must include a timezone"
        )
    return parsed.isoformat()


def _safe_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(filename or "return.bin")).strip(".-")
    safe = re.sub(r"\.{2,}", ".", safe)
    return safe[:80] or "return.bin"


def _acceptance_envelope(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "recorded": True,
        "record": dict(record),
        "detail": UNVERIFIED_DETAIL,
    }


def _case_state_at_import(store: Any, job_id: str) -> dict[str, Any]:
    """Capture observed local state without claiming which bytes were submitted."""
    snapshot = store.get_snapshot(job_id) or {}
    provenance = snapshot.get("provenance") if isinstance(snapshot, Mapping) else {}
    provenance = provenance if isinstance(provenance, Mapping) else {}
    qualification = provenance.get("qualification_context")
    qualification = qualification if isinstance(qualification, Mapping) else {}

    def fingerprint(name: str) -> str | None:
        value = qualification.get(name)
        return value if isinstance(value, str) and value else None

    artifact_sha256: dict[str, str | None] = {}
    for name in ("report.pdf", "signed_report.pdf", "submission.zip"):
        raw = store.get_artifact(job_id, name)
        artifact_sha256[name] = _sha(raw) if raw is not None else None
    return {
        "result_fingerprint": fingerprint("result_fingerprint"),
        "report_content_fingerprint": fingerprint("report_content_fingerprint"),
        "artifact_sha256": artifact_sha256,
        "association_to_sent_version_verified": False,
    }


def _record_digest(record: Mapping[str, Any]) -> str:
    immutable = {
        str(key): value
        for key, value in record.items()
        if key not in {"record_id", "bytes_integrity"}
    }
    return _sha(canonical_json(immutable).encode("utf-8"))


def _validated_record_bytes(
    store: Any, job_id: str, stored: Mapping[str, Any]
) -> tuple[dict[str, Any], bytes]:
    record = dict(stored)
    digest = record.get("proof_sha256")
    record_id = record.get("record_id")
    size = record.get("size")
    stored_name = record.get("stored_name")
    structurally_valid = all(
        (
            isinstance(digest, str) and len(digest) == 64,
            isinstance(record_id, str) and len(record_id) == 64,
            record_id == _record_digest(record),
            isinstance(size, int) and not isinstance(size, bool) and size > 0,
            isinstance(stored_name, str),
            isinstance(stored_name, str)
            and stored_name.startswith(f"recipient-return-{str(digest)[:20]}-"),
            isinstance(stored_name, str)
            and stored_name == stored_name.rsplit("/", 1)[-1]
            and "\\" not in stored_name
            and ".." not in stored_name,
        )
    )
    if not structurally_valid:
        raise RecipientReturnError(
            "RECIPIENT_RETURN_RECORD_INVALID",
            "recipient-return immutable record digest or structure is invalid",
            status_code=409,
        )
    raw = store.get_artifact(job_id, stored_name)
    if raw is None or len(raw) != size or _sha(raw) != digest:
        raise RecipientReturnError(
            "RECIPIENT_RETURN_INTEGRITY_FAILED",
            "recipient-return bytes are missing, have a different size, or differ from the hash",
            status_code=409,
        )
    record["bytes_integrity"] = "verified"
    return record, raw


def store_recipient_return(
    store: Any,
    job_id: str,
    *,
    filename: str,
    media_type: str,
    content: bytes,
    recipient_id: str,
    protocol: str,
    received_at: str,
    source: str,
    operator_declaration: str,
    synthetic_test_only: bool = False,
    authorized_for_report: bool = False,
) -> dict[str, Any]:
    """Persist an immutable sidecar record; never mutate calculation/report bytes."""
    with store._lock:
        job = store.get(job_id)
        if not isinstance(job, Mapping):
            raise RecipientReturnError("JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
        profile, expected_recipient = _profile_for_job(job)
        if str(recipient_id or "").strip() != expected_recipient:
            raise RecipientReturnError(
                "RECIPIENT_PROFILE_MISMATCH", "recipient does not match the job profile"
            )
        if operator_declaration != OPERATOR_DECLARATION:
            raise RecipientReturnError(
                "RECIPIENT_DECLARATION_REQUIRED",
                "explicit operator declaration of unverified receipt is required",
            )
        if type(synthetic_test_only) is not bool or type(authorized_for_report) is not bool:
            raise RecipientReturnError(
                "RECIPIENT_RETURN_FLAGS_INVALID",
                "synthetic_test_only and authorized_for_report must be booleans",
            )
        if not isinstance(content, bytes) or not content:
            raise RecipientReturnError("RECIPIENT_RETURN_EMPTY", "recipient-return file is empty")
        if len(content) > MAX_RETURN_BYTES:
            raise RecipientReturnError(
                "RECIPIENT_RETURN_TOO_LARGE",
                "recipient-return file exceeds 20 MiB",
                status_code=413,
            )
        protocol = str(protocol or "").strip()
        source = str(source or "").strip()
        if not protocol or not source:
            raise RecipientReturnError(
                "RECIPIENT_RETURN_METADATA_REQUIRED", "protocol and source are required"
            )
        normalized_received_at = _normalized_timestamp(received_at)
        digest = _sha(content)
        original_filename = str(filename or "recipient-return.bin")
        normalized_media_type = str(media_type or "application/octet-stream")
        effective_synthetic_test_only = (
            synthetic_test_only
            or (job.get("request_spec") or {}).get("synthetic_test_only") is True
        )
        idempotency_material = {
            "proof_sha256": digest,
            "recipient_id": expected_recipient,
            "profile_id": profile.get("id"),
            "protocol": protocol,
            "received_at": normalized_received_at,
            "source": source,
            "filename": original_filename,
            "media_type": normalized_media_type,
            "synthetic_test_only": effective_synthetic_test_only,
            "authorized_for_report": bool(authorized_for_report),
        }
        idempotency_key = _sha(canonical_json(idempotency_material).encode("utf-8"))
        records = [
            _validated_record_bytes(store, job_id, item)[0]
            for item in _read_registry(store, job_id)
        ]
        existing = next(
            (item for item in records if item.get("idempotency_key") == idempotency_key),
            None,
        )
        if existing is not None:
            return {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "record": existing,
                "institution_acceptance": _acceptance_envelope(existing),
            }

        safe_name = _safe_filename(filename)
        stored_name = f"recipient-return-{digest[:20]}-{safe_name}"
        case_state_at_import = _case_state_at_import(store, job_id)
        record = {
            "idempotency_key": idempotency_key,
            "event": "recipient_return",
            "decision": "received_declared_unverified",
            "status": "received_declared_unverified",
            "institution_acceptance": False,
            "authenticity_verified": False,
            "recipient_id": expected_recipient,
            "profile_id": profile.get("id"),
            "profile_version": profile.get("version"),
            "profile_source_set_sha256": profile.get("source_set_sha256"),
            "protocol": protocol,
            "received_at": normalized_received_at,
            "recorded_at": datetime.now(UTC).isoformat(),
            "source": source,
            "operator_declaration": OPERATOR_DECLARATION,
            "filename": original_filename,
            "stored_name": stored_name,
            "media_type": normalized_media_type,
            "proof_sha256": digest,
            "size": len(content),
            "synthetic_test_only": effective_synthetic_test_only,
            "authorized_for_report": bool(authorized_for_report),
            "case_state_at_import": case_state_at_import,
        }
        record["record_id"] = _record_digest(record)
        record["bytes_integrity"] = "verified"
        store.save_artifact(job_id, stored_name, content)
        registry = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "records": [*records, record],
        }
        store.save_artifact(
            job_id, REGISTRY_ARTIFACT, canonical_json(registry).encode("utf-8")
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "record": record,
            "institution_acceptance": _acceptance_envelope(record),
        }


def get_recipient_return_status(store: Any, job_id: str) -> dict[str, Any]:
    """Read persisted records and verify that their exact bytes still match."""
    with store._lock:
        job = store.get(job_id)
        if not isinstance(job, Mapping):
            raise RecipientReturnError("JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
        profile, recipient_id = _profile_for_job(job)
        records = []
        for stored in _read_registry(store, job_id):
            record, _raw = _validated_record_bytes(store, job_id, stored)
            records.append(record)
        latest = records[-1] if records else None
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "profile": {
                "id": profile.get("id"),
                "version": profile.get("version"),
                "source_set_sha256": profile.get("source_set_sha256"),
                "recipient_id": recipient_id,
            },
            "records": records,
            "latest": latest,
            "institution_acceptance": (
                _acceptance_envelope(latest)
                if latest
                else {
                    "recorded": False,
                    "record": None,
                    "detail": "Nenhum comprovante de retorno institucional foi registrado.",
                }
            ),
        }


def recipient_return_bytes(store: Any, job_id: str, record_id: str) -> tuple[bytes, dict[str, Any]]:
    """Return exact persisted bytes for one digest-bound record."""
    status = get_recipient_return_status(store, job_id)
    record = next(
        (item for item in status["records"] if item.get("record_id") == record_id), None
    )
    if record is None:
        raise RecipientReturnError(
            "RECIPIENT_RETURN_NOT_FOUND", "recipient-return record not found", status_code=404
        )
    raw = store.get_artifact(job_id, str(record.get("stored_name") or ""))
    if (
        raw is None
        or len(raw) != record.get("size")
        or _sha(raw) != record.get("proof_sha256")
    ):
        raise RecipientReturnError(
            "RECIPIENT_RETURN_INTEGRITY_FAILED",
            "recipient-return bytes are missing or differ from the recorded hash",
            status_code=409,
        )
    return raw, record
