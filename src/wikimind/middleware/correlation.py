"""Middleware that assigns a unique request ID to every incoming request.

Generates a UUID-v4 correlation ID for each request and attaches it to
``request.state.request_id``.  If the caller already provides an
``X-Request-ID`` header (e.g. from an upstream gateway or another
micro-service), that value is reused so the same trace ID propagates
across the entire call chain.  The chosen ID is always echoed back in
the ``X-Request-ID`` response header.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation / request ID to every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """Generate or propagate a request ID, then forward the request."""
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
