# ADR-010: Auto-enable LLM providers when their API key is detected

## Status

Accepted

## Context

Earlier configuration (ADR-008) required users to set both an API key
AND a separate `enabled=True` flag to use a provider. This created a
recurring UX problem: contributors and AI agents would export
`OPENAI_API_KEY`, run `make dev`, and get `All LLM providers failed.
Last error: None` because OpenAI was technically disabled in the config
defaults.

The friction wasted significant time during PR #69 testing. We needed
a way for "I have a key" to imply "use this provider" without
requiring a second declaration.

## Decision

Add a Pydantic `model_validator(mode="after")` on `Settings` that walks
the configured providers (`anthropic`, `openai`, `google`) and flips
`enabled = True` for any provider whose API key is found via:

1. The `WIKIMIND_*_API_KEY` environment variable (Pydantic SecretStr field)
2. The unprefixed `*_API_KEY` environment variable (CI/CD compatibility)
3. The OS keychain via `keyring.get_password(KEYRING_SERVICE, provider)`

A second validator (`_warn_on_misconfigured_providers`) emits a startup
warning when the inverse condition holds — provider enabled but no
key configured — pointing the user at the env var to set.

The validators run on every `Settings()` instantiation, so the
auto-enable behavior is consistent across env-only, .env-file, and
keyring configurations.

## Alternatives Considered

**Explicit enabled flag (status quo)** — required two declarations
per provider. The recurring "I exported the key but it doesn't work"
problem made this untenable.

**Settings runtime mutation endpoint** — `POST /settings/llm/provider`
to flip flags without a restart. Defers the problem and adds complexity
without addressing the root cause: users want "key present → provider
on" by default.

**CLI prompt on first run** — interactive setup wizard. Doesn't help
in non-interactive environments (CI, Codespaces, Docker).

**Detection at provider call time** — check for key only when the
LLM router is about to make a call. Defers the validation to runtime
errors instead of startup, which is worse for debugging.

## Consequences

**Enables:**
- Single-key users have zero-config DX: `export OPENAI_API_KEY=... && make dev` works
- AI agents and CI jobs don't need to remember the `WIKIMIND_LLM__OPENAI__ENABLED=true` incantation
- Misconfiguration produces a clear startup warning instead of a silent runtime failure
- Same code path for keyring users, env users, and .env users

**Constrains:**
- "I have a key but I don't want this provider on" requires `WIKIMIND_LLM__OPENAI__ENABLED=false` in env. Counterintuitive but discoverable via the warning.
- Provider granularity is per-vendor, not per-model. Switching between `claude-sonnet-4-5` and `claude-haiku-4-5` is one provider; the active model is set via `WIKIMIND_LLM__ANTHROPIC__MODEL`.

**Risks:**
- A leaked key in `.env` would cause its provider to auto-enable and consume budget. Mitigated by `.env` being gitignored, `SecretStr` preventing accidental logging, and the monthly budget cap.
- Users with multiple keys may be surprised when fallback kicks in to the "wrong" provider. The default provider is `anthropic`; users can override via `WIKIMIND_LLM__DEFAULT_PROVIDER`.
