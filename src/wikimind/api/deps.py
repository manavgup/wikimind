"""Shared FastAPI dependencies for route handlers.

Provides user identity extraction for multi-user data isolation.
When auth is disabled (single-user mode), user_id is None and all
queries return unfiltered data.
"""

from fastapi import Depends, HTTPException, Request

from wikimind.config import get_settings


async def get_current_user_id(request: Request) -> str | None:
    """Extract current user ID from request state. Returns None in single-user mode."""
    return getattr(request.state, "user_id", None)


async def require_user_id(user_id: str | None = Depends(get_current_user_id)) -> str:
    """Require authentication. Raises 401 if auth is enabled but no user."""
    settings = get_settings()
    if settings.auth.enabled and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id or ""
