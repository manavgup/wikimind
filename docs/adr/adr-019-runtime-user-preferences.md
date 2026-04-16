# ADR-019: Runtime User Preferences via DB Override Table

## Status

Accepted

## Context

WikiMind loads all configuration from `.env` / environment variables via Pydantic `BaseSettings` with an `@lru_cache` singleton. This means changing the default LLM provider, monthly budget, or fallback toggle requires editing `.env` and restarting the app.

The Settings UI (#29) needs to let users change a small set of frequently-toggled values at runtime without restarting. mcp-context-forge solves this with database-backed runtime config — provider state lives in DB tables, toggled via API, committed immediately.

## Decision

Introduce a `UserPreference` key-value table for runtime overrides. Only three settings are runtime-changeable:

| Key | Type | Default |
|-----|------|---------|
| `llm.default_provider` | str | "anthropic" |
| `llm.monthly_budget_usd` | float | 50.0 |
| `llm.fallback_enabled` | bool | true |

**Precedence:** DB row wins if it exists. Otherwise falls back to `.env` defaults.

**Startup:** After `init_db()`, `_apply_db_preferences()` reads all `UserPreference` rows and applies them to the in-memory Settings singleton. This ensures DB overrides survive restarts.

**Write path:** API endpoints (`POST /settings/llm/default-provider`, `PATCH /settings`) write to the DB table AND mutate the in-memory singleton for immediate effect.

**Read path:** `GET /settings` overlays DB values onto the response.

## Consequences

- Users can change default provider, budget, and fallback from the UI without restart.
- `.env` remains the canonical source for infrastructure config (host, port, data_dir, API keys).
- The `user_preference` table is lightweight (max 3 rows). No schema migration needed — auto-created by SQLModel.
- Deleting the DB reverts all preferences to `.env` defaults cleanly.
- Budget warning thresholds (`budget_warning_pct`, `budget_check_cache_seconds`) remain `.env`-only — they are operational tuning knobs, not user-facing settings.
