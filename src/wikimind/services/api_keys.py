"""BYOK API key management — encrypt, decrypt, CRUD operations.

Encrypts user-provided LLM API keys at rest using Fernet symmetric
encryption.  The Fernet key is derived from ``JWT_SECRET_KEY`` +
a per-row random salt via PBKDF2-HMAC-SHA256.  See ADR-026.
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, NamedTuple

import structlog
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.models import Provider, UserApiKey

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

# PBKDF2 iteration count — balances security vs. latency for per-request
# key derivation.  100_000 is the OWASP 2023 minimum for SHA-256.
PBKDF2_ITERATIONS = 100_000


def _derive_fernet_key(salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from JWT_SECRET_KEY and a per-row salt."""
    settings = get_settings()
    secret = settings.auth.jwt_secret_key
    if not secret:
        msg = (
            "JWT_SECRET_KEY must be configured for BYOK encryption. "
            "Set WIKIMIND_AUTH__JWT_SECRET_KEY in your environment."
        )
        raise ValueError(msg)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


class EncryptedApiKey(NamedTuple):
    """Result of encrypting an API key."""

    encrypted_key: str
    salt_hex: str


def encrypt_api_key(plaintext: str) -> EncryptedApiKey:
    """Encrypt an API key, returning (encrypted_key, salt_hex).

    Args:
        plaintext: The raw API key to encrypt.

    Returns:
        EncryptedApiKey with Fernet-encrypted key and salt hex string.
    """
    salt = os.urandom(16)
    fernet_key = _derive_fernet_key(salt)
    f = Fernet(fernet_key)
    encrypted = f.encrypt(plaintext.encode())
    return EncryptedApiKey(encrypted.decode(), salt.hex())


def decrypt_api_key(encrypted_key: str, salt_hex: str) -> str:
    """Decrypt an API key.

    Args:
        encrypted_key: Fernet-encrypted key (base64 string).
        salt_hex: Hex-encoded salt used during encryption.

    Returns:
        The decrypted plaintext API key.
    """
    salt = bytes.fromhex(salt_hex)
    fernet_key = _derive_fernet_key(salt)
    f = Fernet(fernet_key)
    return f.decrypt(encrypted_key.encode()).decode()


def mask_api_key(key: str) -> str:
    """Return a masked hint of the API key (first 4 + last 4 chars).

    Args:
        key: The plaintext API key.

    Returns:
        A masked string like "sk-p...xyz1".
    """
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


async def set_user_api_key(
    session: AsyncSession,
    user_id: str,
    provider: Provider,
    api_key: str,
) -> UserApiKey:
    """Store or update a user's API key for a provider.

    Args:
        session: Database session.
        user_id: The user's ID.
        provider: LLM provider enum value.
        api_key: Plaintext API key to encrypt and store.

    Returns:
        The created or updated UserApiKey record.
    """
    encrypted_key, salt_hex = encrypt_api_key(api_key)

    result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider.name,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.encrypted_key = encrypted_key
        existing.salt = salt_hex
        existing.updated_at = utcnow_naive()
        session.add(existing)
        log.info("user API key updated", user_id=user_id, provider=provider)
        return existing

    record = UserApiKey(
        user_id=user_id,
        provider=provider,
        encrypted_key=encrypted_key,
        salt=salt_hex,
    )
    session.add(record)
    log.info("user API key stored", user_id=user_id, provider=provider)
    return record


async def get_user_api_key(
    session: AsyncSession,
    user_id: str,
    provider: Provider,
) -> str | None:
    """Retrieve and decrypt a user's API key for a provider.

    Args:
        session: Database session.
        user_id: The user's ID.
        provider: LLM provider enum value.

    Returns:
        The decrypted API key, or None if not configured.
    """
    result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider.name,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return None
    return decrypt_api_key(record.encrypted_key, record.salt)


async def list_user_api_keys(
    session: AsyncSession,
    user_id: str,
) -> list[UserApiKey]:
    """List all configured API key providers for a user (no decryption).

    Args:
        session: Database session.
        user_id: The user's ID.

    Returns:
        List of UserApiKey records (encrypted_key is NOT decrypted).
    """
    result = await session.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))
    return list(result.scalars().all())


async def delete_user_api_key(
    session: AsyncSession,
    user_id: str,
    provider: Provider,
) -> bool:
    """Delete a user's API key for a provider.

    Args:
        session: Database session.
        user_id: The user's ID.
        provider: LLM provider enum value.

    Returns:
        True if a key was deleted, False if none existed.
    """
    result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.provider == provider.name,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return False
    await session.delete(record)
    log.info("user API key deleted", user_id=user_id, provider=provider)
    return True
