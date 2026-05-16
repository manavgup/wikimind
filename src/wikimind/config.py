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
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

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
    enabled: bool = False


class OpenAIConfig(LLMProviderConfig):
    """OpenAI provider defaults."""

    model: str = "gpt-4o"
    enabled: bool = False


class OpenAICompatibleConfig(LLMProviderConfig):
    """OpenAI Chat Completions-compatible endpoint defaults."""

    model: str = "gpt-4o-mini"
    enabled: bool = False
    base_url: str = ""
    supports_json_response_format: bool = True
    supports_stream_usage: bool = True
    supports_reasoning_effort: bool = True
    max_tokens_field: str = "max_tokens"
    reasoning_format: Literal["none", "openai", "openrouter"] = "openai"
    site_url: str = ""
    app_name: str = ""


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
    trace_enabled: bool = False
    trace_store_content: bool = False
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    openai_compatible: OpenAICompatibleConfig = Field(default_factory=OpenAICompatibleConfig)
    google: GoogleConfig = Field(default_factory=GoogleConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    ollama_base_url: str = "http://localhost:11434"
    mock: MockConfig = Field(default_factory=MockConfig)

    @model_validator(mode="after")
    def _validate_budget_warning_pct(self) -> LLMConfig:
        """Ensure budget_warning_pct is a valid fraction between 0 and 1."""
        if not 0 < self.budget_warning_pct < 1:
            msg = "budget_warning_pct must be between 0 and 1 (exclusive)"
            raise ValueError(msg)
        return self


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
    ws_keepalive_seconds: float = 30.0


class QAConfig(BaseModel):
    """Q&A agent configuration — controls multi-turn conversation behavior."""

    max_prior_turns_in_context: int = 5
    prior_answer_truncate_chars: int = 500
    conversation_title_max_chars: int = 120
    max_tokens: int = 2048
    auto_file_back_enabled: bool = False
    auto_file_back_min_words: int = 200
    auto_file_back_min_sources: int = 3


class TaxonomyConfig(BaseModel):
    """Concept taxonomy configuration."""

    rebuild_threshold: int = 5
    max_hierarchy_depth: int = 3
    concept_page_min_sources: int = 2


class MCPServerEntry(BaseModel):
    """Configuration for a single external MCP server connection."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    # stdio transport fields
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    # http transport fields
    url: str = ""
    headers: dict[str, str] | None = None
    # shared
    timeout: float = 30.0


class CaptureConfig(BaseModel):
    """Ambient capture configuration (issue #442)."""

    rss_poll_interval_minutes: int = 60
    rss_max_entries_per_poll: int = 50
    auto_discard_min_chars: int = 200
    rss_http_timeout_seconds: int = 30


class SearchConfig(BaseModel):
    """Full-text search configuration."""

    fts_max_candidates: int = 1000


class WorkerConfig(BaseModel):
    """ARQ worker configuration."""

    max_jobs: int = 4
    job_timeout: int = 300  # 5 min max per job
    keep_result: int = 3600  # keep results for 1 hour


class IngestConfig(BaseModel):
    """Ingestion configuration."""

    http_timeout_seconds: int = 30


class CompilerConfig(BaseModel):
    """Compiler configuration."""

    max_tokens: int = 8192
    source_text_max_chars: int = 60000
    concept_source_max_chars: int = 5000
    synthesis_max_sources: int = 15
    interactive: bool = False
    guidance_max_length: int = 2000
    slug_max_attempts: int = 1000


class StalenessConfig(BaseModel):
    """Staleness detection configuration (issue #425)."""

    decay_rate: float = 0.002  # ~50% staleness at 250 days
    lint_threshold: float = 0.5  # articles above this are flagged

    @model_validator(mode="after")
    def _validate_staleness_params(self) -> StalenessConfig:
        """Ensure staleness parameters are within valid ranges."""
        if self.decay_rate <= 0:
            msg = "decay_rate must be positive"
            raise ValueError(msg)
        if not 0 < self.lint_threshold < 1:
            msg = "lint_threshold must be between 0 and 1 (exclusive)"
            raise ValueError(msg)
        return self


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
    max_concept_concurrency: int = 5
    auto_recompile_on_contradiction: bool = True


class ConceptLayerConfig(BaseModel):
    """Concept-layer clustering configuration (issue #466).

    Controls the two-stage concept clustering pipeline: online (advisory)
    labeling at ingest time, and offline reconciliation by the batch reconciler.
    """

    embedding_backend: Literal["bge-small", "openai"] = "bge-small"
    embedding_dim: int = 384
    embedding_version: str = "bge-small-1.5"
    auto_join_threshold: float = 0.85
    tiebreaker_threshold: float = 0.70
    cluster_promote_min_members: int = 2
    cluster_canonical_refresh_min_members: int = 5
    cluster_size_split_threshold: int = 100
    reconciler_min_interval_minutes: int = 60


class EmbeddingConfig(BaseModel):
    """Embedding and semantic search configuration."""

    model_name: str = "all-MiniLM-L6-v2"
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 50
    min_similarity_score: float = 0.65

    @model_validator(mode="after")
    def _validate_chunk_overlap(self) -> EmbeddingConfig:
        """Ensure chunk_overlap_tokens is non-negative and less than chunk_size_tokens."""
        if self.chunk_overlap_tokens < 0:
            msg = f"chunk_overlap_tokens ({self.chunk_overlap_tokens}) must not be negative"
            raise ValueError(msg)
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            msg = (
                f"chunk_overlap_tokens ({self.chunk_overlap_tokens}) must be less than "
                f"chunk_size_tokens ({self.chunk_size_tokens})"
            )
            raise ValueError(msg)
        return self


class MCPConfig(BaseModel):
    """MCP server configuration."""

    require_auth: bool = True  # applies to HTTP transport only
    external_servers: list[MCPServerEntry] = Field(default_factory=list)
    client_enabled: bool = False


class RateLimitConfig(BaseModel):
    """Rate limiting configuration.

    Controls per-user request rate limits for auth, query, and ingest
    endpoints. Backed by Redis when available; falls back to in-memory
    storage for single-process dev mode.
    """

    enabled: bool = True
    auth_limit: str = "5/minute"
    query_limit: str = "30/minute"
    ingest_limit: str = "10/minute"


class AuthConfig(BaseModel):
    """OAuth2 authentication configuration.

    Auth is always on. In development mode (``is_dev``), the system can
    auto-provision and auto-authenticate a dev user so that no manual
    login is needed for local development.
    """

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    oauth_state_ttl_seconds: int = 600
    # BFF cookie settings
    cookie_name: str = "wikimind_session"
    cookie_secure: bool = True  # False in dev (HTTP), True in prod (HTTPS)
    cookie_domain: str | None = None  # None = current host; set for subdomains
    # Public base URL for OAuth callbacks (e.g. "https://wikimind.fly.dev").
    # When set, used instead of the request Host header to build redirect URIs.
    public_url: str = ""
    # Magic link (passwordless email) login
    magic_link_enabled: bool = True
    magic_link_ttl_seconds: int = 600  # 10 minutes
    magic_link_token_length: int = 32  # bytes for secrets.token_urlsafe
    # Dev-mode auto-authentication: when is_dev AND dev_auto_auth, requests
    # are auto-authenticated as the dev user (no login required).
    dev_auto_auth: bool = True
    dev_user_email: str = "dev@wikimind.local"


# Mapping from provider name → (Settings field for SecretStr key, raw env var name).
# Used by both `get_api_key` and the auto-enable validator below.
_PROVIDER_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "openai_compatible": ("openai_compatible_api_key", "OPENAI_COMPATIBLE_API_KEY"),
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

    # Runtime environment — controls dev-only features like magic-link dev_token.
    # Defaults to "production" (secure by default). Set WIKIMIND_ENV=development
    # in local dev to enable dev shortcuts.
    env: str = "production"

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
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    compiler: CompilerConfig = Field(default_factory=CompilerConfig)
    linter: LinterConfig = Field(default_factory=LinterConfig)
    staleness: StalenessConfig = Field(default_factory=StalenessConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    concept_layer: ConceptLayerConfig = Field(default_factory=ConceptLayerConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    # Storage backend: "local" creates wiki/ and raw/ on the local filesystem;
    # "r2" delegates to Cloudflare R2 (wiki_dir / raw_dir are not needed).
    storage_backend: str = "local"

    # PDF extraction: docling-serve sidecar URL.
    # The docling-serve container exposes /v1/convert/source for PDF-to-markdown.
    docling_serve_url: str = "http://localhost:5001"

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
    image_min_bytes: int = 5000
    image_base_url: str = "/images"

    # API keys — SecretStr prevents accidental logging
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_compatible_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None

    @model_validator(mode="after")
    def _post_init(self) -> Settings:
        """Resolve env-var fallbacks that pydantic-settings can't handle natively."""
        # Database URL: SQLite default, or rewrite unprefixed DATABASE_URL scheme
        constructed_url = self.database_url
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir}/db/wikimind.db"
            constructed_url = self.database_url
        raw = os.environ.get("DATABASE_URL")
        wikimind_db_url_set = bool(os.environ.get("WIKIMIND_DATABASE_URL"))
        if raw and not self.database_url.startswith("postgresql"):
            self.database_url = re.sub(r"^postgres(ql)?://", "postgresql+asyncpg://", raw)
        if raw and wikimind_db_url_set and self.database_url != constructed_url:
            log.warning(
                "DATABASE_URL env var overrides WIKIMIND_DATABASE_URL",
                hint="remove one to avoid ambiguity",
            )
        # Redis URL: fall back to unprefixed REDIS_URL
        if not self.redis_url:
            self.redis_url = os.environ.get("REDIS_URL") or None
        # Upstash Fly Redis private endpoint uses plain redis:// (no TLS).
        # Do NOT auto-upgrade to rediss:// — confirmed via manual testing
        # that the private endpoint rejects TLS handshakes.
        # If using a public Upstash endpoint, set WIKIMIND_REDIS_URL to
        # rediss:// explicitly.

        # Warn about empty JWT secret in production — PyJWT accepts "" as a
        # valid HMAC key, which would let anyone forge tokens. We warn rather
        # than raise because CLI tools (export-openapi, migrations) may run
        # without auth configured.
        if not self.is_dev and not self.auth.jwt_secret_key:
            log.warning(
                "jwt_secret_key is empty in production mode — set WIKIMIND_AUTH__JWT_SECRET_KEY",
            )
        return self

    @property
    def is_dev(self) -> bool:
        """Return True when running in development mode."""
        return self.env.lower() == "development"

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
        """Create all required directories.

        Always creates db_dir and config dir (needed regardless of storage
        backend). wiki_dir and raw_dir are only created when the storage
        backend is "local" — remote backends (e.g. R2) don't use them.
        """
        dirs: list[Path] = [self.db_dir, Path(self.data_dir) / "config"]
        if self.storage_backend == "local":
            dirs.extend([self.wiki_dir, self.raw_dir])
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def get_security_status(self) -> dict[str, object]:
        """Return a summary of which API keys and security features are configured.

        Checks all key sources: SecretStr field (prefixed env), raw env var
        (unprefixed for CI/CD), and OS keychain.
        """
        return {
            "anthropic_api_key": self._has_provider_key("anthropic"),
            "openai_api_key": self._has_provider_key("openai"),
            "openai_compatible_api_key": self._has_provider_key("openai_compatible"),
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


def _reconcile_providers(settings: Settings) -> None:
    """Auto-enable providers with keys; warn about enabled ones without."""
    for name, (_field, raw_env) in _PROVIDER_KEY_FIELDS.items():
        cfg = getattr(settings.llm, name)
        has_key = settings._has_provider_key(name)
        missing_runtime = name == "openai_compatible" and not cfg.base_url
        if has_key and not cfg.enabled and not missing_runtime:
            cfg.enabled = True
            log.info("auto-enabled provider (key detected)", provider=name)
        elif has_key and missing_runtime:
            log.warning(
                "provider key detected but required base URL is missing",
                provider=name,
                hint="set WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL",
            )
        elif not has_key and cfg.enabled:
            log.warning("provider enabled but no API key", provider=name, env_var=raw_env)
        elif name == "openai_compatible" and cfg.enabled and not cfg.base_url:
            log.warning(
                "provider enabled but required base URL is missing",
                provider=name,
                hint="set WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL",
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and return application settings (cached singleton)."""
    settings = Settings()
    settings.ensure_dirs()
    _reconcile_providers(settings)
    return settings


# ---------------------------------------------------------------------------
# RuntimeConfig — mutable overlay that keeps the Settings singleton immutable
# ---------------------------------------------------------------------------


class RuntimeConfig:
    """Thread-safe mutable overlay for DB-persisted runtime settings.

    Composes over the immutable Settings singleton. Callers read runtime
    values (e.g. ``default_provider``, ``monthly_budget_usd``) from this
    object. Values start as ``None`` (meaning "use the Settings default")
    and are populated from the DB at startup or on write.

    This replaces the previous pattern of mutating ``get_settings()`` directly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set a runtime override (thread-safe)."""
        with self._lock:
            self._overrides[key] = value

    def get(self, key: str) -> Any | None:
        """Get a runtime override, or None if not set."""
        with self._lock:
            return self._overrides.get(key)

    def get_default_provider(self) -> str:
        """Return the effective default LLM provider."""
        override = self.get("llm.default_provider")
        if override is not None:
            return override
        return get_settings().llm.default_provider

    def get_monthly_budget_usd(self) -> float:
        """Return the effective monthly budget."""
        override = self.get("llm.monthly_budget_usd")
        if override is not None:
            return float(override)
        return get_settings().llm.monthly_budget_usd

    def get_fallback_enabled(self) -> bool:
        """Return the effective fallback setting."""
        override = self.get("llm.fallback_enabled")
        if override is not None:
            return bool(override)
        return get_settings().llm.fallback_enabled

    def get_openai_compatible_base_url(self) -> str:
        """Return the effective OpenAI-compatible base URL."""
        override = self.get("llm.openai_compatible.base_url")
        if override is not None:
            return override
        return get_settings().llm.openai_compatible.base_url

    def get_openai_compatible_model(self) -> str:
        """Return the effective OpenAI-compatible model."""
        override = self.get("llm.openai_compatible.model")
        if override is not None:
            return override
        return get_settings().llm.openai_compatible.model

    def get_openai_compatible_enabled(self) -> bool:
        """Return whether the OpenAI-compatible provider is effectively enabled."""
        base_url = self.get_openai_compatible_base_url()
        model = self.get_openai_compatible_model()
        settings = get_settings()
        has_key = bool(settings._has_provider_key("openai_compatible") or settings.llm.openai_compatible.enabled)
        return bool(has_key and base_url and model)

    def get_openai_compatible_field(self, field_name: str) -> Any:
        """Return an effective OpenAI-compatible config field value."""
        override = self.get(f"llm.openai_compatible.{field_name}")
        if override is not None:
            return override
        return getattr(get_settings().llm.openai_compatible, field_name)


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    """Return the singleton RuntimeConfig instance."""
    return RuntimeConfig()


# ---------------------------------------------------------------------------
# API Key management — env vars first, then OS keychain
# ---------------------------------------------------------------------------

_ENV_MAP: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "openai_compatible": "openai_compatible_api_key",
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
        "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
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
