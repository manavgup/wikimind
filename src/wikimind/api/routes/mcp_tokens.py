"""MCP personal access token management endpoints.

Mounted at ``/api/settings/mcp-tokens`` — users generate, list, and revoke
personal access tokens for authenticating MCP clients (Claude Desktop, etc.).
See ADR-027.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import (
    MCPAccessToken,
    MCPTokenCreateRequest,
    MCPTokenCreateResponse,
    MCPTokenResponse,
    MCPTokenRevokeResponse,
)

log = structlog.get_logger()

router = APIRouter()


def _generate_pat() -> tuple[str, str, str]:
    """Generate a personal access token.

    Returns:
        Tuple of (raw_token, token_hash, token_prefix).
    """
    raw_token = f"wmk_{secrets.token_hex(16)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token_prefix = raw_token[:12]
    return raw_token, token_hash, token_prefix


@router.post("", response_model=MCPTokenCreateResponse)
async def create_mcp_token(
    request: MCPTokenCreateRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> MCPTokenCreateResponse:
    """Generate a new MCP personal access token.

    The plaintext token is returned ONCE in the response. It is never
    stored — only the SHA-256 hash is persisted.
    """
    raw_token, token_hash, token_prefix = _generate_pat()

    token_row = MCPAccessToken(
        user_id=user_id,
        name=request.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
    )
    session.add(token_row)
    await session.commit()
    await session.refresh(token_row)

    log.info("MCP token created", token_id=token_row.id, name=request.name)

    return MCPTokenCreateResponse(
        id=token_row.id,
        token=raw_token,
        name=token_row.name,
        created_at=token_row.created_at,
    )


@router.get("", response_model=list[MCPTokenResponse])
async def list_mcp_tokens(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> list[MCPTokenResponse]:
    """List all MCP tokens for the current user (never returns plaintext)."""
    stmt = (
        select(MCPAccessToken).where(MCPAccessToken.user_id == user_id).order_by(MCPAccessToken.created_at.desc())  # type: ignore[attr-defined]
    )
    result = await session.exec(stmt)
    tokens = result.all()
    return [
        MCPTokenResponse(
            id=t.id,
            name=t.name,
            token_prefix=t.token_prefix,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
            revoked=t.revoked,
        )
        for t in tokens
    ]


@router.delete("/{token_id}", response_model=MCPTokenRevokeResponse)
async def revoke_mcp_token(
    token_id: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> MCPTokenRevokeResponse:
    """Revoke an MCP token (soft delete — sets revoked=True)."""
    token_row = await session.get(MCPAccessToken, token_id)
    if not token_row or token_row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Token not found")

    token_row.revoked = True
    session.add(token_row)
    await session.commit()

    log.info("MCP token revoked", token_id=token_id)

    return MCPTokenRevokeResponse(status="revoked")
