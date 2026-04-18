# ADR-022: Multi-User Authentication via OAuth2

## Status

Accepted

## Context

WikiMind was designed as a single-user personal knowledge OS. To support multiple
users on a shared server deployment, we need authentication and identity
management. The system must remain backward compatible — when auth is disabled,
it works exactly as before.

## Decision

- **OAuth2/SSO** with Google and GitHub as identity providers
- **JWT tokens** for session management (stateless, no server-side sessions)
- **Opt-in via config** — `WIKIMIND_AUTH__ENABLED=false` by default
- **PyJWT** for token encoding/decoding (lightweight, no framework dependency)
- Auth middleware skips exempt paths (`/health`, `/docs`, `/auth/*`)
- User model stores provider identity (email, name, avatar) — no passwords stored

### Alternatives Considered

**API keys per user** — simpler but poor UX for a web app (no login flow).

**Managed auth (Auth0, Clerk)** — less code but adds external dependency and cost.

**JWT with email/password** — requires password hashing, email verification, reset
flows.

## Consequences

**Enables:**
- Multi-user deployments on a shared server
- Per-user data isolation (PR 2) depends on user identity from this PR

**Constrains:**
- New `User` table and `AuthConfig` in Settings
- All routes remain accessible without auth when disabled (backward compatible)
- Frontend must handle token storage and injection (PR 5)
