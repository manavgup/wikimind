# Multi-User WikiMind — Design Spec

## Problem

WikiMind is a single-user personal knowledge OS. Every table, route, storage path, and background job assumes one user. To scale to 100s of users on a shared server, we need authentication, per-user data isolation, scoped file storage, and scoped background jobs.

## Decisions

- **Auth**: OAuth2/SSO via Google and GitHub
- **Data isolation**: `user_id` FK on all tables, application-level filtering (no RLS)
- **LLM billing**: BYOK — each user brings their own API keys
- **File storage**: Per-user namespacing in local/R2 storage (`{user_id}/article-slug.md`)
- **Backward compatibility**: Existing single-user data migrated to a "default" user

## Architecture Overview

```
Browser → OAuth2 Login → JWT issued → Authorization header on every request
                                        ↓
                              Auth Middleware extracts user_id
                                        ↓
                              Route handler filters by user_id
                                        ↓
                              Storage namespaced by user_id
```

No shared LLM keys. No billing system. No Stripe. Each user configures their own Anthropic/OpenAI/Google key in Settings, stored encrypted per-user.

---

## PR 1: User Model + OAuth2 Auth

### New Table: `User`

```python
class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str | None = None
    avatar_url: str | None = None
    auth_provider: str  # "google" | "github"
    auth_provider_id: str  # provider's user ID
    created_at: datetime
    updated_at: datetime
```

### Config Additions

```python
class AuthConfig(BaseModel):
    enabled: bool = False
    jwt_secret_key: str = ""  # required when enabled
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
```

Added to Settings as `auth: AuthConfig = Field(default_factory=AuthConfig)`.

### Auth Flow

1. Frontend redirects to `/auth/login/google` (or `/github`)
2. Server redirects to provider's OAuth2 authorize URL
3. Provider redirects back to `/auth/callback?code=...&state=...`
4. Server exchanges code for access token, fetches user profile
5. Server upserts User row, issues JWT with `{"sub": user_id, "email": email}`
6. Frontend stores JWT in localStorage, sends via `Authorization: Bearer <token>`

### Auth Middleware

```python
class AuthMiddleware:
    async def __call__(self, request, call_next):
        if not settings.auth.enabled:
            # Single-user mode — skip auth, set a default user
            request.state.user = None
            return await call_next(request)

        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token:
            return JSONResponse(status_code=401, content={"error": "Missing token"})

        payload = jwt.decode(token, settings.auth.jwt_secret_key, ...)
        request.state.user = User(id=payload["sub"], email=payload["email"])
        return await call_next(request)
```

### Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/auth/login/{provider}` | GET | Redirect to OAuth2 provider |
| `/auth/callback` | GET | Handle OAuth2 callback, issue JWT |
| `/auth/me` | GET | Return current user profile |
| `/auth/logout` | POST | Invalidate token (client-side) |

### Backward Compatibility

When `auth.enabled = False` (default), `request.state.user` is `None`. All existing routes continue working without auth. PR 2 will use this to decide whether to filter by user_id.

### New Dependencies

- `PyJWT>=2.8.0` — JWT encoding/decoding
- `httpx` — already a dependency (used for OAuth2 token exchange)

---

## PR 2: Data Isolation — user_id FK on All Models

### Schema Changes

Add `user_id: str | None = Field(default=None, foreign_key="user.id", index=True)` to:

| Table | Notes |
|-------|-------|
| Source | Who ingested this source |
| Article | Who owns this article (slug unique per user, not globally) |
| Concept | Per-user concept taxonomy |
| Backlink | Follows article ownership |
| Conversation | Who started this conversation |
| Query | Follows conversation ownership |
| Job | Whose job |
| CostLog | Whose LLM spend |
| UserPreference | Per-user settings (key changes from global to per-user) |
| LintReport | Per-user lint runs |
| ContradictionFinding | Per-user |
| OrphanFinding | Per-user |
| StructuralFinding | Per-user |

### Unique Constraint Changes

- `Article.slug`: currently globally unique → change to `UniqueConstraint("user_id", "slug")`
- `Concept.name`: currently globally unique → change to `UniqueConstraint("user_id", "name")`

### FastAPI Dependency: `get_current_user`

```python
async def get_current_user(request: Request) -> User | None:
    """Extract current user from request state. Returns None in single-user mode."""
    return getattr(request.state, "user", None)

def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Require authentication. Raises 401 if no user."""
    if user is None:
        settings = get_settings()
        if settings.auth.enabled:
            raise HTTPException(status_code=401, detail="Authentication required")
    return user
```

### Route Handler Changes (every route)

Before:
```python
@router.get("/articles")
async def list_articles(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Article))
```

After:
```python
@router.get("/articles")
async def list_articles(
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_current_user),
):
    stmt = select(Article)
    if user:
        stmt = stmt.where(Article.user_id == user.id)
    result = await session.execute(stmt)
```

### Alembic Migration

1. Add `user_id` column to all tables (nullable, no FK constraint initially)
2. Create a "default" User row for existing single-user data
3. Backfill all existing rows: `UPDATE article SET user_id = '<default-user-id>'`
4. Add FK constraint and index
5. For Article: drop old unique index on slug, create composite unique on (user_id, slug)
6. For Concept: same treatment for name

### Per-User API Keys

