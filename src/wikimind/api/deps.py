"""Shared FastAPI dependencies for route handlers.

Provides user identity extraction for multi-user data isolation.
Auth is always on — ``get_current_user_id`` raises 401 if no user is set.
In dev mode the middleware auto-authenticates; in production a JWT is required.
"""

from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.database import get_session  # CodeQL: cyclic-import — unavoidable, see #649

if TYPE_CHECKING:
    from wikimind.models import Plan


async def get_current_user_id(request: Request) -> str:
    """Extract current user ID from request state.

    Raises HTTP 401 if no user_id is set — there is no anonymous fallback.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def require_user_id(user_id: str = Depends(get_current_user_id)) -> str:
    """Require authentication. Raises 401 if no user is set."""
    return user_id


async def require_admin(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Require the current user to have admin privileges.

    Raises HTTP 403 if the user is not an admin.
    Returns the user_id if admin check passes.
    """
    from wikimind.models import User  # noqa: PLC0415 — deferred to avoid circular import

    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()
    if user is None or not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "Admin access required"}},
        )
    return user_id


async def require_plan(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> "Plan | None":
    """Load user's effective plan. Returns None in self-hosted mode.

    Routes use ``if plan:`` to skip quota checks when billing is disabled.
    """
    if not get_settings().billing_enabled:
        return None
    from wikimind.services.quota import get_effective_plan  # noqa: PLC0415 — deferred to avoid circular import

    return await get_effective_plan(session, user_id)


async def get_ws_user_id(websocket: WebSocket) -> str:
    """Extract user_id from JWT cookie on WebSocket upgrade.

    In dev mode with dev_auto_auth, returns the dev user ID.
    Otherwise decodes a JWT from the session cookie or ``token`` query param.
    Rejects the connection if no valid user can be identified.
    """
    settings = get_settings()

    # Dev-mode auto-auth for WebSocket connections
    if settings.is_dev and settings.auth.dev_auto_auth:
        from wikimind.database import get_dev_user_id  # noqa: PLC0415

        return await get_dev_user_id()

    token = websocket.cookies.get(settings.auth.cookie_name)
    if not token:
        # Allow passing the JWT as a query parameter (NOT user_id) for clients
        # that cannot attach cookies to the WebSocket upgrade request.
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        msg = "WebSocket authentication required"
        raise HTTPException(status_code=401, detail=msg)

    try:
        payload = jwt.decode(
            token,
            settings.auth.jwt_secret_key,
            algorithms=[settings.auth.jwt_algorithm],
            # Accept both session tokens (no aud) and API tokens (aud=wikimind-api).
            options={"verify_aud": False},
        )
        sub = payload.get("sub")
        if not sub:
            await websocket.close(code=4001, reason="Authentication required")
            msg = "WebSocket authentication required"
            raise HTTPException(status_code=401, detail=msg)
        return sub
    except jwt.InvalidTokenError:
        await websocket.close(code=4001, reason="Invalid token")
        msg = "WebSocket authentication failed"
        raise HTTPException(status_code=401, detail=msg) from None
