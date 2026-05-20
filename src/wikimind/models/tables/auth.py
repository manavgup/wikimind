"""Auth tables — MCP tokens and OAuth credentials."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class MCPAccessToken(SQLModel, table=True):
    """Personal access token for MCP API authentication.

    Tokens use the ``wmk_`` prefix for easy identification. Only the
    SHA-256 hash is stored; the plaintext is shown once at creation and
    never persisted. See ADR-027.
    """

    __tablename__ = "mcp_access_token"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    token_hash: str  # SHA-256 hash (never store plaintext)
    token_prefix: str = Field(max_length=12)  # "wmk_ab12..." for display
    created_at: datetime = Field(default_factory=utcnow_naive)
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked: bool = False


class OAuthAuthorizationCode(SQLModel, table=True):
    """Short-lived OAuth 2.1 authorization code for MCP client flows.

    Created when a user approves an MCP client's authorization request.
    Exchanged for an access token at the token endpoint. Codes expire
    after 5 minutes and can only be used once (``used`` flag).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    code: str = Field(index=True)
    user_id: str = Field(foreign_key="user.id")
    client_id: str
    redirect_uri: str
    code_challenge: str  # S256 hash
    state: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime
    used: bool = False


class OAuthAccessToken(SQLModel, table=True):
    """OAuth 2.1 access token issued to MCP clients.

    Created during the token exchange (authorization_code grant).
    Tokens use the ``wmk_`` prefix and are validated by the MCP auth
    provider alongside PAT tokens.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    token_hash: str = Field(index=True)  # SHA-256 of the raw token
    user_id: str = Field(foreign_key="user.id", index=True)
    client_id: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime
    revoked: bool = False
