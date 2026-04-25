"""Tests for BYOK API key management (issue #247)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wikimind.config import get_settings
from wikimind.models import Provider
from wikimind.services.api_keys import (
    decrypt_api_key,
    delete_user_api_key,
    encrypt_api_key,
    get_user_api_key,
    list_user_api_keys,
    mask_api_key,
    set_user_api_key,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Unit tests — encryption helpers
# ---------------------------------------------------------------------------


class TestEncryption:
    """Test encrypt/decrypt round-trip and masking."""

    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        """Encrypting then decrypting returns the original key."""
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "test-secret-key-for-byok")
        get_settings.cache_clear()
        try:
            original = "sk-ant-api03-xxxxxxxxxxxxxxxxxxxx"
            encrypted, salt_hex = encrypt_api_key(original)
            decrypted = decrypt_api_key(encrypted, salt_hex)
            assert decrypted == original
        finally:
            get_settings.cache_clear()

    def test_different_salts_produce_different_ciphertexts(self, monkeypatch):
        """Each encryption should use a unique salt."""
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "test-secret-key-for-byok")
        get_settings.cache_clear()
        try:
            key = "sk-test-key-12345"
            encrypted1, salt1 = encrypt_api_key(key)
            encrypted2, salt2 = encrypt_api_key(key)
            assert salt1 != salt2
            assert encrypted1 != encrypted2
            # But both decrypt to the same value
            assert decrypt_api_key(encrypted1, salt1) == key
            assert decrypt_api_key(encrypted2, salt2) == key
        finally:
            get_settings.cache_clear()

    def test_mask_api_key_long(self):
        """Long keys show first 4 and last 4 chars."""
        assert mask_api_key("sk-ant-api03-xxxxxxxxxxxxxxxxxxxx") == "sk-a...xxxx"

    def test_mask_api_key_short(self):
        """Short keys are fully masked."""
        assert mask_api_key("abc") == "****"
        assert mask_api_key("12345678") == "****"

    def test_mask_api_key_nine_chars(self):
        """9-char keys show first 4 and last 4."""
        assert mask_api_key("123456789") == "1234...6789"


# ---------------------------------------------------------------------------
# Unit tests — service layer CRUD
# ---------------------------------------------------------------------------


class TestServiceCRUD:
    """Test set/get/list/delete operations on UserApiKey."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "test-secret-key-for-byok")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_set_and_get(self, db_session: AsyncSession):
        """Setting a key then getting it returns the original."""
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "sk-test-123")
        await db_session.commit()

        result = await get_user_api_key(db_session, "user-1", Provider.ANTHROPIC)
        assert result == "sk-test-123"

    async def test_get_nonexistent(self, db_session: AsyncSession):
        """Getting a key that doesn't exist returns None."""
        result = await get_user_api_key(db_session, "user-1", Provider.OPENAI)
        assert result is None

    async def test_update_existing(self, db_session: AsyncSession):
        """Setting a key twice updates the existing record."""
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "old-key")
        await db_session.commit()
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "new-key")
        await db_session.commit()

        result = await get_user_api_key(db_session, "user-1", Provider.ANTHROPIC)
        assert result == "new-key"

    async def test_list_keys(self, db_session: AsyncSession):
        """Listing returns all configured providers for a user."""
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "key-a")
        await set_user_api_key(db_session, "user-1", Provider.OPENAI, "key-b")
        await db_session.commit()

        records = await list_user_api_keys(db_session, "user-1")
        providers = {r.provider for r in records}
        assert providers == {Provider.ANTHROPIC, Provider.OPENAI}

    async def test_list_isolation(self, db_session: AsyncSession):
        """Listing only returns keys for the specified user."""
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "key-a")
        await set_user_api_key(db_session, "user-2", Provider.OPENAI, "key-b")
        await db_session.commit()

        records = await list_user_api_keys(db_session, "user-1")
        assert len(records) == 1
        assert records[0].provider == Provider.ANTHROPIC

    async def test_delete(self, db_session: AsyncSession):
        """Deleting a key removes it."""
        await set_user_api_key(db_session, "user-1", Provider.ANTHROPIC, "key-a")
        await db_session.commit()

        deleted = await delete_user_api_key(db_session, "user-1", Provider.ANTHROPIC)
        assert deleted is True
        await db_session.commit()

        result = await get_user_api_key(db_session, "user-1", Provider.ANTHROPIC)
        assert result is None

    async def test_delete_nonexistent(self, db_session: AsyncSession):
        """Deleting a nonexistent key returns False."""
        deleted = await delete_user_api_key(db_session, "user-1", Provider.GOOGLE)
        assert deleted is False


