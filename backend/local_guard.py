"""C04 safeguards attached to the actual ASGI surface, including WebSocket."""
import os
import threading
from urllib.parse import parse_qsl

from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException

from modules.operacao_local.runtime import get_security_policy, license_decision
from modules.operacao_local.security import AccessDenied, WorkspacePathResolver


class LocalRequestGuard:
    def __init__(self, app):
        self.app = app
        self._maintenance_lock = threading.Lock()
        self._active_http = 0
        self._restoring = False

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if kind == "http" and path == "/health" and method == "GET":
            return await self.app(scope, receive, send)
        try:
            policy = get_security_policy()
            origin = headers.get("origin")
            if origin and origin not in policy.allowed_origins:
                raise AccessDenied("origin is not explicitly allowed")
            workspace = os.environ.get("MODELA_WORKSPACE_ID", "local")
            WorkspacePathResolver(".").require_workspace(workspace, headers.get("x-workspace-id", workspace))
            query_names = {key.lower() for key, _ in parse_qsl(scope.get("query_string", b"").decode())}
            if query_names & {"token", "access_token", "local_auth_token", "authorization"}:
                raise AccessDenied("credentials in URLs are forbidden")
            if kind == "websocket":
                if not origin:
                    raise AccessDenied("WebSocket Origin required")
                # Browser clients authenticate in their first message; never in a URL.
            elif method == "OPTIONS":
                if not origin:
                    raise AccessDenied("preflight Origin required")
            else:
                policy.authorize(method=method, authorization=headers.get("authorization"),
                                 origin=origin, csrf_token=headers.get("x-csrf-token"))
                creates_calculation = method == "POST" and (
                    path in {"/jobs", "/upload"} or path.endswith("/batch")
                )
                if creates_calculation and not license_decision().permits("calculate"):
                    return await JSONResponse({"error": "LICENSE_CALCULATION_NOT_PERMITTED"}, status_code=403)(
                        scope, receive, send)
        except (AccessDenied, ValueError, OSError):
            if kind == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"error": "LOCAL_ACCESS_DENIED"}, status_code=403)(scope, receive, send)
        if kind != "http":
            return await self.app(scope, receive, send)
        from modules.config_manager import config
        limit = 2 * 1024 * 1024
        if path == "/operations/license":
            limit = 65536
        elif path == "/operations/restore":
            limit = 101 * 1024 * 1024
        elif path.endswith("/recipient-return"):
            limit = 21 * 1024 * 1024
        elif path in {"/preview", "/upload", "/jobs"} or path.endswith(("/attachments", "/signature")):
            limit = (config.MAX_UPLOAD_MB + 1) * 1024 * 1024
        try:
            length = int(headers.get("content-length", "0"))
            if length < 0:
                raise ValueError("negative length")
        except ValueError:
            return await JSONResponse({"error": "INVALID_CONTENT_LENGTH"}, status_code=400)(scope, receive, send)
        if length > limit:
            return await JSONResponse({"error": "REQUEST_BODY_TOO_LARGE"}, status_code=413)(scope, receive, send)
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(413, "REQUEST_BODY_TOO_LARGE")
            return message

        restoring = path == "/operations/restore" and method == "POST"
        with self._maintenance_lock:
            admitted = not self._restoring and (not restoring or self._active_http == 0)
            if admitted:
                self._active_http += 1
                self._restoring = restoring
        if not admitted:
            return await JSONResponse({"error": "WORKSPACE_MAINTENANCE_CONFLICT"}, status_code=409)(scope, receive, send)
        try:
            return await self.app(scope, bounded_receive, send)
        finally:
            with self._maintenance_lock:
                self._active_http -= 1
                if restoring:
                    self._restoring = False
