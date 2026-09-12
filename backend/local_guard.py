"""C04 safeguards attached to the actual ASGI surface, including WebSocket."""
import os

from starlette.responses import JSONResponse

from modules.operacao_local.runtime import get_security_policy, license_decision
from modules.operacao_local.security import AccessDenied, WorkspacePathResolver


class LocalRequestGuard:
    def __init__(self, app):
        self.app = app

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
            if kind == "websocket":
                if not origin:
                    raise AccessDenied("WebSocket Origin required")
                # Browser clients authenticate in their first message; never in a URL.
                if scope.get("query_string") and b"token=" in scope["query_string"]:
                    raise AccessDenied("credentials in WebSocket URL are forbidden")
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
        return await self.app(scope, receive, send)
