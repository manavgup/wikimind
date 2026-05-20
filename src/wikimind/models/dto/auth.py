"""Auth DTOs — dependency-light request/response schemas.

Covers OAuth, magic link, API tokens, and user profile responses.
"""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# OAuth models
# ---------------------------------------------------------------------------


class OAuthTokenResponse(BaseModel):
    """OAuth token exchange response from an external provider.

    Contains at minimum an ``access_token`` field. Additional fields
    vary by provider (e.g. ``token_type``, ``scope``, ``id_token``).
    """

    model_config = {"extra": "allow"}

    access_token: str
    token_type: str | None = None
    scope: str | None = None


class OAuthUserInfo(BaseModel):
    """User profile from an OAuth provider (Google or GitHub).

    Only ``id`` is guaranteed; other fields may be absent depending
    on the provider and scopes.
    """

    model_config = {"extra": "allow"}

    id: int | str
    email: str | None = None
    name: str | None = None
    login: str | None = None
    picture: str | None = None
    avatar_url: str | None = None


# ---------------------------------------------------------------------------
# Magic Link models
# ---------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    """Request to send a magic link login email."""

    email: str


class MagicLinkResponse(BaseModel):
    """Response after requesting a magic link."""

    status: str
    message: str
    dev_token: str | None = None


class MagicLinkVerifyRequest(BaseModel):
    """Request to verify a magic link token."""

    token: str


class MagicLinkVerifyResponse(BaseModel):
    """Response after successfully verifying a magic link token."""

    access_token: str
    token_type: str = "bearer"
    user: dict


# ---------------------------------------------------------------------------
# API token models
# ---------------------------------------------------------------------------


class TokenCreateRequest(BaseModel):
    """Request to create a long-lived API token."""

    name: str
    expires_in_days: int = Field(default=30, ge=1, le=365)


class TokenCreateResponse(BaseModel):
    """Response after creating a long-lived API token (shown only once)."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str
    name: str


# ---------------------------------------------------------------------------
# User profile models
# ---------------------------------------------------------------------------


class UserProfileResponse(BaseModel):
    """Public user profile returned by GET /auth/me."""

    id: str
    email: str | None = None
    name: str | None = None
    avatar_url: str | None = None


class DeleteAccountResponse(BaseModel):
    """Confirmation of account deletion."""

    deleted: str
