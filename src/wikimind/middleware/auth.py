"""JWT authentication middleware for OAuth2-protected endpoints.

When ``settings.auth.enabled`` is False (default), the middleware is a
pass-through — every request proceeds with ``request.state.user_id = None``,
preserving backward-compatible single-user mode.

When enabled, the middleware extracts a JWT from the ``Authorization: Bearer``
header, decodes it, and sets ``request.state.user_id`` and
``request.state.user_email`` for downstream route handlers. Exempt paths
(health check, docs, auth routes) are never challenged.
"""

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from wikimind.config import get_settings

EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
EXEMPT_PREFIXES = ("/auth/login/", "/auth/callback")


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce JWT authentication when auth is enabled."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate JWT token or pass through when auth is disabled."""
        settings = get_settings()

        if not settings.auth.enabled:
            request.state.user_id = None
            request.state.user_email = None
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            request.state.user_id = None
            request.state.user_email = None
            return await call_next(request)

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing authentication token",
                    }
                },
            )

        try:
            payload = jwt.decode(
                token,
                settings.auth.jwt_secret_key,
                algorithms=[settings.auth.jwt_algorithm],
            )
            request.state.user_id = payload["sub"]
            request.state.user_email = payload.get("email")
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "TOKEN_EXPIRED",
                        "message": "Token has expired",
                    }
                },
            )
        except jwt.InvalidTokenError:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": "Invalid token",
                    }
                },
            )

        return await call_next(request)
