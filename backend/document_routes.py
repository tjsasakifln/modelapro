"""HTTP consumer for C03's persisted document lifecycle.

The application includes this router behind its existing local Origin/token/
CSRF middleware.  Job access tokens are additionally checked here before any
document bytes or professional-review data are read or changed.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from modules.report_export.workflow import (
    DocumentWorkflowError,
    create_signature_request,
    generate_documents,
    get_document_status,
    import_signed_report,
    record_review,
    store_document_attachment,
)

router = APIRouter(tags=["documents"])


def _store():
    # Deferred import avoids a cycle while backend.api is constructing `app`.
    from backend.api import get_job_store

    store = get_job_store()
    if store is None:
        raise HTTPException(status_code=503, detail="JobStore unavailable")
    return store


def _authorized_store(job_id: str, token: Optional[str]):
    store = _store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    verify = getattr(store, "verify_access", None)
    if not token or not callable(verify) or not verify(job_id, token):
        raise HTTPException(status_code=403, detail="invalid job access token")
    return store


def _error(exc: DocumentWorkflowError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "schema_version": "MP-DOCUMENTS/1",
            "error": str(exc),
            "issues": [{"code": exc.code, "message": str(exc), "origin": "c03.documents"}],
        },
    )


def _configured_signature_validation_context():
    """Load operator-configured trust anchors; never accept trust from HTTP."""
    configured = os.environ.get("MODELA_REPORT_SIGNATURE_TRUST_ROOTS", "").strip()
    if not configured:
        return None
    try:
        from asn1crypto import pem, x509
        from pyhanko_certvalidator import ValidationContext

        roots = []
        for raw_path in configured.split(os.pathsep):
            path = Path(raw_path).expanduser()
            data = path.read_bytes()
            if not data or len(data) > 1024 * 1024:
                raise ValueError(f"invalid trust-root size: {path}")
            if pem.detect(data):
                label, _headers, data = pem.unarmor(data)
                if label != "CERTIFICATE":
                    raise ValueError(f"trust root is not a certificate: {path}")
            roots.append(x509.Certificate.load(data))
        if not roots:
            raise ValueError("no trust roots configured")
        return ValidationContext(trust_roots=roots, allow_fetching=False)
    except Exception as exc:
        raise DocumentWorkflowError(
            "SIGNATURE_TRUST_CONFIGURATION_INVALID",
            "configured report-signature trust roots could not be loaded",
            status_code=503,
        ) from exc


@router.get("/jobs/{job_id}/documents")
def document_status(job_id: str, x_job_token: Optional[str] = Header(None)):
    store = _authorized_store(job_id, x_job_token)
    try:
        return get_document_status(store, job_id)
    except DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents")
def document_generate(
    job_id: str,
    payload: Optional[Dict[str, Any]] = None,
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    try:
        return generate_documents(
            store,
            job_id,
            report_fields=(payload or {}).get("report_context") or payload or {},
        )
    except DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/review")
def document_review(
    job_id: str,
    payload: Dict[str, Any],
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    try:
        return record_review(
            store,
            job_id,
            professional_id=str(payload.get("professional_id") or ""),
            professional_name=payload.get("professional_name"),
            motive=str(payload.get("motive") or ""),
            version=str(payload.get("version") or ""),
            synthetic_test_only=bool(payload.get("synthetic_test_only", False)),
        )
    except DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/signature-request")
def document_signature_request(
    job_id: str,
    payload: Dict[str, Any],
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    try:
        return create_signature_request(
            store, job_id, revision_id=str(payload.get("revision_id") or "")
        )
    except (DocumentWorkflowError, ValueError) as exc:
        if isinstance(exc, DocumentWorkflowError):
            return _error(exc)
        return _error(DocumentWorkflowError("SIGNATURE_REQUEST_INVALID", str(exc), status_code=400))


@router.post("/jobs/{job_id}/documents/attachments")
async def document_attachment_upload(
    job_id: str,
    file: UploadFile = File(...),
    source: str = Form(...),
    authorized_for_report: bool = Form(...),
    category: str = Form("document"),
    description: str = Form(""),
    synthetic_test_only: bool = Form(False),
    requirement_ids: str = Form("[]"),
    x_job_token: Optional[str] = Header(None),
):
    """Store exact documentary bytes; mere JSON references are not evidence."""
    store = _authorized_store(job_id, x_job_token)
    try:
        return await asyncio.to_thread(
            store_document_attachment,
            store,
            job_id,
            filename=file.filename or "document.bin",
            media_type=file.content_type or "application/octet-stream",
            content=await file.read(20 * 1024 * 1024 + 1),
            source=source,
            authorized_for_report=authorized_for_report,
            category=category,
            description=description,
            synthetic_test_only=synthetic_test_only,
            requirement_ids=json.loads(requirement_ids),
        )
    except json.JSONDecodeError:
        return _error(DocumentWorkflowError("ATTACHMENT_REQUIREMENTS_INVALID", "requirement_ids must be JSON", status_code=400))
    except DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/signature")
async def document_signature_import(
    job_id: str,
    file: UploadFile = File(...),
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    try:
        return await asyncio.to_thread(
            import_signed_report,
            store,
            job_id,
            signed_pdf=await file.read(),
            validation_context=_configured_signature_validation_context(),
        )
    except (DocumentWorkflowError, ValueError) as exc:
        if isinstance(exc, DocumentWorkflowError):
            return _error(exc)
        return _error(DocumentWorkflowError("SIGNATURE_IMPORT_INVALID", str(exc), status_code=400))
