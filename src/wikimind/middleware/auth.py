"""JWT authentication middleware for OAuth2-protected endpoints.

When ``settings.auth.enabled`` is False (default), the middleware is a
pass-through — every request proceeds with ``request.state.user_id = None``.
The ``get_current_user_id`` dependency coalesces this to ``"anonymous"``.

When enabled, the middleware extracts a JWT from the ``wikimind_session``
HttpOnly cookie (set during the OAuth callback). If no cookie is present,
it falls back to the ``Authorization: Bearer`` header for API clients.
The decoded payload sets ``request.state.user_id`` and
``request.state.user_email`` for downstream route handlers. Exempt paths
(health check, docs, auth routes, logout) are never challenged.
"""

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from wikimind.config import get_settings

EXEMPT_PATHS = {"/health", "/health/deep", "/metrics", "/docs", "/openapi.json", "/redoc"}
EXEMPT_PREFIXES = (
    "/auth/login/",
    "/auth/callback",
    "/auth/logout",
    "/auth/magic-link",
    "/assets/",
    "/public/",
)
# Static frontend files that must load without auth so users can see the login page.
_STATIC_EXTENSIONS = (".html", ".js", ".css", ".ico", ".png", ".svg", ".woff", ".woff2", ".map")
# API route prefixes that require auth. Everything else is a frontend SPA route
# (served as index.html by the static file mount) and must be exempt.
# Paths that are always exempt from auth regardless of method.
# Non-API paths (SPA routes) are also exempt — they serve index.html.
# Auth is enforced on API routes by checking Accept header: API clients
# send Accept: application/json, browsers loading SPA pages send text/html.


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
        # Check if this is an API request (Accept: application/json) or a
        # browser page load (Accept: text/html). SPA routes should never
        # be auth-blocked — they need to load index.html so the frontend
        # can handle auth client-side.
        accept = request.headers.get("accept", "")
        is_html_request = "text/html" in accept and "application/json" not in accept
        is_exempt = (
            is_html_request
            or path in EXEMPT_PATHS
            or any(path.startswith(p) for p in EXEMPT_PREFIXES)
            or any(path.endswith(ext) for ext in _STATIC_EXTENSIONS)
        )
        if is_exempt:
            request.state.user_id = None
            request.state.user_email = None
            return await call_next(request)

        token = request.cookies.get(settings.auth.cookie_name, "")
        if not token:
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
                # Accept both session tokens (no aud) and API tokens (aud=wikimind-api).
                options={"verify_aud": False},
            )
            request.state.user_id = payload["sub"]
            # API tokens include email in a nested ``user`` dict.
            user_claim = payload.get("user")
            if isinstance(user_claim, dict):
                request.state.user_email = user_claim.get("email")
            else:
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
