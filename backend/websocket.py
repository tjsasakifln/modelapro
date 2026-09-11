import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from modules.job_store import JobStore
from modules.logging_manager import logger
from modules.websocket_notifier import WebSocketNotifier

router = APIRouter()
notifier = WebSocketNotifier()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    job_id: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
):
    """Optional local progress channel, scoped to job_id + access token.

    Snapshot and artifacts are not sent here. C10 GET endpoints are the
    source of truth. Missing credentials are rejected; this is not a
    multi-tenant cloud login.
    """
    await websocket.accept()
    store = JobStore.default()
    if not job_id or not token:
        job_id, token = await _credentials_from_first_message(websocket, job_id, token)
    attached = await notifier.attach(
        websocket, job_id=job_id, token=token, job_store=store
    )
    if not attached:
        return
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        notifier.disconnect(websocket)
        logger.info("Client disconnected")
    except Exception:
        notifier.disconnect(websocket)
        raise


async def _credentials_from_first_message(websocket: WebSocket, job_id, token):
    try:
        raw = await websocket.receive_text()
    except WebSocketDisconnect:
        return job_id, token
    except Exception as exc:
        logger.debug(f"WS credential message not received: {exc}")
        return job_id, token
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return job_id, token
    if not isinstance(data, dict):
        return job_id, token
    return data.get("job_id") or data.get("jobId") or job_id, data.get("token") or token
