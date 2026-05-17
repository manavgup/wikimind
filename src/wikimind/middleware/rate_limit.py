"""Rate limiting middleware backed by Redis (or in-memory for dev).

Uses slowapi to enforce per-user rate limits on auth, query, and ingest
endpoints. When Redis is configured, limits are shared across workers;
otherwise falls back to in-memory storage for single-process dev mode.

The limiter key function extracts the user ID from ``request.state``
(set by the auth middleware), falling back to the client IP for
unauthenticated endpoints (e.g. login).
"""

from __future__ import annotations

import contextlib

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded  # noqa: TC002 — used at runtime in handler signature
from slowapi.util import get_remote_address
from starlette.requests import Request  # noqa: TC002 — used in function signatures consumed by slowapi
from starlette.responses import JSONResponse

from wikimind.config import get_settings


def _key_func(request: Request) -> str:
    """Extract rate limit key: user_id if authenticated, else client IP."""
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    if user_id:
        return user_id
    return get_remote_address(request)


def _create_limiter() -> Limiter:
    """Create the rate limiter with current settings."""
    settings = get_settings()
    return Limiter(
        key_func=_key_func,
        storage_uri=settings.redis_url,
        enabled=settings.rate_limit.enabled,
        in_memory_fallback_enabled=True,
    )


limiter = _create_limiter()


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a standard 429 response with Retry-After header.

    Formats the rate-limit error using the project's standard JSON
    error envelope and includes a ``Retry-After`` header.
    """
    request_id = getattr(getattr(request, "state", None), "request_id", "unknown")

    # Derive retry window from the rate limit that was exceeded.
    # exc.limit is a slowapi Limit wrapper whose .limit is a
    # limits.RateLimitItem with .get_expiry() returning seconds.
    retry_after_seconds = "60"
    with contextlib.suppress(Exception):
        retry_after_seconds = str(exc.limit.limit.get_expiry())

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": f"Rate limit exceeded: {exc.detail}",
                "request_id": request_id,
            }
        },
        headers={"Retry-After": retry_after_seconds},
    )
