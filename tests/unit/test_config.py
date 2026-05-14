"""Tests for the BaseSettings config — auto-enable, nested env vars, .env loading."""

import keyring
import pytest
from pydantic import ValidationError

from wikimind.config import AuthConfig, Settings, _reconcile_providers, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Force get_settings() to re-read on every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_keyring(monkeypatch):
    """Stub keyring so tests don't touch the real OS keychain."""
    monkeypatch.setattr(keyring, "get_password", lambda *_args, **_kwargs: None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Strip any WIKIMIND_/_API_KEY env vars that could leak into tests."""
    for key in list(__import__("os").environ.keys()):
        if key.startswith("WIKIMIND_") or key.endswith("_API_KEY"):
            monkeypatch.delenv(key, raising=False)


class TestNestedEnvVars:
    """Verify the env_nested_delimiter='__' machinery works with the new factories."""

    def test_default_provider_is_anthropic(self, monkeypatch):
        monkeypatch.delenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL", raising=False)
        monkeypatch.delenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__MODEL", raising=False)
        monkeypatch.delenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__ENABLED", raising=False)
        s = Settings()
        assert s.llm.default_provider == "anthropic"
        assert s.llm.openai.model == "gpt-4o"  # default preserved
        assert s.llm.openai.enabled is False
        assert s.llm.openai_compatible.base_url == ""
        assert s.llm.openai_compatible.supports_reasoning_effort is True
        assert s.llm.openai_compatible.reasoning_format == "openai"

    def test_nested_env_var_override(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_LLM__DEFAULT_PROVIDER", "openai")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI__ENABLED", "true")
        s = Settings()
        assert s.llm.default_provider == "openai"
        assert s.llm.openai.enabled is True
        # Critical: model default preserved across the partial override
        assert s.llm.openai.model == "gpt-4o"

    def test_nested_env_var_model_override(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI__MODEL", "gpt-4o-mini")
        s = Settings()
        assert s.llm.openai.model == "gpt-4o-mini"

    def test_openai_compatible_nested_env_vars(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL", "https://openrouter.ai/api/v1")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__MODEL", "openai/gpt-4o-mini")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__SUPPORTS_STREAM_USAGE", "false")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__SUPPORTS_REASONING_EFFORT", "false")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__REASONING_FORMAT", "openrouter")
        s = Settings()
        assert s.llm.openai_compatible.base_url == "https://openrouter.ai/api/v1"
        assert s.llm.openai_compatible.model == "openai/gpt-4o-mini"
        assert s.llm.openai_compatible.supports_stream_usage is False
        assert s.llm.openai_compatible.supports_reasoning_effort is False
        assert s.llm.openai_compatible.reasoning_format == "openrouter"


class TestAutoEnableProviders:
    """A provider whose API key is set should auto-enable on Settings init."""

    def test_openai_auto_enables_with_unprefixed_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.openai.enabled is True

    def test_openai_auto_enables_with_prefixed_key(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_OPENAI_API_KEY", "sk-test-456")
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.openai.enabled is True
        assert s.openai_api_key is not None
        assert s.openai_api_key.get_secret_value() == "sk-test-456"

    def test_anthropic_disabled_when_no_key(self):
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.anthropic.enabled is False

    def test_google_auto_enables_with_key(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.google.enabled is True

    def test_openai_compatible_auto_enables_with_key_and_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "openrouter-test")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL", "https://openrouter.ai/api/v1")
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.openai_compatible.enabled is True

    def test_openai_compatible_does_not_auto_enable_without_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "openrouter-test")
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.openai_compatible.enabled is False

    def test_no_auto_enable_when_no_keys(self):
        s = Settings()
        _reconcile_providers(s)
        assert s.llm.anthropic.enabled is False
        assert s.llm.openai.enabled is False
        assert s.llm.openai_compatible.enabled is False
        assert s.llm.google.enabled is False
        assert s.llm.ollama.enabled is False

    def test_explicit_false_overrides_auto_enable(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI__ENABLED", "false")
        s = Settings()
        _reconcile_providers(s)
        # Auto-enable wins because the key is present
        assert s.llm.openai.enabled is True


class TestSecurityStatus:
    """Verify the security audit helper still works after the refactor."""

    def test_security_status_no_keys(self):
        s = Settings()
        status = s.get_security_status()
        assert status["anthropic_api_key"] is False
        assert status["openai_api_key"] is False
        assert status["openai_compatible_api_key"] is False
        assert status["google_api_key"] is False
        assert "keyring_backend" in status

    def test_security_status_with_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        s = Settings()
        status = s.get_security_status()
        assert status["openai_api_key"] is True
        assert status["anthropic_api_key"] is False


class TestKeyringBackendMissing:
    """Settings instantiation must survive a missing keyring backend.

    Linux CI runners typically have no usable keyring backend (no
    secret-service, no GNOME keyring, no KWallet). Calling
    `keyring.get_password()` raises `NoKeyringError` in that case.
    The auto-enable validator must treat this as 'no key stored'
    instead of crashing the entire Settings load.
    """

    def test_settings_loads_when_keyring_raises(self, monkeypatch):
        def raise_no_keyring(*_args, **_kwargs):
            raise keyring.errors.NoKeyringError("No recommended backend was available")

        monkeypatch.setattr(keyring, "get_password", raise_no_keyring)
        # Should NOT raise — keyring failure is silently caught
        s = Settings()
        _reconcile_providers(s)
        # Without any env vars set, no providers should auto-enable
        assert s.llm.openai.enabled is False
        assert s.llm.google.enabled is False

    def test_env_var_still_works_when_keyring_raises(self, monkeypatch):
        def raise_no_keyring(*_args, **_kwargs):
            raise keyring.errors.NoKeyringError("No recommended backend was available")

        monkeypatch.setattr(keyring, "get_password", raise_no_keyring)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        s = Settings()
        _reconcile_providers(s)
        # Env var path bypasses keyring entirely — auto-enable still works
        assert s.llm.openai.enabled is True

    def test_get_security_status_handles_keyring_failure(self, monkeypatch):
        def raise_no_keyring(*_args, **_kwargs):
            raise keyring.errors.NoKeyringError("No recommended backend was available")

        monkeypatch.setattr(keyring, "get_password", raise_no_keyring)
        s = Settings()
        # Should not raise when computing the security audit summary
        status = s.get_security_status()
        assert status["openai_api_key"] is False
        assert status["anthropic_api_key"] is False


class TestRedisUrlConfig:
    """Verify redis_url reads WIKIMIND_REDIS_URL first, falls back to REDIS_URL.

    Neither the autouse `_clean_env` fixture (which only clears `WIKIMIND_*`
    and `*_API_KEY`) nor the hermetic session fixture touches `REDIS_URL`,
    so each test clears the raw form explicitly to avoid CI env leakage.
    """

    def test_redis_url_default_none(self, monkeypatch):
        """No env vars → None (dev mode, in-process compilation)."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        s = Settings()
        assert s.redis_url is None

    def test_redis_url_from_prefixed_env(self, monkeypatch):
        """WIKIMIND_REDIS_URL is read via the standard env_prefix path."""
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("WIKIMIND_REDIS_URL", "redis://compose:6379/0")
        s = Settings()
        assert s.redis_url == "redis://compose:6379/0"

    def test_redis_url_from_raw_env(self, monkeypatch):
        """REDIS_URL (unprefixed) is read as a fallback — CI/CD + ADR-002."""
        monkeypatch.delenv("WIKIMIND_REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://ci:6379/1")
        s = Settings()
        assert s.redis_url == "redis://ci:6379/1"

    def test_redis_url_prefixed_wins_over_raw(self, monkeypatch):
        """When both are set, the prefixed form wins (explicit > fallback)."""
        monkeypatch.setenv("WIKIMIND_REDIS_URL", "redis://prefixed:6379/0")
        monkeypatch.setenv("REDIS_URL", "redis://raw:6379/0")
        s = Settings()
        assert s.redis_url == "redis://prefixed:6379/0"


class TestDatabaseUrlRewrite:
    """Config rewrites scheme but passes sslmode through (database.py handles SSL)."""

    def test_scheme_rewritten_postgres(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
        s = Settings()
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_scheme_rewritten_postgresql(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
        s = Settings()
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_sslmode_passes_through(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db?sslmode=disable")
        s = Settings()
        assert "sslmode=disable" in s.database_url
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_query_params_preserved(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db?sslmode=require&application_name=test")
        s = Settings()
        assert "application_name=test" in s.database_url
        assert "sslmode=require" in s.database_url

    def test_no_rewrite_when_already_postgresql(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_DATABASE_URL", "postgresql+asyncpg://u:p@host/db")
        monkeypatch.setenv("DATABASE_URL", "postgres://other:x@other/other")
        s = Settings()
        assert s.database_url == "postgresql+asyncpg://u:p@host/db"

    def test_sqlite_default_when_no_env(self):
        s = Settings()
        assert "sqlite+aiosqlite" in s.database_url


class TestAuthConfigJwtSecret:
    """AuthConfig must reject empty jwt_secret_key when auth is enabled (#656)."""

    def test_rejects_empty_secret_when_enabled(self):
        """An empty secret with auth enabled is an auth bypass — must fail."""
        with pytest.raises(ValidationError, match="jwt_secret_key must not be empty"):
            AuthConfig(enabled=True, jwt_secret_key="")

    def test_accepts_real_secret_when_enabled(self):
        """A non-empty secret with auth enabled is valid."""
        cfg = AuthConfig(enabled=True, jwt_secret_key="real-secret")
        assert cfg.jwt_secret_key == "real-secret"
        assert cfg.enabled is True

    def test_allows_empty_secret_when_disabled(self):
        """Auth disabled + empty secret is fine — no tokens are verified."""
        cfg = AuthConfig(enabled=False, jwt_secret_key="")
        assert cfg.enabled is False
        assert cfg.jwt_secret_key == ""