Currently, API keys are stored globally in Settings (SecretStr fields) or OS keychain. For multi-user, keys must be per-user:

- Add `UserApiKey` table: `(user_id, provider, encrypted_key)`
- `get_api_key(provider)` gains a `user_id` parameter
- Keys encrypted at rest using `auth.jwt_secret_key` or a dedicated encryption key
- Settings page saves keys per-user, not globally

---

## PR 3: Per-User File Storage Namespacing

### Path Structure

Current:
```
~/.wikimind/wiki/article-slug.md
~/.wikimind/raw/source-id.txt
```

Multi-user:
```
~/.wikimind/wiki/{user_id}/article-slug.md
~/.wikimind/raw/{user_id}/source-id.txt
```

### Storage Interface Changes

```python
def get_wiki_storage(user_id: str | None = None) -> FileStorage:
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki"
    if user_id:
        root = root / user_id
    return LocalFileStorage(root=root)
```

Same pattern for `get_raw_storage()`.

### R2 Storage (revive PR #171)

Cherry-pick `R2FileStorage` from the `feat/r2-storage-backend` branch. Per-user namespacing via S3 prefix:

```python
class R2FileStorage:
    def __init__(self, bucket: str, prefix: str = ""):
        self.prefix = prefix  # e.g., "wiki/user-123/"
```

Factory:
```python
def get_wiki_storage(user_id: str | None = None) -> FileStorage:
    settings = get_settings()
    if settings.storage_backend == "r2":
        prefix = f"wiki/{user_id}/" if user_id else "wiki/"
        return R2FileStorage(bucket=settings.r2_bucket, prefix=prefix)
    else:
        root = Path(settings.data_dir) / "wiki"
        if user_id:
            root = root / user_id
        return LocalFileStorage(root=root)
```

### Migration

Alembic migration + startup script:
1. Create `wiki/{default-user-id}/` directory
2. Move all existing `wiki/*.md` files into it
3. Update `Article.file_path` in DB from `slug.md` to `{default-user-id}/slug.md`
4. Same for `raw/` directory and `Source.file_path`

---

## PR 4: Per-User Background Jobs + WebSocket Scoping

### Job Changes

- `Job.user_id` added (from PR 2)
- `schedule_compile(source_id, user_id)` — jobs carry user context
- Worker functions filter by user_id:

```python
async def compile_source(ctx, source_id: str, user_id: str):
    async with get_session_factory()() as session:
        source = await session.get(Source, source_id)
        if source.user_id != user_id:
            raise ValueError("Source does not belong to user")
        # ... compile
```

### Cron Jobs

```python
async def lint_all_users(ctx):
    """Weekly lint — iterate over active users."""
    async with get_session_factory()() as session:
        users = await session.execute(select(User))
        for user in users.scalars():
            await lint_wiki(ctx, user_id=user.id)
```

### WebSocket Scoping

Current: single global WebSocket at `/ws` broadcasts to all connections.

Multi-user: connections tagged with user_id.

```python
# In ws.py
connections: dict[str, set[WebSocket]] = {}  # user_id → connections

async def broadcast_to_user(user_id: str, event: dict):
    for ws in connections.get(user_id, set()):
        await ws.send_json(event)
```

Worker emits to specific user:
```python
emit_compilation_complete(user_id=source.user_id, article_title=...)
```

---

## PR 5: Frontend Auth UI

### New Components

- `LoginPage.tsx` — Google/GitHub login buttons
- `AuthProvider.tsx` — React context managing JWT token + user state
- `useAuth()` hook — `{ user, isAuthenticated, login, logout }`
- `ProtectedRoute.tsx` — wraps routes, redirects to /login if unauthenticated

### API Client Changes

```typescript
// api/client.ts
function apiFetch(url: string, options?: RequestInit) {
    const token = localStorage.getItem("wikimind_token");
    const headers = { ...options?.headers };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    return fetch(url, { ...options, headers });
}
```

### Layout Changes

- Header: user avatar + dropdown (settings, logout)
- If not authenticated: redirect to /login
- Login page: centered card with OAuth buttons

### Routes

```tsx
<Route path="/login" element={<LoginPage />} />
<Route path="/auth/callback" element={<AuthCallback />} />
// All other routes wrapped in <ProtectedRoute>
```

---

## What's NOT in Scope

- **Billing / Stripe** — users bring their own LLM keys
- **Admin panel** — no user management UI (manage via DB/API)
- **Rate limiting per user** — defer until needed
- **Email notifications** — not needed for v1
- **RBAC / permissions** — all users are equal; no admin/viewer roles
- **Multi-tenant org model** — no "teams" or "workspaces"
- **Real-time collaboration** — each user has their own wiki

---

## Dependency Chain

```
PR 1: User + OAuth2 Auth
  ↓
PR 2: Data Isolation (user_id FK)  ←  depends on User table from PR 1
  ↓
PR 3: Storage Namespacing          ←  depends on user_id from PR 2
  ↓
PR 4: Jobs + WebSocket Scoping     ←  depends on user_id from PR 2
  ↓
PR 5: Frontend Auth UI             ←  depends on auth routes from PR 1
```

PRs 3 and 4 can be developed in parallel after PR 2 lands.
PR 5 can start after PR 1 (doesn't need PR 2-4 for the UI itself).
