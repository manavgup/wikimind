# BYOK Migration & Production Hardening

## Problem

Setting API keys (OpenAI, Gemini) fails on Fly.io production with a 500 error. The frontend calls `POST /settings/llm/api-key`, which stores keys via `keyring.set_password()` (OS keychain). Fly.io containers have no keyring backend, so this crashes.

A proper BYOK endpoint (`PUT /api/settings/api-keys/{provider}`) already exists — it encrypts keys with Fernet/PBKDF2 and stores them in the database. The frontend just never uses it.

Tests didn't catch this because the test fixture (`conftest.py:52`) installs an in-memory keyring backend, and the endpoint test (`test_misc.py:107`) only checks `status_code == 200` without verifying the key was actually stored or retrievable.

## Scope

Two PRs, independent of each other:

1. **PR 1 — Bug fix:** Migrate frontend to BYOK endpoint, remove legacy keyring endpoint, fix provider "configured" status
2. **PR 2 — Production hardening:** Startup secret validation, smoke tests in deploy pipeline

---

## PR 1: Migrate to BYOK Endpoint

### Frontend

**`apps/web/src/api/settings.ts`** — Change `setApiKey()`:

- **From:** `POST /settings/llm/api-key` with body `{ provider, api_key }`
- **To:** `PUT /api/settings/api-keys/${provider}` with body `{ api_key }`
- Return type changes from `Promise<void>` to `Promise<{provider: string, key_hint: string, status: string}>` (callers don't use the return value, so no other frontend changes needed)

No changes needed to `ApiKeyModal.tsx`, `OnboardingWizard.tsx`, or `ProviderCard.tsx` — they all call `setApiKey()` from the API module and only care about success/failure.

### Backend — Remove legacy endpoint

**`src/wikimind/api/routes/settings.py`:**
- Remove `POST /settings/llm/api-key` handler (`set_provider_api_key`, lines 274-285)
- Remove `APIKeyRequest` model (lines 24-28)
- Remove `ProviderKeyResponse` model (used only by this endpoint)
- Remove `set_api_key` import from `wikimind.config`

**`src/wikimind/config.py`:**
- Remove `set_api_key()` function (lines 418-420) — no longer called
- Remove `delete_api_key()` function (lines 423-425) — never imported anywhere
- Keep `_safe_keyring_get()` and `get_api_key()` (the read path) — still needed for env var resolution and localhost keyring fallback

### Backend — Fix provider "configured" status

**`src/wikimind/api/routes/settings.py`** `get_all_settings()` (line 168):

Currently checks `configured=bool(get_api_key(p.value))` which only checks env vars + keyring. After migration, user-set BYOK keys in the database won't show as "configured".

Fix: Add `session: AsyncSession` and `user_id: str` dependencies. For each provider, check:
1. `get_api_key(p.value)` — env var / keyring (system-level key)
2. If not found, `get_user_api_key(session, user_id, p)` — BYOK database key

A provider is "configured" if either source has a key.

### Backend — Error handling

**`src/wikimind/api/routes/api_keys.py`** `set_api_key()` (line 110):

Wrap `set_user_api_key()` in try/except to catch `ValueError` from missing `JWT_SECRET_KEY` and return HTTP 500 with specific error message instead of a generic 500. This is a server misconfiguration, not a user error.

### Tests

**`tests/unit/test_api_keys.py`:**
- Add test: setting key with empty `JWT_SECRET_KEY` returns 500 with descriptive error
- Existing 28 tests already cover the BYOK happy path

**`tests/unit/test_misc.py`:**
- Remove tests for the deleted `POST /settings/llm/api-key` endpoint (lines 102-109)

**`tests/unit/test_misc.py`** (where settings endpoint tests live):
- Add test: `GET /settings` shows `configured: true` when BYOK key exists in database
- Add test: `GET /settings` shows `configured: true` when env var key exists (existing behavior)

---

## PR 2: Production Hardening

### Startup secret validation

**`src/wikimind/main.py`** lifespan function:

After settings load, validate required secrets:
- If `auth.enabled` is `True` and `jwt_secret_key` is empty → log error and raise `SystemExit` (fail fast, don't start serving requests that will 500)
- If no LLM provider has a configured API key → log warning (non-fatal, app can still accept user BYOK keys)

### Post-deploy smoke checks

**`.github/workflows/deploy.yml`:**

The existing `tests/smoke/test_docker_smoke.py` tests build a local Docker image — they can't run against a remote URL. Instead, add a lightweight post-deploy verification step directly in the workflow:

After each successful deploy, hit the deployed app's key endpoints:
- `GET /health` — returns 200
- `GET /api/docs` — returns 200 (confirms FastAPI loaded)
- `GET /` — returns 200 with HTML (confirms SPA serving)

This catches the most common deployment failures (crashes on startup, missing dependencies, broken mounts) without needing the full Docker test suite. Implemented as a simple `curl`-based step in the workflow, not a separate test file.

### Audit other endpoints

Quick check for other environment assumptions:
- `config.py:338` `get_security_status()` calls `keyring.get_keyring().__name__` — wrap in try/except (cosmetic, not critical)
- No other keyring write calls exist beyond the ones being removed

---

## What this does NOT include

- Removing keyring as a dependency — it's still used for the read path on localhost
- Migrating existing keyring-stored keys to the database — localhost users would need to re-enter keys (acceptable, they're dev keys)
- Changes to the LLM router's key resolution — `get_api_key()` in config.py still works for env var keys, and the router already has BYOK integration via `get_user_api_key()`

## Files modified

### PR 1
| File | Change |
|------|--------|
| `apps/web/src/api/settings.ts` | Switch `setApiKey()` to BYOK endpoint |
| `src/wikimind/api/routes/settings.py` | Remove legacy endpoint, update `configured` check |
| `src/wikimind/api/routes/api_keys.py` | Add ValueError error handling |
| `src/wikimind/config.py` | Remove `set_api_key()`, `delete_api_key()` |
| `tests/unit/test_api_keys.py` | Add missing JWT_SECRET_KEY test |
| `tests/unit/test_misc.py` | Remove legacy endpoint tests |
| `tests/unit/test_misc.py` | Add BYOK configured status tests |

### PR 2
| File | Change |
|------|--------|
| `src/wikimind/main.py` | Add startup secret validation |
| `.github/workflows/deploy.yml` | Add post-deploy health check step |
| `src/wikimind/config.py` | Wrap `get_security_status()` keyring call |
