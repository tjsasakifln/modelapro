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

# The certificate fingerprints are pinned identities of the public AC Raiz
# certificates linked by ITI's DOC-ICP-15.03 v9.1. Operator-provided roots may
# be used by pyHanko to build other trusted chains, but cannot extend this set.
ICP_BRASIL_TRUST_ANCHORS = {
    "caa53fc6091c6951887c976e378f6ef89aa6377c55d97b6475422b71ed7e9b17": {
        "name": "Autoridade Certificadora Raiz Brasileira v5",
        "source": "http://acraiz.icpbrasil.gov.br/ICP-Brasilv5.crt",
    },
    "d8478e37ce19c690cf657381e68fe600e4e1a042536830f06847e03e554c4b01": {
        "name": "Autoridade Certificadora Raiz Brasileira v12",
        "source": "http://acraiz.icpbrasil.gov.br/ICP-Brasilv12.crt",
    },
}

# Current PAdES policy identifiers recorded in DOC-ICP-15.03 v9.1. Merely
# carrying an ICP-looking DN or arbitrary OID is insufficient.
ICP_BRASIL_PADES_POLICY_OIDS = {
    "2.16.76.1.7.1.11.1.2",  # AD-RB 1.2
    "2.16.76.1.7.1.11.1.3",  # AD-RB 1.3
    "2.16.76.1.7.1.12.1.2",  # AD-RT 1.2
    "2.16.76.1.7.1.12.1.3",  # AD-RT 1.3
    "2.16.76.1.7.1.13.1.3",  # AD-RC 1.3
    "2.16.76.1.7.1.13.1.4",  # AD-RC 1.4
    "2.16.76.1.7.1.14.1.3",  # AD-RA 1.3
    "2.16.76.1.7.1.14.1.4",  # AD-RA 1.4
}
# SHA-256 digests of the machine-readable policy DER files recorded in the
# signed LPA_PAdES.der published by ITI and checked again against each policy
# file on 2026-09-12. The registry is intentionally closed: a familiar OID
# alone does not authenticate the referenced policy document.
ICP_BRASIL_PADES_POLICY_REGISTRY = {
    "2.16.76.1.7.1.11.1.2": "84ed4620c6531e4a4853adecc9e2496926c823418dd3141963ed9c4f9704a03d",
    "2.16.76.1.7.1.11.1.3": "23da544aef71f7a75dc85fa6e17a83875741e4baef41ec178258a5c86ace54dd",
    "2.16.76.1.7.1.12.1.2": "da6e12c17e9be0343abbdb494723effcb53fe95f5f0b9bbee1b35bcef3a01eef",
    "2.16.76.1.7.1.12.1.3": "92a972e7c292bb884e98e650773d9e9876994effb43eb36199b06bf2864a677c",
    "2.16.76.1.7.1.13.1.3": "8fbcd072bb60e9776a520a53218a31fb1b0535b12ea3f6599abeef44d2cb8ba7",
    "2.16.76.1.7.1.13.1.4": "defe0ce4a45be8d7bf0a62bfe7baba5329b7665e5585568de00b9f3e56c0ce83",
    "2.16.76.1.7.1.14.1.3": "6102b07606a2704aa5ae4d04e6583725c840ba53c56f095699a3fe24f1f2834d",
    "2.16.76.1.7.1.14.1.4": "b77680a623ba7b9757c38404d4759d966791338665ff5cf152c1c0917f97c548",
}
ICP_BRASIL_PADES_LPA_SOURCE = "http://politicas.icpbrasil.gov.br/LPA_PAdES.der"
ICP_BRASIL_PADES_LPA_SHA256 = (
    "4ef7a4e725deb1f785ddc822a999def912592126930eeab88c0cf45db1cf8d51"
)
ICP_BRASIL_PADES_LPA_SIGNATURE_SOURCE = (
    "http://politicas.icpbrasil.gov.br/LPA_PAdES.p7s"
)
ICP_BRASIL_PADES_LPA_SIGNATURE_SHA256 = (
    "615fee5bc30fafa10e2f548d5d3feba2e54e43ef55590163972457472834e513"
)
ICP_BRASIL_PADES_LPA_NEXT_UPDATE = "2026-10-03T00:00:00Z"
ICP_BRASIL_POLICY_SOURCE = (
    "https://www.gov.br/iti/pt-br/assuntos/legislacao/documentos-principais/"
    "v9.1_IN2021_03_DOCICP15.03_compilada.pdf"
)
ICP_BRASIL_POLICY_SOURCE_SHA256 = (
    "2cc3859adb5af9531ff8d4498151560a689b0742820cc0db766278b1d588a0d9"
)
ICP_BRASIL_POLICY_VERIFIED_ON = "2026-09-12"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_sha(snapshot: Mapping[str, Any]) -> str:
    return signable_snapshot_sha256(snapshot)


