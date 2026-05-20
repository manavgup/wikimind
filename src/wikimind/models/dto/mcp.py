"""MCP token DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class MCPTokenCreateRequest(BaseModel):
    """Request to generate a new MCP personal access token."""

    name: str = Field(min_length=1, max_length=100)


class MCPTokenCreateResponse(BaseModel):
    """Response after creating an MCP token (plaintext shown ONCE)."""

    id: str
    token: str  # Plaintext — shown only at creation, never stored
    name: str
    created_at: datetime


class MCPTokenResponse(BaseModel):
    """API response for an existing MCP token (never includes plaintext)."""

    id: str
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class MCPTokenRevokeResponse(BaseModel):
    """Response after revoking an MCP token."""

    status: str
