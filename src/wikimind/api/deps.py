"""Shared FastAPI dependencies for route handlers.

Provides user identity extraction for multi-user data isolation.
When auth is disabled (single-user mode), user_id defaults to
``ANONYMOUS_USER_ID`` so every record has a non-null owner.
"""

from fastapi import Depends, HTTPException, Request

from wikimind.config import get_settings

ANONYMOUS_USER_ID = "anonymous"


async def get_current_user_id(request: Request) -> str:
    """Extract current user ID from request state.

    Returns ``ANONYMOUS_USER_ID`` when auth is disabled (single-user mode).
    """
    return getattr(request.state, "user_id", None) or ANONYMOUS_USER_ID


async def require_user_id(user_id: str = Depends(get_current_user_id)) -> str:
    """Require authentication. Raises 401 if auth is enabled but no user is set."""
    settings = get_settings()
    if settings.auth.enabled and user_id == ANONYMOUS_USER_ID:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