def _cert_sha256(cert: Any) -> Optional[str]:
    try:
        return hashlib.sha256(cert.dump()).hexdigest()
    except Exception:
        return None


def _signature_policy_details(embedded: Any) -> Optional[Dict[str, str]]:
    """Read the one explicit signed policy reference by its ASN.1 fields."""
    try:
        attributes = embedded.signer_info["signed_attrs"]
    except Exception:
        return None
    matches = []
    for attribute in attributes or []:
        try:
            type_oid = attribute["type"].dotted
            if type_oid == "1.2.840.113549.1.9.16.2.15":
                matches.append(attribute)
        except Exception:
            return None
    if len(matches) != 1:
        return None
    try:
        values = matches[0]["values"]
        if len(values) != 1:
            return None
        identifier = values[0]
        if getattr(identifier, "name", None) != "signature_policy_id":
            return None
        policy = identifier.chosen
        oid = policy["sig_policy_id"].dotted
        digest_info = policy["sig_policy_hash"]
        algorithm = digest_info["digest_algorithm"]["algorithm"].native
        digest = bytes(digest_info["digest"].native).hex()
    except Exception:
        return None
    if not oid or not algorithm or not digest:
        return None
    return {"oid": oid, "hash_algorithm": str(algorithm), "hash_value": digest}


def _signature_policy_oid(embedded: Any) -> Optional[str]:
    details = _signature_policy_details(embedded)
    return details.get("oid") if details else None


def _signature_policy_verified(
    details: Optional[Mapping[str, Any]], *, registry_current: bool
) -> bool:
    if not details or not registry_current:
        return False
    oid = str(details.get("oid") or "")
    return bool(
        oid in ICP_BRASIL_PADES_POLICY_OIDS
        and details.get("hash_algorithm") == "sha256"
        and details.get("hash_value") == ICP_BRASIL_PADES_POLICY_REGISTRY.get(oid)
    )


def _trust_anchor_sha256(status: Any) -> Optional[str]:
    path = getattr(status, "validation_path", None)
    if path is None:
        return None
    try:
        return _cert_sha256(path[0])
    except Exception:
        try:
            return _cert_sha256(path.first)
        except Exception:
            return None


def _strict_revocation_policy(validation_context: Any) -> bool:
    """Require CRL or OCSP for both the signer and intermediate CAs."""
    try:
        checking = validation_context.revinfo_policy.revocation_checking_policy
        return (
            getattr(checking.ee_certificate_rule, "value", None) == "eithercheck"
            and getattr(checking.intermediate_ca_cert_rule, "value", None)
            == "eithercheck"
        )
    except Exception:
        return False


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
        "synthetic_test_only": bool((report_context or {}).get("synthetic_test_only")),
    }


