from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Requires `Authorization: Bearer <token>` on every request.

    This guards the HTTP transport itself (a shared secret between this
    server and whoever is allowed to call it) — separate from and unrelated
    to the OAuth Client Credentials Flow this server uses as a *client* of
    Salesforce. Only active when running in HTTP/hosted mode; stdio mode has
    no network exposure to protect.
    """

    def __init__(self, app: ASGIApp, token: str):
        super().__init__(app)
        self._expected = f"Bearer {token}"

    async def dispatch(self, request: Request, call_next):
        if request.headers.get("Authorization") != self._expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
