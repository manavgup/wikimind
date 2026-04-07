# ADR-008: Pydantic BaseSettings for configuration

## Status

Accepted

## Context

WikiMind needs to manage a variety of configuration: server host/port, data
directory paths, LLM provider selection and model names, API keys for multiple
providers, cloud sync settings, and database options. Configuration must support
environment variables (for CI/CD and containers), `.env` files (for local
development), and secure handling of API keys that must never appear in logs.

The configuration layer was recently refactored to consolidate scattered settings
into a single, validated, type-safe configuration object.

## Decision

We use **Pydantic BaseSettings** (`pydantic-settings`) as the configuration
foundation, with the following design:

1. **Environment-first**: All settings are loaded from environment variables
   with the `WIKIMIND_` prefix via `SettingsConfigDict(env_prefix="WIKIMIND_")`.
   A `.env` file is loaded automatically when present.

2. **SecretStr for API keys**: All API key fields (`anthropic_api_key`,
   `openai_api_key`, `google_api_key`, AWS credentials) use `SecretStr`, which
   prevents accidental exposure in logs, repr output, or serialization.

3. **Keyring fallback**: The `get_api_key()` function checks settings (env vars)
   first, then falls back to the OS keychain via the `keyring` library. This
   lets users store keys securely without `.env` files on their personal machine
   while still supporting env vars in CI/CD.

4. **Nested configuration**: Related settings are grouped into `BaseModel`
   subclasses (`LLMConfig`, `SyncConfig`, `DatabaseConfig`, `ServerConfig`)
   for clarity and validation.

5. **Cached singleton**: `get_settings()` uses `@lru_cache(maxsize=1)` to ensure
   settings are loaded once and reused across the application.

## Alternatives Considered

**Plain environment variables (os.environ)** -- No validation, no type safety,
no default values, no nesting, no protection against logging secrets. Requires
manual parsing everywhere.

**TOML/YAML config file only** -- Works for static configuration but does not
support environment variable overrides for deployment. Would require a separate
mechanism for secrets management. We do plan to support a `settings.toml` for
non-sensitive settings in the future, layered under env vars.

**dynaconf** -- Feature-rich configuration library with multi-source support.
However, it adds a significant dependency, has its own learning curve, and
duplicates functionality that Pydantic BaseSettings provides natively. Since
we already depend on Pydantic for models, BaseSettings is the natural choice.

**python-decouple** -- Lightweight env/ini reader but lacks type validation,
nested config support, and secret protection. Insufficient for our needs.

**Vault/AWS Secrets Manager** -- Enterprise secrets management. Overkill for
a local-first application. The keyring fallback provides similar security for
individual users without requiring cloud infrastructure.

## Consequences

**Enables:**
- Type-safe configuration with validation errors at startup, not at runtime
- API keys never appear in logs or error messages thanks to SecretStr
- Flexible key storage: env vars for CI/CD, keyring for personal machines
- Derived paths (`wiki_dir`, `raw_dir`, `db_dir`) computed from `data_dir`
- `ensure_dirs()` called at startup guarantees directory structure exists
- `get_security_status()` provides a production readiness check

**Constrains:**
- Adding a new setting requires updating the `Settings` class and
  documenting the corresponding `WIKIMIND_*` environment variable
- The `lru_cache` means settings cannot be changed at runtime without
  clearing the cache (acceptable for a daemon that restarts on config changes)

**Risks:**
- The keyring library behavior varies across operating systems; some Linux
  environments may not have a keyring backend configured. Mitigated by
  always checking env vars first and only falling back to keyring.

## Subsequent decisions

- **ADR-010** — Auto-enable LLM providers when their API key is detected (extends the validator pattern introduced here)
