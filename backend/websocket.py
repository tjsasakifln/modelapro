import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

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
    from modules.operacao_local.runtime import get_security_policy
    from modules.operacao_local.security import AccessDenied
    policy = get_security_policy()
    authorization = websocket.headers.get("authorization")
    if not authorization:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
            if len(raw) > 16384:
                raise ValueError("credential frame exceeds limit")
            credentials = json.loads(raw)
            if not isinstance(credentials, dict):
                raise ValueError("credential frame must be an object")
            authorization = "Bearer " + str(credentials.get("local_auth_token", ""))
            job_id, token = credentials.get("job_id"), credentials.get("token")
        except (ValueError, TimeoutError, WebSocketDisconnect):
            await websocket.close(code=1008)
            return
    try:
        policy.authorize(method="GET", authorization=authorization)
    except AccessDenied:
        await websocket.close(code=1008)
        return
    # Reuse the process JobStore. A new JobStore() here used to run
    # recover_abandoned(live_job_ids=()) and flip a live running job to
    # interrupted on the first /ws connection.
    from backend.api import get_job_store
    store = get_job_store()
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
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        if len(raw) > 16384:
            return None, None
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
