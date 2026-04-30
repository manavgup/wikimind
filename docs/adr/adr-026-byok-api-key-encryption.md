# ADR-026: BYOK API Key Encryption at Rest

## Status

Accepted

## Context

WikiMind uses system-wide API keys (from environment variables or OS keychain)
to access LLM providers.  In a multi-user deployment, users should be able to
supply their own API keys so they can use their own accounts and billing.
User-supplied keys must be stored securely at rest in the database.

Requirements:
- Encrypt user API keys before storing in the database
- Use a unique encryption key per row to limit blast radius of any single key leak
- Derive encryption keys from an existing secret (JWT_SECRET_KEY) to avoid
  requiring operators to manage yet another secret
- When a user has their own key for a provider, use it instead of the system key

## Decision

### Encryption scheme

- **Algorithm**: Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256 via
  the `cryptography` library)
- **Key derivation**: PBKDF2-HMAC-SHA256 with 100,000 iterations (OWASP 2023
  minimum for SHA-256)
- **Key material**: `JWT_SECRET_KEY` (required for authentication and BYOK
  key storage) +
  a 16-byte random per-row salt
- **Storage**: `UserApiKey` table with `encrypted_key` (Fernet ciphertext,
  base64) and `salt` (hex-encoded)

### Data model

```
UserApiKey(table=True)
  id:            UUID primary key
  user_id:       FK -> user.id (indexed)
  provider:      Provider enum (anthropic | openai | google)
  encrypted_key: str  -- Fernet ciphertext
  salt:          str  -- hex-encoded 16-byte random salt
  created_at:    datetime
  updated_at:    datetime
  UNIQUE(user_id, provider)
```

### API endpoints

- `PUT  /api/settings/api-keys/{provider}` -- set/update a key
- `GET  /api/settings/api-keys`            -- list providers (masked hints only)
- `DELETE /api/settings/api-keys/{provider}` -- remove a key

API responses never return raw keys -- only masked hints (first 4 + last 4
characters).

### LLM router integration

When making LLM calls, the router checks for a user-specific BYOK key:
1. Look up `UserApiKey` for `(user_id, provider)` in the database
2. If found, decrypt and create a temporary (non-cached) provider instance
3. If not found, fall back to the system-wide key

BYOK provider instances are intentionally NOT cached in the router's
`_provider_cache` to prevent one user's key from leaking to another.

## Consequences

### Positive
- Users can use their own billing accounts without exposing keys to the operator
- Per-row salt means compromising one ciphertext does not help decrypt others
- No new secret to manage -- reuses existing JWT_SECRET_KEY
- Backward compatible -- system keys continue to work as before

### Negative
- Rotating JWT_SECRET_KEY invalidates all stored user keys (they become
  undecryptable).  Operators must warn users to re-enter keys after rotation.
- PBKDF2 key derivation adds ~50ms per LLM call when a user key is used
  (negligible vs. LLM latency).  Could be optimized with an in-memory TTL
  cache per user/provider if needed.
- BYOK provider instances are created fresh per-call, adding minor overhead
  (SDK client initialization) compared to the cached system-key path.
