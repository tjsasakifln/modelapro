"""Evidence adapter for PDF/A validation performed by a concrete validator."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Dict, Optional


def validate_pdfa(
    pdf_bytes: bytes, validator_result: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Bind an external PDF/A validator result to exact PDF bytes.

    A PDF extension, metadata claim, or successful render is never treated as
    PDF/A validation.  Callers may pass a veraPDF (or equivalent) result with
    the exact SHA, tool/version and conformance.  No validator means
    ``unsupported`` rather than PASS.
    """
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    result = dict(validator_result or {})
    if not result:
        return {
            "status": "unsupported",
            "pdf_sha256": digest,
            "conformance": None,
            "validator": None,
            "findings": [
                {
                    "code": "PDFA_VALIDATOR_NOT_RUN",
                    "message": "Nenhum validador PDF/A concreto foi executado para estes bytes.",
                }
            ],
        }
    observed_sha = str(result.get("pdf_sha256") or "")
    validator = str(result.get("validator") or result.get("tool") or "").strip()
    version = str(result.get("version") or result.get("tool_version") or "").strip()
    conformance = str(result.get("conformance") or "").strip()
    passed = str(result.get("status") or "").lower() in {"passed", "valid"}
    findings = []
    if observed_sha != digest:
        findings.append(
            {
                "code": "PDFA_RESULT_HASH_MISMATCH",
                "expected": digest,
                "observed": observed_sha,
            }
        )
    if not validator or not version:
        findings.append({"code": "PDFA_VALIDATOR_IDENTITY_MISSING"})
    if not conformance:
        findings.append({"code": "PDFA_CONFORMANCE_MISSING"})
    if not passed:
        findings.append(
            {"code": "PDFA_VALIDATION_FAILED", "details": result.get("findings") or []}
        )
    return {
        "status": "valid" if not findings else "invalid",
        "pdf_sha256": digest,
        "conformance": conformance or None,
        "validator": {"name": validator, "version": version}
        if validator or version
        else None,
        "findings": findings,
    }
