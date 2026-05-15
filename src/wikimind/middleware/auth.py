"""JWT authentication middleware for OAuth2-protected endpoints.

Auth is always on. In development mode with ``dev_auto_auth`` enabled,
the middleware auto-authenticates every request as the dev user (looked
up or created at startup via ``_ensure_dev_user``). In production, the
middleware extracts a JWT from the ``wikimind_session`` HttpOnly cookie
(set during the OAuth callback) or the ``Authorization: Bearer`` header.

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
# NOTE: .png and .svg are intentionally excluded — API-served images
# (e.g. /api/sources/{id}/images/{filename}) require auth.  Static frontend
# images are already covered by the "/assets/" prefix exemption above.
_STATIC_EXTENSIONS = (".html", ".js", ".css", ".ico", ".woff", ".woff2", ".map")
# API route prefixes that require auth. Everything else is a frontend SPA route
# (served as index.html by the static file mount) and must be exempt.
# Paths that are always exempt from auth regardless of method.
# Non-API paths (SPA routes) are also exempt — they serve index.html.
# Auth is enforced on API routes by checking Accept header: API clients
# send Accept: application/json, browsers loading SPA pages send text/html.

# Cached dev user ID — populated once on first request in dev-auto-auth mode.
_dev_user_id: str | None = None


def reset_dev_user_cache() -> None:
    """Clear the cached dev user ID (used by tests)."""
    global _dev_user_id
    _dev_user_id = None


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce JWT authentication on all requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Validate JWT token or auto-authenticate in dev mode."""
        settings = get_settings()

        # Dev-mode auto-auth: auto-authenticate as the dev user.
        if settings.is_dev and settings.auth.dev_auto_auth:
            global _dev_user_id
            if _dev_user_id is None:
                from wikimind.database import get_dev_user_id  # noqa: PLC0415

                _dev_user_id = await get_dev_user_id()
            request.state.user_id = _dev_user_id
            request.state.user_email = settings.auth.dev_user_email
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
