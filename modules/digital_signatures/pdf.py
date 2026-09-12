"""Bind a frozen report revision to external signing and verify signed PDFs.

Private keys and passwords are deliberately outside this API.  pyHanko is an
optional verification backend proposed to the global dependency owner (C04).
When it is absent, the result is ``not_verified`` rather than a false PASS.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..report_presenter.qualification import (
    report_content_fingerprint,
    signable_snapshot_sha256,
)

SIGNATURE_STATUSES = {"valid", "invalid", "indeterminate", "not_verified"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_sha(snapshot: Mapping[str, Any]) -> str:
    return signable_snapshot_sha256(snapshot)


def prepare_signature_request(
    pdf_bytes: bytes,
    snapshot: Mapping[str, Any],
    *,
    revision_id: str,
    profile_id: str,
    report_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a non-secret request that identifies the exact unsigned bytes."""
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("signature request requires PDF bytes")
    if not str(revision_id).strip() or not str(profile_id).strip():
        raise ValueError("revision_id and profile_id are required")
    provenance = (
        snapshot.get("provenance")
        if isinstance(snapshot.get("provenance"), Mapping)
        else {}
    )
    qualification = (
        provenance.get("qualification_context")
        if isinstance(provenance.get("qualification_context"), Mapping)
        else {}
    )
    return {
        "schema_version": "MP-SIGN/1",
        "operation": "external_pdf_signature",
        "unsigned_pdf_sha256": _sha(pdf_bytes),
        "unsigned_pdf_size": len(pdf_bytes),
        "snapshot_sha256": _snapshot_sha(snapshot),
        "result_fingerprint": qualification.get("result_fingerprint"),
        "report_content_fingerprint": report_content_fingerprint(
            snapshot, report_context
        ),
        "revision_id": str(revision_id),
        "profile_id": str(profile_id),
        "private_key_handling": "external_to_modelapro",
        "technical_content_approval": False,
    }


