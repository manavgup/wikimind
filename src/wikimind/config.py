"""Application settings via Pydantic BaseSettings with environment variable binding.

Environment variables are the primary configuration source. A `.env` file is loaded
automatically when present. API keys are stored in the OS keychain via keyring and
can be overridden by environment variables (e.g. for CI/CD).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import keyring
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KEYRING_SERVICE = "wikimind"
DEFAULT_DATA_DIR = Path.home() / ".wikimind"


class LLMProviderConfig(BaseModel):
    """LLM provider configuration."""

    model: str
    enabled: bool = False


class LLMConfig(BaseModel):
    """LLM configuration across providers."""

    default_provider: str = "anthropic"
    fallback_enabled: bool = True
    monthly_budget_usd: float = 50.0
    anthropic: LLMProviderConfig = LLMProviderConfig(model="claude-sonnet-4-5", enabled=True)
    openai: LLMProviderConfig = LLMProviderConfig(model="gpt-4o", enabled=False)
    google: LLMProviderConfig = LLMProviderConfig(model="gemini-2.0-flash", enabled=False)
    ollama: LLMProviderConfig = LLMProviderConfig(model="llama3.2", enabled=False)
    ollama_base_url: str = "http://localhost:11434"


class SyncConfig(BaseModel):
    """Cloud sync configuration."""

    enabled: bool = False
    interval_minutes: int = 15
    bucket: str | None = None
    region: str = "auto"
    endpoint_url: str | None = None


class DatabaseConfig(BaseModel):
    """Database configuration."""

    echo: bool = False


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = "127.0.0.1"
    port: int = 7842


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="WIKIMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: str = str(DEFAULT_DATA_DIR)
    gateway_port: int = 7842

    llm: LLMConfig = LLMConfig()
    sync: SyncConfig = SyncConfig()
    database: DatabaseConfig = DatabaseConfig()
    server: ServerConfig = ServerConfig()

    # API keys — SecretStr prevents accidental logging
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None

    @property
    def wiki_dir(self) -> Path:
        """Return wiki directory path."""
        return Path(self.data_dir) / "wiki"

    @property
    def raw_dir(self) -> Path:
        """Return raw data directory path."""
        return Path(self.data_dir) / "raw"

    @property
    def db_dir(self) -> Path:
        """Return database directory path."""
        return Path(self.data_dir) / "db"

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        for d in [self.wiki_dir, self.raw_dir, self.db_dir, Path(self.data_dir) / "config"]:
            d.mkdir(parents=True, exist_ok=True)

    def get_security_status(self) -> dict[str, object]:
        """Return a summary of which API keys and security features are configured.

        Useful for production readiness checks.
        """
        return {
            "anthropic_api_key": self.anthropic_api_key is not None
            or bool(keyring.get_password(KEYRING_SERVICE, "anthropic")),
            "openai_api_key": self.openai_api_key is not None or bool(keyring.get_password(KEYRING_SERVICE, "openai")),
            "google_api_key": self.google_api_key is not None or bool(keyring.get_password(KEYRING_SERVICE, "google")),
            "keyring_backend": type(keyring.get_keyring()).__name__,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and return application settings (cached singleton)."""
    settings = Settings()
    settings.ensure_dirs()
    return settings


# ---------------------------------------------------------------------------
# API Key management — env vars first, then OS keychain
# ---------------------------------------------------------------------------

_ENV_MAP: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google": "google_api_key",
    "aws_access_key": "aws_access_key_id",
    "aws_secret_key": "aws_secret_access_key",
}


def get_api_key(provider: str) -> str | None:
    """Retrieve API key from environment / settings or OS keychain.

    Priority: env var (via Settings SecretStr) -> keychain.
    """
    settings = get_settings()

    # Check Settings field (populated from env vars / .env)
    attr = _ENV_MAP.get(provider)
    if attr:
        secret: SecretStr | None = getattr(settings, attr, None)
        if secret is not None:
            return secret.get_secret_value()

    # Also check raw env vars for non-prefixed names (CI/CD compatibility)
    raw_env_map: dict[str, str] = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "aws_access_key": "AWS_ACCESS_KEY_ID",
        "aws_secret_key": "AWS_SECRET_ACCESS_KEY",
    }
    env_var = raw_env_map.get(provider)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val:
            return env_val

    # Fall back to keychain
    return keyring.get_password(KEYRING_SERVICE, provider)


def set_api_key(provider: str, key: str) -> None:
    """Store API key in OS keychain."""
    keyring.set_password(KEYRING_SERVICE, provider, key)


def delete_api_key(provider: str) -> None:
    """Remove API key from OS keychain."""
    keyring.delete_password(KEYRING_SERVICE, provider)
