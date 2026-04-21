# Storage Backends

WikiMind uses a dual-storage architecture: a relational database for metadata and structured queries, and the filesystem (or object storage) for article content and raw source files.

## Database

### SQLite (Development)

The default for local development. The database file lives at `~/.wikimind/db/wikimind.db` and is created automatically on first startup.

- No setup required
- Single-file database, easy to reset (`make db-reset`)
- Async access via `aiosqlite` + SQLAlchemy async

### PostgreSQL (Production)

Required for cloud deployments and multi-device access. Set via:

```bash
WIKIMIND_DATABASE_URL=postgresql+asyncpg://localhost:5432/wikimind
```

Key differences from SQLite:

- Schema migrations managed by Alembic (`alembic upgrade head`)
- JSON queries use PostgreSQL-native operators instead of string `CONTAINS`
- SSL handling for managed providers (Fly.io internal Postgres, etc.)
- Connection pooling via SQLAlchemy async engine

WikiMind auto-detects the `DATABASE_URL` environment variable set by managed providers (Fly.io, Railway, Render, Heroku) and rewrites the URL for async compatibility.

### Dialect Compatibility

The codebase uses `db_compat` helpers to abstract dialect differences:

- `is_sqlite()` / `is_postgresql()` -- Detect the active backend
- `json_array_contains()` -- Cross-dialect JSON array search

## File Storage

### Local Filesystem

The default storage backend (`WIKIMIND_STORAGE_BACKEND=local`).

```
~/.wikimind/
├── raw/              # Original source files (immutable)
│   ├── {uuid}.txt    # Extracted text
│   ├── {uuid}.pdf    # Original PDF (when available)
│   └── {uuid}.html   # Original HTML
├── wiki/             # Compiled articles
│   ├── index.md      # Auto-maintained master index
│   └── {concept}/
│       └── {slug}.md # Article markdown with frontmatter
├── images/           # Extracted PDF images
│   └── {source_id}/
│       └── *.png
└── db/
    └── wikimind.db
```

Key points:

- **Raw files are immutable** -- Once saved, source files are never modified
- **Wiki files are regenerated** -- Recompilation replaces the `.md` file in place
- **User isolation** -- In multi-user mode, wiki files are stored under `wiki/{user_id}/`

### R2 Object Storage (planned)

The `WIKIMIND_STORAGE_BACKEND=r2` option delegates to Cloudflare R2. When using R2:

- `wiki_dir` and `raw_dir` properties are not used
- Files are read/written via the R2 API
- Local `db/` and `config/` directories are still created

## Session Lifecycle

Database sessions are managed via FastAPI's dependency injection:

```python
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
```

Route handlers receive a session via `Depends(get_session)`. The session is committed by the service layer and closed automatically when the request completes.

For background jobs and operations that need an independent transaction (e.g., cost logging), a separate session is created via `get_session_factory()()`.

## Multi-User Data Isolation

When authentication is enabled, all data is scoped by `user_id`:

- **Sources** -- `Source.user_id` filters ingested sources per user
- **Articles** -- `Article.user_id` isolates compiled articles
- **Conversations** -- `Conversation.user_id` and `Query.user_id` isolate Q&A
- **Wiki files** -- Stored under `wiki/{user_id}/` on the filesystem

The `get_current_user_id` dependency extracts the user ID from the JWT session cookie and passes it to the service layer for filtering.
