from typing import Dict, Any
from datetime import datetime, date
import json
import math
import asyncio
import numpy as np
from .logging_manager import logger


def _json_safe(obj: Any) -> Any:
    """
    Recursively converts a value into something the standard json encoder
    can always serialize, so a single unexpected type or non-finite float
    deep inside a result payload (datetime timestamps, numpy scalars from
    statsmodels/numpy computations, or inf/nan metrics) can never make
    send_notification() raise and swallow the real result.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, np.generic):
        # Covers numpy scalar types (float32/float64, int*, bool_, ...).
        return _json_safe(obj.item())
    if isinstance(obj, float):
        # Bare Infinity/NaN are accepted by json.dumps (json.dumps allows
        # them by default) but are NOT valid JSON per RFC 8259 and make a
        # browser's JSON.parse throw client-side, which is the same
        # "notification silently never arrives" symptom this guards
        # against. Normalize to None (serialized as JSON null) instead.
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


class WebSocketNotifier:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WebSocketNotifier, cls).__new__(cls)
            cls._instance.active_connections = []
        return cls._instance
    
    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
    def disconnect(self, websocket):
        self.active_connections.remove(websocket)
        
    async def send_notification(self, message: Dict[str, Any]):
        """
        Sends a notification to all connected clients.
        """
        if not self.active_connections:
            return

        try:
            json_message = json.dumps(_json_safe(message))
        except Exception as e:
            logger.error(f"Error serializing notification payload: {str(e)}")
            # Fall back to a minimal, guaranteed-serializable error payload
            # instead of silently dropping the notification: the caller
            # (e.g. worker.process_file) awaits this call inside a broad
            # try/except and has no other way to learn delivery failed.
            fallback = {
                "status": "error",
                "message": f"Falha ao serializar notificação: {str(e)}",
            }
            json_message = json.dumps(fallback)

        for connection in self.active_connections:
            try:
                await connection.send_text(json_message)
            except Exception as e:
                logger.error(f"Error sending notification: {str(e)}")
                # Potentially remove dead connection
