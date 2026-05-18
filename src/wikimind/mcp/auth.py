"""Authentication for MCP HTTP transport — supports both JWTs and PATs.

JWTs are validated using the same secret and algorithm as the FastAPI
auth middleware. Personal access tokens (PATs) use the ``wmk_`` prefix
and are validated by SHA-256 hash lookup. Stdio transport skips auth
entirely. See ADR-027.
"""

from __future__ import annotations

import hashlib

import jwt
import structlog
from fastmcp.server.auth import AccessToken, TokenVerifier

from wikimind._datetime import utcnow_naive
from wikimind.database import get_session_factory
from wikimind.models import MCPAccessToken

log = structlog.get_logger()


class WikiMindAuthProvider(TokenVerifier):
    """Validate WikiMind JWT or PAT tokens for MCP HTTP transport."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        """Route to PAT or JWT validation based on token prefix."""
        if token.startswith("wmk_"):
            return await self._verify_pat(token)
        return await self._verify_jwt(token)

    async def _verify_pat(self, token: str) -> AccessToken:
        """Validate a personal access token by hash lookup."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        from sqlmodel import select  # noqa: PLC0415 — deferred to avoid circular import

        async with get_session_factory()() as session:
            result = await session.exec(select(MCPAccessToken).where(MCPAccessToken.token_hash == token_hash))
            token_row = result.one_or_none()

            if token_row is None:
                msg = "Invalid token"
                raise ValueError(msg)

            if token_row.revoked:
                msg = "Token has been revoked"
                raise ValueError(msg)

            if token_row.expires_at is not None and token_row.expires_at < utcnow_naive():
                msg = "Token expired"
                raise ValueError(msg)

            # Update last_used_at
            token_row.last_used_at = utcnow_naive()
            session.add(token_row)
            await session.commit()

            return AccessToken(
                token=token,
                client_id=token_row.user_id,
                scopes=[],
            )

    async def _verify_jwt(self, token: str) -> AccessToken:
        """Decode and validate a JWT token, returning an AccessToken."""
        try:
            from wikimind.config import get_settings  # noqa: PLC0415

            settings = get_settings()
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[settings.auth.jwt_algorithm],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            msg = "Token expired"
            raise ValueError(msg) from exc
        except jwt.InvalidTokenError as exc:
            msg = "Invalid token"
            raise ValueError(msg) from exc

        user_id = payload.get("sub")
        if not user_id:
            msg = "Token missing 'sub' claim"
            raise ValueError(msg)

        return AccessToken(token=token, client_id=user_id, scopes=[])
