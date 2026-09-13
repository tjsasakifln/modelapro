"""HTTP consumer for C03's persisted document lifecycle.

The application includes this router behind its existing local Origin/token/
CSRF middleware.  Job access tokens are additionally checked here before any
document bytes or professional-review data are read or changed.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(tags=["documents"])


def _document_workflow():
    """Load the renderer only when a document endpoint actually needs it."""
    return importlib.import_module("modules.report_export.workflow")


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


def _error(exc: Any) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "schema_version": "MP-DOCUMENTS/1",
            "error": str(exc),
            "issues": [{"code": exc.code, "message": str(exc), "origin": "c03.documents"}],
        },
    )


def _configured_signature_validation_context():
    """Load offline operator trust and revocation evidence; never use HTTP."""
    trust_configured = os.environ.get("MODELA_REPORT_SIGNATURE_TRUST_ROOTS", "").strip()
    crls_configured = os.environ.get("MODELA_REPORT_SIGNATURE_CRLS", "").strip()
    ocsps_configured = os.environ.get("MODELA_REPORT_SIGNATURE_OCSPS", "").strip()
    if not (trust_configured or crls_configured or ocsps_configured):
        return None
    try:
        from asn1crypto import crl, ocsp, x509
        from pyhanko_certvalidator import ValidationContext

        roots = _load_operator_asn1(
            "MODELA_REPORT_SIGNATURE_TRUST_ROOTS",
            x509.Certificate,
            {"CERTIFICATE"},
            max_size=1024 * 1024,
        )
        if not roots:
            raise ValueError("no trust roots configured")
        crls = _load_operator_asn1(
            "MODELA_REPORT_SIGNATURE_CRLS",
            crl.CertificateList,
            {"X509 CRL", "CRL"},
            max_size=16 * 1024 * 1024,
        )
        ocsps = _load_operator_asn1(
            "MODELA_REPORT_SIGNATURE_OCSPS",
            ocsp.OCSPResponse,
            {"OCSP RESPONSE"},
            max_size=16 * 1024 * 1024,
        )
        return ValidationContext(
            trust_roots=roots,
            crls=crls,
            ocsps=ocsps,
            revocation_mode="require",
            allow_fetching=False,
        )
    except Exception as exc:
        raise _document_workflow().DocumentWorkflowError(
            "SIGNATURE_TRUST_CONFIGURATION_INVALID",
            "configured report-signature trust/revocation material could not be loaded",
            status_code=503,
        ) from exc


def _load_operator_asn1(
    environment_name: str,
    asn1_type,
    pem_labels: set[str],
    *,
    max_size: int,
) -> list:
    from asn1crypto import pem

    configured = os.environ.get(environment_name, "").strip()
    values = []
    for raw_path in configured.split(os.pathsep) if configured else ():
        path = Path(raw_path).expanduser()
        data = path.read_bytes()
        if not data or len(data) > max_size:
            raise ValueError(f"invalid {environment_name} file size: {path}")
        if pem.detect(data):
            label, _headers, data = pem.unarmor(data)
            if label not in pem_labels:
                raise ValueError(f"unexpected PEM label {label!r} in {path}")
        values.append(asn1_type.load(data))
    return values


@router.get("/jobs/{job_id}/documents")
def document_status(job_id: str, x_job_token: Optional[str] = Header(None)):
    store = _authorized_store(job_id, x_job_token)
    workflow = _document_workflow()
    try:
        return workflow.get_document_status(store, job_id)
    except workflow.DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents")
def document_generate(
    job_id: str,
    payload: Optional[Dict[str, Any]] = None,
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = _document_workflow()
    try:
        return workflow.generate_documents(
            store,
            job_id,
            report_fields=(payload or {}).get("report_context") or payload or {},
        )
    except workflow.DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/review")
def document_review(
    job_id: str,
    payload: Dict[str, Any],
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = _document_workflow()
    try:
        return workflow.record_review(
            store,
            job_id,
            professional_id=str(payload.get("professional_id") or ""),
            professional_name=payload.get("professional_name"),
            motive=str(payload.get("motive") or ""),
            version=str(payload.get("version") or ""),
            synthetic_test_only=bool(payload.get("synthetic_test_only", False)),
        )
    except workflow.DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/signature-request")
def document_signature_request(
    job_id: str,
    payload: Dict[str, Any],
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = _document_workflow()
    try:
        return workflow.create_signature_request(
            store, job_id, revision_id=str(payload.get("revision_id") or "")
        )
    except (workflow.DocumentWorkflowError, ValueError) as exc:
        if isinstance(exc, workflow.DocumentWorkflowError):
            return _error(exc)
        return _error(workflow.DocumentWorkflowError("SIGNATURE_REQUEST_INVALID", str(exc), status_code=400))


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
    workflow = await asyncio.to_thread(_document_workflow)
    try:
        return await asyncio.to_thread(
            workflow.store_document_attachment,
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
        return _error(workflow.DocumentWorkflowError("ATTACHMENT_REQUIREMENTS_INVALID", "requirement_ids must be JSON", status_code=400))
    except workflow.DocumentWorkflowError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/documents/signature")
async def document_signature_import(
    job_id: str,
    file: UploadFile = File(...),
    x_job_token: Optional[str] = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = await asyncio.to_thread(_document_workflow)
    try:
        validation_context = await asyncio.to_thread(
            _configured_signature_validation_context
        )
        return await asyncio.to_thread(
            workflow.import_signed_report,
            store,
            job_id,
            signed_pdf=await file.read(),
            validation_context=validation_context,
        )
    except (workflow.DocumentWorkflowError, ValueError) as exc:
        if isinstance(exc, workflow.DocumentWorkflowError):
            return _error(exc)
        return _error(workflow.DocumentWorkflowError("SIGNATURE_IMPORT_INVALID", str(exc), status_code=400))
