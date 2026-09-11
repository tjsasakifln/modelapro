from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from modules.websocket_notifier import WebSocketNotifier
from modules.logging_manager import logger

router = APIRouter()
notifier = WebSocketNotifier()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await notifier.connect(websocket)
    try:
        while True:
            # Keep connection alive and listen for client messages if needed
            data = await websocket.receive_text()
            # For now we just echo or log, main logic is server->client notifications
            logger.debug(f"Received message from client: {data}")
    except WebSocketDisconnect:
        notifier.disconnect(websocket)
        logger.info("Client disconnected")
