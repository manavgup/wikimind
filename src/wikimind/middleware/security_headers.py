"""HTTP security headers applied to every non-WebSocket response.

Adds a baseline set of headers that mitigate common browser-side
attacks (click-jacking, MIME-sniffing, reflected XSS) without
requiring per-route opt-in.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject browser-security headers into every HTTP response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers, skipping WebSocket upgrade requests."""
        # WebSocket upgrades use a different response path; headers are irrelevant.
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        response = await call_next(request)

        for name, value in _SECURITY_HEADERS.items():
            response.headers[name] = value

        return response
