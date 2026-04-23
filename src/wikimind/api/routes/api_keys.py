"""BYOK API key management endpoints.

Lets authenticated users store, list, and delete their own LLM provider
API keys.  Keys are encrypted at rest (Fernet + PBKDF2).  Responses
never expose raw keys -- only provider names and masked hints.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import require_user_id
from wikimind.database import get_session
from wikimind.models import Provider
from wikimind.services.api_keys import (
    decrypt_api_key,
    delete_user_api_key,
    list_user_api_keys,
    mask_api_key,
    set_user_api_key,
)

router = APIRouter()

# Providers that accept user-supplied API keys (Ollama and Mock don't use keys)
_BYOK_PROVIDERS = {Provider.ANTHROPIC, Provider.OPENAI, Provider.GOOGLE}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SetApiKeyRequest(BaseModel):
    """Request to store an API key for a provider."""

    api_key: str


class ApiKeyInfo(BaseModel):
    """Summary of a configured API key (no raw key exposed)."""

    provider: str
    key_hint: str
    created_at: datetime
    updated_at: datetime


class ApiKeyListResponse(BaseModel):
    """List of configured API key providers."""

    keys: list[ApiKeyInfo]


class ApiKeySetResponse(BaseModel):
    """Response after setting an API key."""

    provider: str
    key_hint: str
    status: str


class ApiKeyDeleteResponse(BaseModel):
    """Response after deleting an API key."""

    provider: str
    status: str


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _validate_provider(provider: str) -> Provider:
    """Validate and return the provider enum, raising 400 for invalid values."""
    try:
        p = Provider(provider)
    except ValueError as err:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}",
        ) from err
    if p not in _BYOK_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider {provider} does not support user API keys",
        )
    return p


@router.put(
    "/{provider}",
    response_model=ApiKeySetResponse,
)
async def set_api_key(
    provider: str,
    request: SetApiKeyRequest,
    user_id: str = Depends(require_user_id),
    session: AsyncSession = Depends(get_session),
) -> ApiKeySetResponse:
    """Store or update an API key for a provider."""
    p = _validate_provider(provider)

    if not request.api_key.strip():
        raise HTTPException(status_code=400, detail="API key must not be empty")

    await set_user_api_key(session, user_id, p, request.api_key.strip())
    hint = mask_api_key(request.api_key.strip())
    return ApiKeySetResponse(provider=p.value, key_hint=hint, status="ok")


@router.get(
    "",
    response_model=ApiKeyListResponse,
)
async def list_api_keys(
    user_id: str = Depends(require_user_id),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyListResponse:
    """List configured providers with masked key hints."""
    records = await list_user_api_keys(session, user_id)
    keys = []
    for record in records:
        plaintext = decrypt_api_key(record.encrypted_key, record.salt)
        keys.append(
            ApiKeyInfo(
                provider=record.provider.value,
                key_hint=mask_api_key(plaintext),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return ApiKeyListResponse(keys=keys)


@router.delete(
    "/{provider}",
    response_model=ApiKeyDeleteResponse,
)
async def delete_api_key(
    provider: str,
    user_id: str = Depends(require_user_id),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyDeleteResponse:
    """Delete a stored API key for a provider."""
    p = _validate_provider(provider)
    deleted = await delete_user_api_key(session, user_id, p)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"No API key configured for provider {provider}",
        )
    return ApiKeyDeleteResponse(provider=p.value, status="deleted")
