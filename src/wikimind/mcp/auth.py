"""JWT authentication provider for MCP HTTP transport.

Reuses the same JWT validation logic as the FastAPI auth middleware
(same secret, algorithm, and payload structure) so that tokens issued
by the WikiMind OAuth flow work seamlessly with the MCP server.

Stdio transport (local Claude Desktop) does NOT use this provider.
"""

from __future__ import annotations

import jwt
import structlog
from fastmcp.server.auth import AccessToken, TokenVerifier

from wikimind.config import get_settings

log = structlog.get_logger()


class WikiMindJWTAuthProvider(TokenVerifier):
    """Verify WikiMind JWT tokens for MCP HTTP transport.

    Accepts the same Bearer tokens used by the FastAPI application.
    Extracts user_id from the ``sub`` claim and stores it in
    AccessToken.claims for tool handlers to read.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a JWT Bearer token and return an AccessToken.

        Returns None if the token is invalid or expired, which causes
        FastMCP to respond with a 401 Unauthorized.
        """
        settings = get_settings()

        try:
            payload = jwt.decode(
                token,
                settings.auth.jwt_secret_key,
                algorithms=[settings.auth.jwt_algorithm],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            log.warning("mcp_auth: token expired")
            return None
        except jwt.InvalidTokenError:
            log.warning("mcp_auth: invalid token")
            return None

        user_id = payload.get("sub")
        if not user_id:
            log.warning("mcp_auth: token missing 'sub' claim")
            return None

        # Extract email from payload (same logic as FastAPI auth middleware)
        user_claim = payload.get("user")
        email = user_claim.get("email", "") if isinstance(user_claim, dict) else payload.get("email", "")

        return AccessToken(
            token=token,
            client_id=user_id,
            scopes=[],
            claims={"user_id": user_id, "email": email},
        )
