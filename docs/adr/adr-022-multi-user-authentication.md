# ADR-022: Multi-User Authentication via OAuth2

## Status

Accepted (revised — BFF cookie auth, April 2026)

## Context

WikiMind was designed as a single-user personal knowledge OS. To support multiple
users on a shared server deployment, we need authentication and identity
management. The system must remain backward compatible — when auth is disabled,
it works exactly as before.

The initial implementation used JWT tokens passed via URL fragment and stored in
`localStorage`. This was vulnerable to XSS (any injected script could steal the
token) and required a `FRONTEND_URL` hack to redirect across ports in dev mode.

## Decision

- **OAuth2/SSO** with Google and GitHub as identity providers
- **BFF (Backend-for-Frontend) cookie pattern** — the backend sets an `HttpOnly`
  cookie carrying the JWT after OAuth callback; the frontend never touches the
  token directly
- **Cookie-first, header-fallback** — auth middleware reads the JWT from the
  `wikimind_session` HttpOnly cookie first, falling back to `Authorization: Bearer`
  for CLI/API clients
- **Opt-in via config** — `WIKIMIND_AUTH__ENABLED=false` by default
- **PyJWT** for token encoding/decoding (lightweight, no framework dependency)
- Auth middleware skips exempt paths (`/health`, `/docs`, `/auth/*`)
- User model stores provider identity (email, name, avatar) — no passwords stored
- **Vite proxy in dev** — all API/auth routes proxied to the backend so dev is
  single-origin (matching production); eliminates CORS and `FRONTEND_URL` hacks
- **`_callback_url()` reads Host header** — builds OAuth `redirect_uri` from the
  request's `Host` header instead of `request.url_for()`, which ignores proxies

### Cookie configuration

```
WIKIMIND_AUTH__COOKIE_NAME=wikimind_session   # cookie key
WIKIMIND_AUTH__COOKIE_SECURE=true             # false in dev (HTTP)
WIKIMIND_AUTH__COOKIE_DOMAIN=                 # unset = current host
```

`SameSite=Lax` + JSON `Content-Type` provides CSRF protection without a
separate CSRF token.

### Alternatives Considered

**API keys per user** — simpler but poor UX for a web app (no login flow).

**Managed auth (Auth0, Clerk)** — less code but adds external dependency and cost.

**JWT with email/password** — requires password hashing, email verification, reset
flows.

**JWT in localStorage (original implementation)** — vulnerable to XSS; any
injected script can call `localStorage.getItem("wikimind_token")` to steal the
session. HttpOnly cookies are immune because JavaScript cannot read them.

## Consequences

**Enables:**
- Multi-user deployments on a shared server
- Per-user data isolation depends on user identity from this decision
- XSS-resistant session management (HttpOnly cookies)
- CLI/API access via `Authorization: Bearer` header (backward compatible)
- Identical auth flow in dev and prod (single-origin via proxy)

**Constrains:**
- New `User` table and `AuthConfig` in Settings
- All routes remain accessible without auth when disabled (backward compatible)
- `COOKIE_SECURE=false` required in dev (HTTP); defaults to `true` for prod (HTTPS)
- Vite proxy config (`vite.config.ts`) must list all backend route prefixes
