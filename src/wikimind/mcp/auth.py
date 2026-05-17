"""JWT authentication for MCP HTTP transport.

Validates tokens using the same secret and algorithm as the FastAPI
auth middleware. Stdio transport skips auth entirely.
"""

from __future__ import annotations

import jwt
from fastmcp.server.auth import AccessToken, TokenVerifier


class WikiMindJWTAuthProvider(TokenVerifier):
    """Validate WikiMind JWT tokens for MCP HTTP transport."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        """Decode and validate a JWT token, returning an AccessToken."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=["HS256"])
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
