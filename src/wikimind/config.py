"""Application settings via Pydantic BaseSettings with environment variable binding.

Environment variables are the primary configuration source. A `.env` file is loaded
automatically when present. API keys are stored in the OS keychain via keyring and
can be overridden by environment variables (e.g. for CI/CD).

Nested settings use the `__` delimiter — e.g. ``WIKIMIND_LLM__OPENAI__ENABLED=true``
sets ``settings.llm.openai.enabled``. The provider config classes use class-level
defaults so that partial overrides preserve unset fields.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import keyring
import keyring.errors
import structlog
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger()

KEYRING_SERVICE = "wikimind"
DEFAULT_DATA_DIR = Path.home() / ".wikimind"


def _safe_keyring_get(provider: str) -> str | None:
    """Read a key from the OS keychain, returning None on any failure.

    Linux CI runners often lack a configured keyring backend (no
    secret-service, no GNOME keyring, no KWallet), which causes
    `keyring.get_password()` to raise `NoKeyringError`. We treat that
    case the same as "no key stored" so Settings instantiation never
    crashes for environments that don't use the keychain.
    """
    try:
        return keyring.get_password(KEYRING_SERVICE, provider)
    except keyring.errors.KeyringError:
        return None


class LLMProviderConfig(BaseModel):
    """Base provider configuration. Subclasses set the default model per provider."""

    model: str = ""
    enabled: bool = False


class AnthropicConfig(LLMProviderConfig):
    """Anthropic provider defaults."""

    model: str = "claude-sonnet-4-5"
    enabled: bool = True


class OpenAIConfig(LLMProviderConfig):
    """OpenAI provider defaults."""

    model: str = "gpt-4o"
    enabled: bool = False


class GoogleConfig(LLMProviderConfig):
    """Google Gemini provider defaults."""

    model: str = "gemini-2.0-flash"
    enabled: bool = False


class OllamaConfig(LLMProviderConfig):
    """Local Ollama provider defaults."""

    model: str = "llama3.2"
    enabled: bool = False


class MockConfig(LLMProviderConfig):
    """Deterministic mock provider for CI and local e2e testing.

    Never returns a real LLM call. Must be explicitly enabled and
    must be set as the default provider to be selected. Disabled
    by default so it can never silently intercept real traffic.
    """

    model: str = "mock-1"
    enabled: bool = False


class LLMConfig(BaseModel):
    """LLM configuration across providers."""

    default_provider: str = "anthropic"
    fallback_enabled: bool = True
    monthly_budget_usd: float = 50.0
    budget_warning_pct: float = 0.8
    budget_check_cache_seconds: int = 60
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    ollama_base_url: str = "http://localhost:11434"
    mock: MockConfig = Field(default_factory=MockConfig)


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


class QAConfig(BaseModel):
    """Q&A agent configuration — controls multi-turn conversation behavior."""

    max_prior_turns_in_context: int = 5
    prior_answer_truncate_chars: int = 500
    conversation_title_max_chars: int = 120


class TaxonomyConfig(BaseModel):
    """Concept taxonomy configuration."""

    rebuild_threshold: int = 5
    max_hierarchy_depth: int = 3
    concept_page_min_sources: int = 2


class LinterConfig(BaseModel):
    """Wiki linter configuration."""

    enable_orphan_detection: bool = True
    max_concepts_per_run: int = 25
    max_contradiction_pairs_per_concept: int = 10
    contradiction_llm_max_tokens: int = 1024
    contradiction_llm_temperature: float = 0.2
    enable_pair_cache: bool = True
    contradiction_batch_enabled: bool = True
    contradiction_batch_size: int = 10


class EmbeddingConfig(BaseModel):
    """Embedding and semantic search configuration."""

    model_name: str = "all-MiniLM-L6-v2"
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 50
    min_similarity_score: float = 0.65


class AuthConfig(BaseModel):
    """OAuth2 authentication configuration."""

    enabled: bool = False
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None


# Mapping from provider name → (Settings field for SecretStr key, raw env var name).
# Used by both `get_api_key` and the auto-enable validator below.
_PROVIDER_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "google": ("google_api_key", "GOOGLE_API_KEY"),
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="WIKIMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data_dir: str = str(DEFAULT_DATA_DIR)

    # Database URL — defaults to SQLite in data_dir. Set to a Postgres URL
    # (postgresql+asyncpg://...) for production. See ADR-021.
    database_url: str = ""

    gateway_port: int = 7842

    # Redis URL for the ARQ job queue. When unset, BackgroundCompiler runs
    # compilations in-process (single-user dev mode) and the ARQ worker
    # falls back to localhost (which will fail to connect unless a local
    # Redis is actually running).
    #
    # Read from WIKIMIND_REDIS_URL via env_prefix. Falls back to the raw
    # REDIS_URL env var in `_fallback_redis_url` below — same dual-read
    # pattern used for API keys, for CI/CD and ADR-002 compatibility.
    redis_url: str | None = None

    llm: LLMConfig = Field(default_factory=LLMConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    qa: QAConfig = Field(default_factory=QAConfig)
    taxonomy: TaxonomyConfig = Field(default_factory=TaxonomyConfig)
    linter: LinterConfig = Field(default_factory=LinterConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # PDF extraction: number of pages per Docling batch (issue #117).
    # Smaller values give more frequent progress updates at the cost of
    # slightly higher overhead from repeated converter calls.
    docling_batch_pages: int = 10

    # Vision-enhanced slide deck ingestion (issue #68).
    # Pages with fewer characters than the threshold are treated as
    # image-heavy (diagrams, charts, cover slides) and sent to the
    # multimodal LLM for description. Set vision_enabled=False to
    # disable the feature entirely (kill switch).
    vision_enabled: bool = True
    vision_text_threshold: int = 300
    vision_dpi: int = 150
    vision_max_pages_per_batch: int = 20

    # Image extraction from PDFs (issue #142).
    # Docling PictureItem/TableItem extraction, served via /images/ endpoint.
    # Frontend FiguresPanel displays them alongside the article.
    image_extraction_enabled: bool = True
    image_max_per_pdf: int = 30
    image_base_url: str = "/images"

    # API keys — SecretStr prevents accidental logging
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None

    @model_validator(mode="after")
    def _default_database_url(self) -> Settings:
        """Set database_url default after data_dir is resolved."""
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir}/db/wikimind.db"
        return self

    @model_validator(mode="after")
    def _fallback_database_url(self) -> Settings:
        """Fall back to the unprefixed DATABASE_URL env var for managed Postgres services.

        Fly.io, Railway, Render, and Heroku set DATABASE_URL automatically
        when attaching a managed Postgres instance. This validator lets those
        deployments work without requiring WIKIMIND_DATABASE_URL to be set
        manually. The scheme is rewritten from postgres:// or postgresql://
        to postgresql+asyncpg:// for SQLAlchemy async compatibility.

        Only activates when the current database_url is NOT already a Postgres
        URL (i.e., when it's the SQLite default from _default_database_url).
        """
        raw = os.environ.get("DATABASE_URL")
        if raw and not self.database_url.startswith("postgresql"):
            if raw.startswith("postgres://"):
                raw = raw.replace("postgres://", "postgresql+asyncpg://", 1)
            elif raw.startswith("postgresql://"):
                raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
            self.database_url = raw
        return self

    @model_validator(mode="after")
    def _auto_enable_providers_with_keys(self) -> Settings:
        """Auto-enable any provider whose API key is configured.

        Resolves the long-standing UX problem where exporting OPENAI_API_KEY
        was not enough to use OpenAI — users also had to manually flip
        WIKIMIND_LLM__OPENAI__ENABLED=true. Now any provider whose key is
        present (env var, prefixed env var, or keyring) is automatically
        marked enabled.

        If a key is set but the user has explicitly disabled the provider via
        env var, that override still wins — only the default-disabled state
        is changed.
        """
        for provider_name, (field, raw_env) in _PROVIDER_KEY_FIELDS.items():
            has_key = bool(
                getattr(self, field)
                or os.environ.get(raw_env)
                or os.environ.get(f"WIKIMIND_{raw_env}")
                or _safe_keyring_get(provider_name)
            )
            if not has_key:
                continue
            provider_cfg = getattr(self.llm, provider_name)
            if not provider_cfg.enabled:
                provider_cfg.enabled = True
                log.info(
                    "auto-enabled provider (key detected)",
                    provider=provider_name,
                    model=provider_cfg.model,
                )
        return self

    @model_validator(mode="after")
    def _warn_on_misconfigured_providers(self) -> Settings:
        """Warn when a provider is enabled but has no key configured."""
        for provider_name, (field, raw_env) in _PROVIDER_KEY_FIELDS.items():
            provider_cfg = getattr(self.llm, provider_name)
            if not provider_cfg.enabled:
                continue
            has_key = bool(
                getattr(self, field)
                or os.environ.get(raw_env)
                or os.environ.get(f"WIKIMIND_{raw_env}")
                or _safe_keyring_get(provider_name)
            )
            if not has_key:
                log.warning(
                    "provider enabled but no API key configured — calls will fail",
                    provider=provider_name,
                    hint=f"set {raw_env} in your environment or .env file",
                )
        return self

    @model_validator(mode="after")
    def _fallback_redis_url(self) -> Settings:
        """Fall back to the unprefixed REDIS_URL env var when the prefixed form is unset.

        Matches the dual-read pattern used for API keys — lets CI/CD pipelines
        and production deployments that set the unprefixed ``REDIS_URL``
        (documented in ADR-002) keep working while docker-compose and .env
        files that use ``WIKIMIND_REDIS_URL`` (matching every other WikiMind
        env var) also work out of the box. Precedence: prefixed wins over raw.

        Empty string is treated as unset so that ``WIKIMIND_REDIS_URL=`` in a
        compose file or .env falls through cleanly to the raw env var (and
        then to ``None``) instead of being stored as a zero-length URL the
        worker would later fail to parse.
        """
        if not self.redis_url:
            self.redis_url = os.environ.get("REDIS_URL") or None
        return self

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

        Checks all key sources: SecretStr field (prefixed env), raw env var
        (unprefixed for CI/CD), and OS keychain.
        """
        return {
            "anthropic_api_key": self._has_provider_key("anthropic"),
            "openai_api_key": self._has_provider_key("openai"),
            "google_api_key": self._has_provider_key("google"),
            "keyring_backend": type(keyring.get_keyring()).__name__,
        }

    def _has_provider_key(self, provider: str) -> bool:
        """Check if a key for the given provider is configured anywhere."""
        field, raw_env = _PROVIDER_KEY_FIELDS[provider]
        return bool(
            getattr(self, field)
            or os.environ.get(raw_env)
            or os.environ.get(f"WIKIMIND_{raw_env}")
            or _safe_keyring_get(provider)
        )


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

    Priority: env var (via Settings SecretStr) -> raw env var -> keychain.
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
    return _safe_keyring_get(provider)


def set_api_key(provider: str, key: str) -> None:
    """Store API key in OS keychain."""
    keyring.set_password(KEYRING_SERVICE, provider, key)


def delete_api_key(provider: str) -> None:
    """Remove API key from OS keychain."""
    keyring.delete_password(KEYRING_SERVICE, provider)
