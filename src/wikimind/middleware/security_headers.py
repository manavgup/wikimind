"""HTTP security headers applied to every non-WebSocket response.

Adds a baseline set of headers that mitigate common browser-side
attacks (click-jacking, MIME-sniffing, reflected XSS, missing HSTS)
without requiring per-route opt-in.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from wikimind.config import get_settings

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'"
    ),
}

# Two-year max-age as recommended by OWASP; includeSubDomains ensures
# all sub-domains also use HTTPS.
_HSTS_VALUE = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject browser-security headers into every HTTP response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers, skipping WebSocket upgrade requests."""
        # WebSocket upgrades use a different response path; headers are irrelevant.
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        response = await call_next(request)

        # Relax CSP for FastAPI's built-in docs pages (Swagger/ReDoc load CDN
        # scripts and inline bootstrap JS that strict CSP blocks).
        path = request.url.path
        skip_csp = path in ("/docs", "/redoc", "/openapi.json")

        for name, value in _SECURITY_HEADERS.items():
            if skip_csp and name == "Content-Security-Policy":
                continue
            response.headers[name] = value

        # HSTS must only be sent over HTTPS. In development mode (HTTP)
        # it would cause browsers to refuse plain-text connections.
        if not get_settings().is_dev:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        return response
