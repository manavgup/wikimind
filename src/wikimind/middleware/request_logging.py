"""Middleware that emits a structured log line for every HTTP request.

Captures method, path, status code, response time, and the correlation
ID assigned by ``CorrelationIdMiddleware``.  Noisy endpoints such as
``/health`` and ``/docs`` are silently skipped to keep logs focused on
meaningful application traffic.
"""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_SKIP_PATHS: frozenset[str] = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})

log: structlog.stdlib.BoundLogger = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration."""

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """Time the request, then log its outcome."""
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        request_id: str = getattr(request.state, "request_id", "unknown")
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response