def verify_pdf_signature(
    pdf_bytes: bytes,
    *,
    validation_context: Any = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify embedded PDF signatures through pyHanko when available.

    The caller supplies an offline validation context with public trust roots
    and CRL/OCSP evidence. Profile requirements decide whether trust,
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
    icp_required = str(requirements.get("trust_framework") or "").strip().lower() in {
        "icp-brasil", "icp_brasil"
    }
    if icp_required:
        # DOC-ICP-15.03 requires LCR or OCSP for end certificates and CAs.
        require_trust = True
        require_revocation = True
    policy_registry_current = datetime.now(timezone.utc) <= datetime.fromisoformat(
        ICP_BRASIL_PADES_LPA_NEXT_UPDATE.replace("Z", "+00:00")
    )
    findings = []
    details = []
    revocation_policy_verified = (
        _strict_revocation_policy(validation_context)
        if require_revocation else None
    )
    if require_revocation and not revocation_policy_verified:
        findings.append({"code": "PDF_REVOCATION_POLICY_NOT_STRICT"})
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
            signer_cert_sha256 = _cert_sha256(getattr(status, "signing_cert", None))
            trust_anchor_sha256 = _trust_anchor_sha256(status)
            signature_policy = _signature_policy_details(embedded)
            policy_oid = signature_policy.get("oid") if signature_policy else None
            policy_hash_algorithm = (
                signature_policy.get("hash_algorithm") if signature_policy else None
            )
            policy_hash_value = (
                signature_policy.get("hash_value") if signature_policy else None
            )
            official_anchor = trust_anchor_sha256 in ICP_BRASIL_TRUST_ANCHORS
            oid_allowlisted = policy_oid in ICP_BRASIL_PADES_POLICY_OIDS
            approved_policy = _signature_policy_verified(
                signature_policy, registry_current=policy_registry_current
            )
            summary = {
                "index": index,
                "field_name": getattr(embedded, "field_name", None),
                "intact": intact,
                "cryptographically_valid": cryptographically_valid,
                "trusted": trusted,
                "revoked": revoked,
                "timestamp_valid": timestamp_valid,
                "signer_certificate_sha256": signer_cert_sha256,
                "trust_anchor_sha256": trust_anchor_sha256,
                "signature_policy_oid": policy_oid,
                "signature_policy_hash_algorithm": policy_hash_algorithm,
                "signature_policy_hash_value": policy_hash_value,
                "signature_policy_oid_allowlisted": oid_allowlisted,
                "icp_brasil_anchor_verified": official_anchor,
                "icp_brasil_policy_verified": approved_policy,
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
            if require_timestamp and not timestamp_valid:
                findings.append(
                    {"code": "PDF_TRUSTED_TIMESTAMP_MISSING", "signature_index": index}
                )
            if icp_required and not official_anchor:
                findings.append({
                    "code": "ICP_BRASIL_OFFICIAL_TRUST_ANCHOR_NOT_VERIFIED",
                    "signature_index": index,
                })
            if icp_required and not approved_policy:
                findings.append({
                    "code": "ICP_BRASIL_PADES_POLICY_NOT_VERIFIED",
                    "signature_index": index,
                })
            if icp_required and not policy_registry_current:
                findings.append({
                    "code": "ICP_BRASIL_PADES_POLICY_REGISTRY_STALE",
                    "signature_index": index,
                })
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
    framework_verified = bool(
        icp_required and details
        and all(item.get("icp_brasil_anchor_verified") for item in details)
        and all(item.get("icp_brasil_policy_verified") for item in details)
        and result_status == "valid"
    )
    return {
        "status": result_status,
        "signed_pdf_sha256": digest,
        "backend": "pyHanko",
        "signature_count": len(signatures),
        "policy": {
            "require_trust": require_trust,
            "require_revocation": require_revocation,
            "require_timestamp": require_timestamp,
            "trust_framework": "ICP-Brasil" if icp_required else None,
            "trust_framework_source": ICP_BRASIL_POLICY_SOURCE if icp_required else None,
            "trust_framework_source_sha256": (
                ICP_BRASIL_POLICY_SOURCE_SHA256 if icp_required else None
            ),
            "trust_framework_verified_on": (
                ICP_BRASIL_POLICY_VERIFIED_ON if icp_required else None
            ),
            "policy_registry_source": (
                ICP_BRASIL_PADES_LPA_SOURCE if icp_required else None
            ),
            "policy_registry_source_sha256": (
                ICP_BRASIL_PADES_LPA_SHA256 if icp_required else None
            ),
            "policy_registry_signature_source": (
                ICP_BRASIL_PADES_LPA_SIGNATURE_SOURCE if icp_required else None
            ),
            "policy_registry_signature_sha256": (
                ICP_BRASIL_PADES_LPA_SIGNATURE_SHA256 if icp_required else None
            ),
            "policy_registry_next_update": (
                ICP_BRASIL_PADES_LPA_NEXT_UPDATE if icp_required else None
            ),
            "policy_registry_current": (
                policy_registry_current if icp_required else None
            ),
            "trust_anchor_allowlist_verified": framework_verified,
            "signature_policy_verified": framework_verified,
            "revocation_policy_verified": revocation_policy_verified,
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
    if request.get("synthetic_test_only") and (
        (local_result.get("policy") or {}).get("trust_framework") == "ICP-Brasil"
    ):
        status = "indeterminate"
        local_result["status"] = "indeterminate"
        local_result["policy"]["trust_anchor_allowlist_verified"] = False
        local_result["policy"]["signature_policy_verified"] = False
        findings.append({"code": "SYNTHETIC_TEST_SIGNATURE_IS_NOT_ICP_BRASIL"})
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
        "synthetic_test_only": bool(request.get("synthetic_test_only")),
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
    provenance = snapshot.get("provenance") if isinstance(snapshot.get("provenance"), Mapping) else {}
    qctx = provenance.get("qualification_context") if isinstance(provenance.get("qualification_context"), Mapping) else {}
    profile = qctx.get("resolved_profile") if isinstance(qctx.get("resolved_profile"), Mapping) else {}
    if profile.get("id") == "bb-meci-avaliacao-imovel-pf":
        policy = local.get("policy") if isinstance(local, Mapping) and isinstance(local.get("policy"), Mapping) else {}
        if (
            signature_record.get("synthetic_test_only") is True
            or policy.get("trust_framework") != "ICP-Brasil"
            or policy.get("trust_anchor_allowlist_verified") is not True
            or policy.get("signature_policy_verified") is not True
        ):
            findings.append({"code": "ICP_BRASIL_SIGNATURE_POLICY_NOT_VERIFIED"})
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
