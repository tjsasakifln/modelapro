"""Scoped local WebSocket notifications (light progress only).

``/ws`` is optional. Job results live in JobStore and are read via C10 HTTP.
This module does not broadcast completed payloads or PDFs to every socket.
"""

from typing import Any, Dict, Optional
from datetime import datetime, date
import json
import math
import numpy as np
from .logging_manager import logger

from modules.job_store import CONTRACT_VERSION


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


_LIGHT_ALLOW = frozenset(
    {
        "schema_version",
        "job_id",
        "project_id",
        "state",
        "stage",
        "progress",
        "result_available",
        "status",
        "message",
    }
)
_HEAVY_DENY = frozenset(
    {
        "report_pdf_base64",
        "charts",
        "snapshot",
        "model_metrics",
        "formula",
        "validation",
        "value",
        "sample",
        "model",
        "search",
        "alternatives",
        "next_actions",
        "provenance",
        "artifact_bytes",
        "pdf",
        "payload",
        "target",
        "issues",
        "artifact_states",
    }
)


def light_progress_payload(message: Dict[str, Any], *, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Strip snapshot/PDF/model bodies. Progress is null or in [0, 1]."""
    source = message or {}
    out: Dict[str, Any] = {"schema_version": CONTRACT_VERSION}
    for key, value in source.items():
        if key in _HEAVY_DENY:
            continue
        if key in _LIGHT_ALLOW:
            out[key] = value
    if job_id:
        out["job_id"] = job_id
    elif source.get("job_id"):
        out["job_id"] = source["job_id"]
    progress = out.get("progress", None)
    if progress is not None:
        try:
            progress_f = float(progress)
        except (TypeError, ValueError):
            out["progress"] = None
        else:
            if not math.isfinite(progress_f) or progress_f < 0.0 or progress_f > 1.0:
                out["progress"] = None
            else:
                out["progress"] = progress_f
    return _json_safe(out)


class WebSocketNotifier:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WebSocketNotifier, cls).__new__(cls)
            cls._instance._init_state()
        else:
            cls._instance._ensure_state()
        return cls._instance

    def _init_state(self) -> None:
        self.active_connections = []
        self._by_job = {}
        self._ws_job = {}

    def _ensure_state(self) -> None:
        if not hasattr(self, "active_connections") or self.active_connections is None:
            self.active_connections = []
        if not hasattr(self, "_by_job") or self._by_job is None:
            self._by_job = {}
        if not hasattr(self, "_ws_job") or self._ws_job is None:
            self._ws_job = {}

    def reset_connections(self) -> None:
        self.active_connections = []
        self._by_job = {}
        self._ws_job = {}

    async def connect(self, websocket, job_id=None, token=None, job_store=None):
        await websocket.accept()
        return await self.attach(
            websocket, job_id=job_id, token=token, job_store=job_store
        )

    async def attach(self, websocket, job_id=None, token=None, job_store=None) -> bool:
        """Bind an already-accepted socket to a local job_id+token scope."""
        self._ensure_state()
        if not job_id or not token:
            await self._reject(websocket, "job_id and token are required")
            return False
        store = job_store
        if store is None:
            from modules.job_store import JobStore

            store = JobStore.default()
        if not store.verify_access(str(job_id), str(token)):
            await self._reject(websocket, "invalid job_id or token")
            return False
        job_id = str(job_id)
        self._by_job.setdefault(job_id, [])
        if websocket not in self._by_job[job_id]:
            self._by_job[job_id].append(websocket)
        self._ws_job[id(websocket)] = job_id
        if websocket not in self.active_connections:
            self.active_connections.append(websocket)
        job = store.get(job_id)
        if job is not None:
            await self.send_progress(
                job_id,
                {
                    "status": job["state"],
                    "state": job["state"],
                    "stage": job.get("stage"),
                    "progress": job.get("progress"),
                    "result_available": job.get("result_available"),
                    "project_id": job.get("project_id"),
                    "job_id": job_id,
                },
            )
        return True

    def disconnect(self, websocket) -> None:
        self._ensure_state()
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass
        job_id = self._ws_job.pop(id(websocket), None)
        if job_id is None:
            for scoped_id, bucket in list(self._by_job.items()):
                if websocket in bucket:
                    job_id = scoped_id
                    break
        if job_id is not None:
            bucket = self._by_job.get(job_id) or []
            try:
                bucket.remove(websocket)
            except ValueError:
                pass
            if not bucket:
                self._by_job.pop(job_id, None)

    def connections_for(self, job_id: str):
        self._ensure_state()
        return list(self._by_job.get(job_id, []))

    async def send_progress(self, job_id: str, message: Dict[str, Any]) -> None:
        """Deliver a light status/progress event to sockets bound to job_id."""
        self._ensure_state()
        light = light_progress_payload(message, job_id=job_id)
        try:
            json_message = json.dumps(light, allow_nan=False)
        except Exception as e:
            logger.error(f"Error serializing progress payload: {str(e)}")
            json_message = json.dumps(
                {
                    "schema_version": CONTRACT_VERSION,
                    "job_id": job_id,
                    "status": "error",
                    "message": f"Falha ao serializar notificação: {str(e)}",
                }
            )
        dead = []
        for connection in list(self._by_job.get(job_id, [])):
            try:
                await connection.send_text(json_message)
            except Exception as e:
                logger.error(f"Error sending notification: {str(e)}")
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)

    async def send_notification(self, message: Dict[str, Any]):
        """
        Legacy adapter used by C10's current worker.

        Serializes with ``_json_safe`` so unexpected types cannot raise into
        the worker. Does **not** broadcast a completed result or PDF to every
        socket. If ``job_id`` is present, a light progress event is sent only
        to connections scoped to that job.
        """
        if not isinstance(message, dict):
            message = {"status": "error", "message": "invalid notification"}
        try:
            json.dumps(_json_safe(message), allow_nan=False)
        except Exception as e:
            logger.error(f"Error serializing notification payload: {str(e)}")
            message = {
                "status": "error",
                "message": f"Falha ao serializar notificação: {str(e)}",
            }
        job_id = message.get("job_id")
        if not job_id:
            logger.info(
                "send_notification dropped unscoped payload; results are persisted "
                "and read via GET /jobs/{id}/result, not global WebSocket broadcast"
            )
            return
        await self.send_progress(str(job_id), message)

    async def _reject(self, websocket, message: str) -> None:
        try:
            await websocket.send_text(
                json.dumps(
                    {
                        "schema_version": CONTRACT_VERSION,
                        "status": "error",
                        "message": message,
                    }
                )
            )
        except Exception:
            pass
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
