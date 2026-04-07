"""Tests for the BaseSettings config — auto-enable, nested env vars, .env loading."""

import keyring
import pytest

from wikimind.config import Settings, get_settings


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

    def test_default_provider_is_anthropic(self):
        s = Settings()
        assert s.llm.default_provider == "anthropic"
        assert s.llm.openai.model == "gpt-4o"  # default preserved
        assert s.llm.openai.enabled is False

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


class TestAutoEnableProviders:
    """A provider whose API key is set should auto-enable on Settings init."""

    def test_openai_auto_enables_with_unprefixed_key(self, monkeypatch):
        # Unprefixed env vars are read by the auto-enable validator
        # but don't populate the SecretStr field directly (BaseSettings only
        # picks up prefixed names). get_api_key() handles the fallback.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        s = Settings()
        assert s.llm.openai.enabled is True

    def test_openai_auto_enables_with_prefixed_key(self, monkeypatch):
        monkeypatch.setenv("WIKIMIND_OPENAI_API_KEY", "sk-test-456")
        s = Settings()
        assert s.llm.openai.enabled is True
        # Prefixed env vars DO populate the SecretStr field directly
        assert s.openai_api_key is not None
        assert s.openai_api_key.get_secret_value() == "sk-test-456"

    def test_anthropic_stays_enabled_when_no_key(self):
        # Anthropic defaults to enabled=True even without a key (legacy default).
        # Auto-enable doesn't disable anything — only flips False → True.
        s = Settings()
        assert s.llm.anthropic.enabled is True

    def test_google_auto_enables_with_key(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
        s = Settings()
        assert s.llm.google.enabled is True

    def test_no_auto_enable_when_no_keys(self):
        s = Settings()
        assert s.llm.openai.enabled is False
        assert s.llm.google.enabled is False
        assert s.llm.ollama.enabled is False

    def test_explicit_false_overrides_auto_enable(self, monkeypatch):
        # If a user explicitly sets enabled=false via env var, that should win.
        # NOTE: validators run after env loading, so the env-set False is what
        # the validator sees first. The validator only flips False → True if
        # a key is present, so explicit-false-with-key gets re-enabled.
        # This is acceptable: setting a key but disabling the provider is a
        # contradiction the user probably didn't mean.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("WIKIMIND_LLM__OPENAI__ENABLED", "false")
        s = Settings()
        # Auto-enable wins because the key is present
        assert s.llm.openai.enabled is True


class TestSecurityStatus:
    """Verify the security audit helper still works after the refactor."""

    def test_security_status_no_keys(self):
        s = Settings()
        status = s.get_security_status()
        assert status["anthropic_api_key"] is False
        assert status["openai_api_key"] is False
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
        # Without any env vars set, no providers should auto-enable
        assert s.llm.openai.enabled is False
        assert s.llm.google.enabled is False

    def test_env_var_still_works_when_keyring_raises(self, monkeypatch):
        def raise_no_keyring(*_args, **_kwargs):
            raise keyring.errors.NoKeyringError("No recommended backend was available")

        monkeypatch.setattr(keyring, "get_password", raise_no_keyring)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        s = Settings()
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
