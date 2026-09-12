"""Authenticated local routes for exact institutional-return evidence."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response

from modules.report_export.recipient import (
    MAX_RETURN_BYTES,
    RecipientReturnError,
    get_recipient_return_status,
    recipient_return_bytes,
    store_recipient_return,
)

router = APIRouter(tags=["recipient-return"])


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


def _error(exc: RecipientReturnError) -> JSONResponse:
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
    try:
        return get_recipient_return_status(store, job_id)
    except RecipientReturnError as exc:
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
    x_job_token: str | None = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    content = await file.read(MAX_RETURN_BYTES + 1)
    try:
        return await asyncio.to_thread(
            store_recipient_return,
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
        )
    except RecipientReturnError as exc:
        return _error(exc)


@router.get("/jobs/{job_id}/recipient-return/{record_id}/file")
async def recipient_return_file(
    job_id: str,
    record_id: str,
    x_job_token: str | None = Header(None),
):
    store = _authorized_store(job_id, x_job_token)
    try:
        content, record = await asyncio.to_thread(
            recipient_return_bytes, store, job_id, record_id
        )
        filename = (
            str(record.get("filename") or "recipient-return.bin")
            .replace('"', "")
            .replace("\r", "")
            .replace("\n", "")
        )
        return Response(
            content,
            media_type=str(record.get("media_type") or "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except RecipientReturnError as exc:
        return _error(exc)
