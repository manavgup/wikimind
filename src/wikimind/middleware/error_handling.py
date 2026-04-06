"""Catch-all error handling middleware for consistent JSON error responses.

Ensures that unhandled exceptions never leak stack traces to callers and
always produce the standard ``{"error": {"code", "message", "request_id"}}``
envelope.  WikiMindError subclasses are mapped to appropriate HTTP status
codes; everything else becomes a generic 500.
"""

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from wikimind.errors import WikiMindError

log = structlog.get_logger()


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Return a uniform JSON error envelope for any unhandled exception."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Wrap the downstream handler, catching all exceptions."""
        try:
            return await call_next(request)
        except WikiMindError as exc:
            request_id = _get_request_id(request)
            log.warning(
                "domain_error",
                code=exc.code,
                message=exc.message,
                request_id=request_id,
                path=request.url.path,
            )
            return _error_response(exc.status_code, exc.code, exc.message, request_id)
        except Exception as exc:
            request_id = _get_request_id(request)
            log.exception(
                "unhandled_error",
                error=str(exc),
                request_id=request_id,
                path=request.url.path,
            )
            return _error_response(500, "internal_error", "An unexpected error occurred", request_id)


def _get_request_id(request: Request) -> str:
    """Extract the request ID set by correlation middleware, falling back to 'unknown'."""
    return getattr(request.state, "request_id", "unknown")


def _error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    """Build the standard WikiMind error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )
