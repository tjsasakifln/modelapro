"""Authenticated local routes for exact institutional-return evidence."""

from __future__ import annotations

import asyncio
import importlib
import re
import unicodedata
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

router = APIRouter(tags=["recipient-return"])


def _recipient_workflow():
    """Load document export code only when this route is exercised."""
    return importlib.import_module("modules.report_export.recipient")


def _authorized_store(job_id: str, token: str | None):
    from backend.api import get_job_store

    store = get_job_store()
    if store is None:
        raise HTTPException(status_code=503, detail="JobStore unavailable")
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    verify = getattr(store, "verify_access", None)
    if not token or not callable(verify) or not verify(job_id, token):
        raise HTTPException(status_code=403, detail="invalid job access token")
    return store


def _error(exc) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "schema_version": "MP-RECIPIENT-RETURN/1",
            "error": str(exc),
            "issues": [{"code": exc.code, "message": str(exc), "origin": "c06.recipient"}],
        },
    )


@router.get("/jobs/{job_id}/recipient-return")
def recipient_return_status(job_id: str, x_job_token: str | None = Header(None)):
    store = _authorized_store(job_id, x_job_token)
    workflow = _recipient_workflow()
    try:
        return workflow.get_recipient_return_status(store, job_id)
    except workflow.RecipientReturnError as exc:
        return _error(exc)


@router.post("/jobs/{job_id}/recipient-return")
async def recipient_return_import(
    job_id: str,
    file: UploadFile = File(...),
    recipient_id: str = Form(...),
    protocol: str = Form(...),
    received_at: str = Form(...),
    source: str = Form(...),
    operator_declaration: str = Form(...),
    synthetic_test_only: bool = Form(False),
    authorized_for_report: bool = Form(False),
    x_job_token: str | None = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = await asyncio.to_thread(_recipient_workflow)
    content = await file.read(workflow.MAX_RETURN_BYTES + 1)
    try:
        return await asyncio.to_thread(
            workflow.store_recipient_return,
            store,
            job_id,
            filename=file.filename or "recipient-return.bin",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            recipient_id=recipient_id,
            protocol=protocol,
            received_at=received_at,
            source=source,
            operator_declaration=operator_declaration,
            synthetic_test_only=synthetic_test_only,
            authorized_for_report=authorized_for_report,
        )
    except workflow.RecipientReturnError as exc:
        return _error(exc)


@router.get("/jobs/{job_id}/recipient-return/{record_id}/file")
async def recipient_return_file(
    job_id: str,
    record_id: str,
    x_job_token: str | None = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    workflow = await asyncio.to_thread(_recipient_workflow)
    try:
        content, record = await asyncio.to_thread(
            workflow.recipient_return_bytes, store, job_id, record_id
        )
        original_filename = str(record.get("filename") or "recipient-return.bin")
        ascii_filename = unicodedata.normalize("NFKD", original_filename).encode(
            "ascii", "ignore"
        ).decode("ascii")
        ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_filename)
        ascii_filename = re.sub(r"-+", "-", ascii_filename).strip(".-")
        ascii_filename = ascii_filename[:80] or "recipient-return.bin"
        encoded_filename = quote(original_filename, safe="")
        return Response(
            content,
            media_type=str(record.get("media_type") or "application/octet-stream"),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_filename}"; '
                    f"filename*=UTF-8''{encoded_filename}"
                ),
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )
    except workflow.RecipientReturnError as exc:
        return _error(exc)