def verify_pdf_signature(
    pdf_bytes: bytes,
    *,
    validation_context: Any = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify embedded PDF signatures through pyHanko when available.

    Network fetching remains disabled unless the caller supplies an already
    configured validation context.  Profile requirements decide whether trust,
    revocation evidence and a trusted timestamp are mandatory.
    """
    digest = _sha(pdf_bytes)
    if not pdf_bytes.startswith(b"%PDF"):
        return {
            "status": "invalid",
            "signed_pdf_sha256": digest,
            "findings": [{"code": "SIGNED_ARTIFACT_NOT_PDF"}],
        }
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
    except ImportError:
        return {
            "status": "not_verified",
            "signed_pdf_sha256": digest,
            "backend": None,
            "findings": [
                {
                    "code": "PYHANKO_NOT_INSTALLED",
                    "message": "Backend criptográfico indisponível; assinatura não foi declarada válida.",
                }
            ],
        }
    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes))
        signatures = list(reader.embedded_signatures)
    except Exception as exc:
        return {
            "status": "invalid",
            "signed_pdf_sha256": digest,
            "backend": "pyHanko",
            "findings": [{"code": "SIGNED_PDF_PARSE_FAILED", "message": str(exc)}],
        }
    if not signatures:
        return {
            "status": "not_verified",
            "signed_pdf_sha256": digest,
            "backend": "pyHanko",
            "signature_count": 0,
            "findings": [{"code": "NO_EMBEDDED_PDF_SIGNATURE"}],
        }

    requirements = dict(policy or {})
    require_trust = bool(requirements.get("require_trust", True))
    require_revocation = bool(requirements.get("require_revocation", False))
    require_timestamp = bool(requirements.get("require_timestamp", False))
    findings = []
    details = []
    for index, embedded in enumerate(signatures):
        try:
            kwargs = {}
            if validation_context is not None:
                kwargs["signer_validation_context"] = validation_context
            status = validate_pdf_signature(embedded, **kwargs)
            intact = bool(getattr(status, "intact", False))
            cryptographically_valid = bool(getattr(status, "valid", False))
            trusted = bool(getattr(status, "trusted", False))
            revoked = bool(getattr(status, "revoked", False))
            timestamp_validity = getattr(status, "timestamp_validity", None)
            timestamp_valid = bool(
                timestamp_validity
                and getattr(timestamp_validity, "intact", False)
                and getattr(timestamp_validity, "valid", False)
                and getattr(timestamp_validity, "trusted", False)
            )
            summary = {
                "index": index,
                "field_name": getattr(embedded, "field_name", None),
                "intact": intact,
                "cryptographically_valid": cryptographically_valid,
                "trusted": trusted,
                "revoked": revoked,
                "timestamp_valid": timestamp_valid,
            }
            details.append(summary)
            if not intact:
                findings.append(
                    {"code": "PDF_SIGNATURE_CONTENT_CHANGED", "signature_index": index}
                )
            if not cryptographically_valid:
                findings.append(
                    {
                        "code": "PDF_SIGNATURE_CRYPTOGRAPHICALLY_INVALID",
                        "signature_index": index,
                    }
                )
            if revoked:
                findings.append(
                    {"code": "PDF_SIGNER_CERTIFICATE_REVOKED", "signature_index": index}
                )
            if require_trust and not trusted:
                findings.append(
                    {"code": "PDF_SIGNER_CHAIN_UNTRUSTED", "signature_index": index}
                )
            if (
                require_revocation
                and not revoked
                and not getattr(status, "revocation_details", None)
            ):
                findings.append(
                    {
                        "code": "PDF_REVOCATION_STATUS_UNAVAILABLE",
                        "signature_index": index,
                    }
                )
            if require_timestamp and not timestamp_valid:
                findings.append(
                    {"code": "PDF_TRUSTED_TIMESTAMP_MISSING", "signature_index": index}
                )
        except Exception as exc:
            findings.append(
                {
                    "code": "PDF_SIGNATURE_VALIDATION_ERROR",
                    "signature_index": index,
                    "message": str(exc),
                }
            )

    invalid_codes = {
        "PDF_SIGNATURE_CONTENT_CHANGED",
        "PDF_SIGNATURE_CRYPTOGRAPHICALLY_INVALID",
        "PDF_SIGNER_CERTIFICATE_REVOKED",
    }
    if any(item["code"] in invalid_codes for item in findings):
        result_status = "invalid"
    elif findings:
        result_status = "indeterminate"
    else:
        result_status = "valid"
    return {
        "status": result_status,
        "signed_pdf_sha256": digest,
        "backend": "pyHanko",
        "signature_count": len(signatures),
        "policy": {
            "require_trust": require_trust,
            "require_revocation": require_revocation,
            "require_timestamp": require_timestamp,
        },
        "signatures": details,
        "findings": findings,
    }


def record_external_signature(
    signed_pdf: bytes,
    request: Mapping[str, Any],
    *,
    unsigned_pdf: bytes,
    verification: Optional[Mapping[str, Any]] = None,
    validation_context: Any = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a received signed version without upgrading unverified claims."""
    if request.get("schema_version") != "MP-SIGN/1":
        raise ValueError("unsupported signature request schema")
    unsigned_digest = _sha(unsigned_pdf)
    if unsigned_digest != request.get("unsigned_pdf_sha256"):
        raise ValueError("unsigned PDF does not match the signature request")
    digest = _sha(signed_pdf)
    local_result = verify_pdf_signature(
        signed_pdf,
        validation_context=validation_context,
        policy=policy,
    )
    external_result = dict(verification or {})
    status = str(local_result.get("status") or "not_verified").lower()
    if status not in SIGNATURE_STATUSES:
        status = "not_verified"
    findings = list(local_result.get("findings") or [])
    incremental_base_verified = bool(signed_pdf.startswith(unsigned_pdf))
    if not incremental_base_verified:
        status = "invalid"
        findings.append(
            {"code": "SIGNED_PDF_NOT_DERIVED_FROM_REQUESTED_UNSIGNED_BYTES"}
        )
    if external_result:
        external_sha = external_result.get("signed_pdf_sha256")
        if external_sha and external_sha != digest:
            status = "invalid"
            findings.append({"code": "EXTERNAL_SIGNATURE_EVIDENCE_HASH_MISMATCH"})
        elif (
            str(external_result.get("status") or "").lower() == "valid"
            and status != "valid"
        ):
            # Imported evidence is retained for audit but cannot upgrade local
            # cryptographic verification by itself.
            if status == "not_verified":
                status = "indeterminate"
            findings.append(
                {"code": "EXTERNAL_SIGNATURE_EVIDENCE_REQUIRES_CONTROLLED_IMPORT"}
            )
    return {
        "schema_version": "MP-SIGN/1",
        "status": status,
        "unsigned_pdf_sha256": request.get("unsigned_pdf_sha256"),
        "signed_pdf_sha256": digest,
        "signed_pdf_size": len(signed_pdf),
        "snapshot_sha256": request.get("snapshot_sha256"),
        "result_fingerprint": request.get("result_fingerprint"),
        "report_content_fingerprint": request.get("report_content_fingerprint"),
        "revision_id": request.get("revision_id"),
        "profile_id": request.get("profile_id"),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "backend": local_result.get("backend"),
        "incremental_base_verified": incremental_base_verified,
        "local_verification": local_result,
        "external_evidence": external_result or None,
        "findings": findings,
        "technical_content_approval": False,
    }


def verify_signature_binding(
    signed_pdf: bytes,
    signature_record: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    revision_id: str,
    unsigned_pdf: bytes,
    report_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Detect a changed signed PDF, snapshot, result fingerprint or revision."""
    findings = []
    if _sha(signed_pdf) != signature_record.get("signed_pdf_sha256"):
        findings.append({"code": "SIGNED_PDF_HASH_MISMATCH"})
    if _sha(unsigned_pdf) != signature_record.get("unsigned_pdf_sha256"):
        findings.append({"code": "UNSIGNED_PDF_HASH_MISMATCH"})
    if not signed_pdf.startswith(unsigned_pdf):
        findings.append({"code": "SIGNED_PDF_BASE_MISMATCH"})
    if _snapshot_sha(snapshot) != signature_record.get("snapshot_sha256"):
        findings.append({"code": "SIGNED_SNAPSHOT_HASH_MISMATCH"})
    if str(revision_id) != str(signature_record.get("revision_id") or ""):
        findings.append({"code": "SIGNED_REVISION_MISMATCH"})
    provenance = (
        snapshot.get("provenance")
        if isinstance(snapshot.get("provenance"), Mapping)
        else {}
    )
    qctx = (
        provenance.get("qualification_context")
        if isinstance(provenance.get("qualification_context"), Mapping)
        else {}
    )
    if signature_record.get("result_fingerprint") != qctx.get("result_fingerprint"):
        findings.append({"code": "SIGNED_RESULT_FINGERPRINT_MISMATCH"})
    expected_report_fingerprint = report_content_fingerprint(snapshot, report_context)
    if (
        signature_record.get("report_content_fingerprint")
        != expected_report_fingerprint
    ):
        findings.append({"code": "SIGNED_REPORT_CONTENT_FINGERPRINT_MISMATCH"})
    if signature_record.get("incremental_base_verified") is not True:
        findings.append({"code": "SIGNED_PDF_BASE_NOT_VERIFIED"})
    local = signature_record.get("local_verification")
    if not isinstance(local, Mapping) or local.get("status") != "valid":
        findings.append({"code": "SIGNATURE_LOCAL_VERIFICATION_NOT_VALID"})
    if signature_record.get("backend") != "pyHanko":
        findings.append({"code": "SIGNATURE_BACKEND_NOT_PYHANKO"})
    if signature_record.get("status") != "valid":
        findings.append(
            {
                "code": "SIGNATURE_NOT_VALID",
                "status": signature_record.get("status") or "not_verified",
            }
        )
    return {
        "ok": not findings,
        "status": "valid" if not findings else "invalid",
        "findings": findings,
    }
