"""Shared FastAPI dependencies for route handlers.

Provides user identity extraction for multi-user data isolation.
When auth is disabled (single-user mode), user_id defaults to
``ANONYMOUS_USER_ID`` so every record has a non-null owner.
"""

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import User

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


async def require_admin(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Require the current user to have admin privileges.

    Raises HTTP 403 if the user is not an admin.
    Returns the user_id if admin check passes.
    """
    settings = get_settings()
    # In single-user mode (auth disabled), allow access
    if not settings.auth.enabled:
        return user_id

    if user_id == ANONYMOUS_USER_ID:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


async def get_ws_user_id(websocket: WebSocket) -> str:
    """Extract user_id from JWT cookie on WebSocket upgrade.

    Falls back to ANONYMOUS_USER_ID when auth is disabled.

    Uses the same JWT decoding logic as :class:`wikimind.middleware.auth.AuthMiddleware`:
    reads the session cookie (``settings.auth.cookie_name``), then falls back to a
    ``token`` query parameter (for clients that cannot set cookies on the WS upgrade).
    """
    settings = get_settings()
    if not settings.auth.enabled:
        return ANONYMOUS_USER_ID

    token = websocket.cookies.get(settings.auth.cookie_name)
    if not token:
        # Allow passing the JWT as a query parameter (NOT user_id) for clients
        # that cannot attach cookies to the WebSocket upgrade request.
        token = websocket.query_params.get("token")

    if not token:
        return ANONYMOUS_USER_ID

    try:
        payload = jwt.decode(
            token,
            settings.auth.jwt_secret_key,
            algorithms=[settings.auth.jwt_algorithm],
            # Accept both session tokens (no aud) and API tokens (aud=wikimind-api).
            options={"verify_aud": False},
        )
        return payload.get("sub") or ANONYMOUS_USER_ID
    except jwt.InvalidTokenError:
        return ANONYMOUS_USER_ID
