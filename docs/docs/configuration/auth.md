# Authentication

WikiMind supports optional multi-user mode with OAuth2 authentication via Google and GitHub.

## Overview

When authentication is **disabled** (default), WikiMind runs in single-user mode. No login is required and all routes are accessible.

When **enabled**, WikiMind uses a BFF (Backend-for-Frontend) cookie-based authentication pattern:

1. User clicks "Sign in with Google/GitHub" in the UI
2. The backend redirects to the OAuth2 provider
3. After authorization, the callback exchanges the code for a JWT
4. The JWT is stored in an HttpOnly secure cookie (`wikimind_session`)
5. All subsequent requests include the cookie automatically

## Enabling Authentication

Set these in your `.env`:

```bash
WIKIMIND_AUTH__ENABLED=true
WIKIMIND_AUTH__JWT_SECRET_KEY=your-random-secret-here
```

!!! warning "Generate a strong secret"
    The JWT secret key must be a random string. Generate one with:
    ```bash
    python3 -c "import secrets; print(secrets.token_hex(32))"
    ```

## Google OAuth2

### 1. Create credentials

Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials) and create an OAuth 2.0 Client ID:

- **Application type**: Web application
- **Authorized redirect URIs**: `http://localhost:7842/auth/callback/google` (dev) and your production URL

### 2. Configure

```bash
WIKIMIND_AUTH__GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET=your-client-secret
```

## GitHub OAuth2

### 1. Create an OAuth App

Go to [GitHub Developer Settings](https://github.com/settings/developers) and create a new OAuth App:

- **Homepage URL**: `http://localhost:7842` (dev) or your production URL
- **Authorization callback URL**: `http://localhost:7842/auth/callback/github`

### 2. Configure

```bash
WIKIMIND_AUTH__GITHUB_CLIENT_ID=your-client-id
WIKIMIND_AUTH__GITHUB_CLIENT_SECRET=your-client-secret
```

## Cookie Settings

The session cookie is configured for security:

| Setting | Default | Description |
|---|---|---|
| `WIKIMIND_AUTH__COOKIE_NAME` | `wikimind_session` | Cookie name |
| `WIKIMIND_AUTH__COOKIE_SECURE` | `true` | Require HTTPS (set to `false` for local HTTP dev) |
| `WIKIMIND_AUTH__COOKIE_DOMAIN` | -- | Cookie domain (None = current host; set for subdomains) |

For local development over HTTP:

```bash
WIKIMIND_AUTH__COOKIE_SECURE=false
```

## JWT Configuration

| Setting | Default | Description |
|---|---|---|
| `WIKIMIND_AUTH__JWT_ALGORITHM` | `HS256` | Signing algorithm |
| `WIKIMIND_AUTH__JWT_EXPIRY_MINUTES` | `1440` | Token expiry (24 hours) |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/auth/providers` | List available OAuth2 providers |
| GET | `/auth/login/{provider}` | Start OAuth2 flow (redirects to provider) |
| GET | `/auth/callback/{provider}` | OAuth2 callback (sets session cookie) |
| POST | `/auth/logout` | Logout (clears session cookie) |
| GET | `/auth/me` | Get current user info |

## Data Isolation

When authentication is enabled, all data is scoped by user ID:

- Each user sees only their own sources, articles, and conversations
- Wiki files are stored under `wiki/{user_id}/` on the filesystem
- The `get_current_user_id` dependency extracts the user from the session cookie

## Frontend Behavior

When auth is enabled:

- Unauthenticated users are redirected to `/login`
- The login page shows buttons for each configured OAuth2 provider
- After login, the user menu in the sidebar shows avatar, name, and logout button

When auth is disabled:

- No login page is shown
- All routes are accessible directly