# ---------------------------------------------------------------------------
# Integration tests — API routes (single-request per test)
# ---------------------------------------------------------------------------


class TestAPIRoutes:
    """Test BYOK API endpoints via the test client.

    Each test exercises a single endpoint. Cross-request state is NOT
    guaranteed by the test client override of ``get_session`` (the override
    does not commit), so each test is self-contained.
    """

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "test-secret-key-for-byok")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_set_key(self, client: AsyncClient):
        """PUT /api/settings/api-keys/{provider} stores a key."""
        resp = await client.put(
            "/api/settings/api-keys/anthropic",
            json={"api_key": "sk-ant-test-1234567890abcdef"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"
        assert data["status"] == "ok"
        assert "sk-a" in data["key_hint"]
        assert "cdef" in data["key_hint"]

    async def test_list_keys_empty(self, client: AsyncClient):
        """GET /api/settings/api-keys returns empty list when none configured."""
        resp = await client.get("/api/settings/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"] == []

    async def test_delete_nonexistent(self, client: AsyncClient):
        """DELETE for a non-configured provider returns 404."""
        resp = await client.delete("/api/settings/api-keys/google")
        assert resp.status_code == 404

    async def test_invalid_provider(self, client: AsyncClient):
        """PUT with an invalid provider returns 400."""
        resp = await client.put(
            "/api/settings/api-keys/invalid",
            json={"api_key": "some-key"},
        )
        assert resp.status_code == 400

    async def test_ollama_rejected(self, client: AsyncClient):
        """PUT for ollama (no API key needed) returns 400."""
        resp = await client.put(
            "/api/settings/api-keys/ollama",
            json={"api_key": "some-key"},
        )
        assert resp.status_code == 400

    async def test_empty_key_rejected(self, client: AsyncClient):
        """PUT with an empty key returns 400."""
        resp = await client.put(
            "/api/settings/api-keys/anthropic",
            json={"api_key": "   "},
        )
        assert resp.status_code == 400

    async def test_mock_rejected(self, client: AsyncClient):
        """PUT for mock (no API key needed) returns 400."""
        resp = await client.put(
            "/api/settings/api-keys/mock",
            json={"api_key": "some-key"},
        )
        assert resp.status_code == 400

    async def test_set_key_without_jwt_secret(self, client: AsyncClient, monkeypatch):
        """PUT returns 500 with descriptive error when JWT_SECRET_KEY is missing."""
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "")
        get_settings.cache_clear()
        try:
            resp = await client.put(
                "/api/settings/api-keys/openai",
                json={"api_key": "sk-test-key-1234"},  # pragma: allowlist secret
            )
            assert resp.status_code == 500
            assert "JWT_SECRET_KEY" in resp.json()["detail"]
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Settings "configured" status — BYOK keys show as configured
# ---------------------------------------------------------------------------


class TestProviderConfiguredStatus:
    """GET /settings reflects BYOK database keys in provider configured status."""

    @pytest.fixture(autouse=True)
    def _set_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_AUTH__JWT_SECRET_KEY", "test-secret-key-for-byok")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    async def test_provider_configured_with_env_var(self, client: AsyncClient, monkeypatch):
        """Provider shows configured when an env var API key is set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        get_settings.cache_clear()
        try:
            resp = await client.get("/settings")
            assert resp.status_code == 200
            providers = resp.json()["llm"]["providers"]
            assert providers["anthropic"]["configured"] is True
        finally:
            get_settings.cache_clear()

    async def test_provider_not_configured_by_default(self, client: AsyncClient):
        """Provider shows not configured when no key exists."""
        resp = await client.get("/settings")
        assert resp.status_code == 200
        providers = resp.json()["llm"]["providers"]
        # OpenAI has no env var set in test → not configured
        assert providers["openai"]["configured"] is False
