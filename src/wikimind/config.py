"""Application settings loaded from TOML config and environment variables.

Non-sensitive settings live in ~/.wikimind/config/settings.toml.
API keys are stored in the OS keychain via keyring — never in config files.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import keyring
import toml
from pydantic import BaseModel

KEYRING_SERVICE = "wikimind"
DEFAULT_DATA_DIR = Path.home() / ".wikimind"
DEFAULT_CONFIG_PATH = DEFAULT_DATA_DIR / "config" / "settings.toml"


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
    region: str = "auto"  # Cloudflare R2 default
    endpoint_url: str | None = None  # R2 endpoint


class Settings(BaseModel):
    """Application settings."""

    data_dir: str = str(DEFAULT_DATA_DIR)
    gateway_port: int = 7842
    llm: LLMConfig = LLMConfig()
    sync: SyncConfig = SyncConfig()

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

    def ensure_dirs(self):
        """Create all required directories."""
        for d in [self.wiki_dir, self.raw_dir, self.db_dir, Path(self.data_dir) / "config"]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and return application settings."""
    config_path = Path(os.environ.get("WIKIMIND_CONFIG", DEFAULT_CONFIG_PATH))

    if config_path.exists():
        raw = toml.load(config_path)
        return Settings(**raw)

    # First run — create default config
    settings = Settings()
    settings.ensure_dirs()
    _write_default_config(config_path, settings)
    return settings


def _write_default_config(path: Path, settings: Settings):
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "data_dir": settings.data_dir,
        "gateway_port": settings.gateway_port,
        "llm": {
            "default_provider": "anthropic",
            "fallback_enabled": True,
            "monthly_budget_usd": 50.0,
            "anthropic": {"model": "claude-sonnet-4-5", "enabled": True},
            "openai": {"model": "gpt-4o", "enabled": False},
            "google": {"model": "gemini-2.0-flash", "enabled": False},
            "ollama": {"model": "llama3.2", "enabled": False},
            "ollama_base_url": "http://localhost:11434",
        },
        "sync": {
            "enabled": False,
            "interval_minutes": 15,
        },
    }
    with open(path, "w") as f:
        toml.dump(config, f)


# ---------------------------------------------------------------------------
# API Key management — OS keychain only, never config files
# ---------------------------------------------------------------------------


def get_api_key(provider: str) -> str | None:
    """Retrieve API key from OS keychain."""
    # Check env var first (for CI/CD)
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "aws_access_key": "AWS_ACCESS_KEY_ID",
        "aws_secret_key": "AWS_SECRET_ACCESS_KEY",
    }
    if provider in env_map:
        env_val = os.environ.get(env_map[provider])
        if env_val:
            return env_val

    # Fall back to keychain
    return keyring.get_password(KEYRING_SERVICE, provider)


def set_api_key(provider: str, key: str):
    """Store API key in OS keychain."""
    keyring.set_password(KEYRING_SERVICE, provider, key)


def delete_api_key(provider: str):
    """Remove API key from OS keychain."""
    keyring.delete_password(KEYRING_SERVICE, provider)
