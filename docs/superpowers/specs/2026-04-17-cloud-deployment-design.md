# Cloud Deployment — FileStorage Abstraction + Postgres + R2

## Problem

WikiMind is local-first: SQLite database + filesystem for .md and raw source files. This means a wiki built on one machine is inaccessible from another. Users who run WikiMind on multiple devices (laptop + desktop, dev + production) have no way to share state.

## Decision

Replace the sync engine approach (issues #28, #74) with a simpler shared-backend architecture. In production, all WikiMind instances connect to the same Postgres database and Cloudflare R2 bucket. No sync protocol, no offline queue, no conflict resolution needed.

Two modes, selected by config:

- **Dev (default):** SQLite + local filesystem. Current behavior, zero changes.
- **Production:** Postgres + R2. All devices share the same backend.

## What This Is Not

- Not a sync engine. There is no push/pull, no delta detection, no manifest.
- Not offline-capable in production mode. Production requires internet connectivity.
- Not multi-user. Single user, multiple devices, same credentials.

## Scope — 3 PRs

### PR 1: FileStorage Abstraction

Pure refactoring. Every direct `Path` read/write of wiki .md files and raw source files goes through a `FileStorage` protocol. Only `LocalFileStorage` is implemented — zero behavior change.

**Interface:**

```python
class FileStorage(Protocol):
    async def read(self, relative_path: str) -> str: ...
    async def read_bytes(self, relative_path: str) -> bytes: ...
    async def write(self, relative_path: str, content: str) -> None: ...
    async def write_bytes(self, relative_path: str, data: bytes) -> None: ...
    async def append(self, relative_path: str, content: str) -> None: ...
    async def delete(self, relative_path: str) -> None: ...
    async def exists(self, relative_path: str) -> bool: ...
    async def list(self, prefix: str = "") -> list[str]: ...
```

**`LocalFileStorage`** wraps current `Path` I/O with `asyncio.to_thread()` for a consistent async interface. Two singleton factories:
- `get_wiki_storage()` — root = `~/.wikimind/wiki/`
- `get_raw_storage()` — root = `~/.wikimind/raw/`

**~19 call sites across these files:**

Wiki storage (11 sites): `engine/compiler.py`, `engine/concept_compiler.py`, `engine/qa_agent.py`, `services/wiki_index.py`, `services/activity_log.py`, `services/wiki.py`, `engine/linter/contradictions.py`, `engine/frontmatter_validator.py`, `jobs/sweep.py`, `jobs/worker.py`

Raw storage (6 sites): `ingest/service.py` (URL/PDF/text/YouTube ingest + cleanup), `jobs/worker.py` (compile/recompile source reads)

### PR 2: Postgres Compatibility

Make the database layer dialect-aware. Dev defaults to SQLite. Production uses Postgres.

**Changes:**

1. **Config:** Add `database_url` to Settings (defaults to SQLite path). Remove hardcoded URL from `database.py`.

2. **Engine creation:** Conditional based on URL scheme:
   - SQLite: `aiosqlite` driver + `check_same_thread=False`
   - Postgres: `asyncpg` driver + connection pool (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`)

3. **Migration system:** Replace `PRAGMA table_info()` (SQLite-only) with SQLAlchemy `Inspector` API. Set up Alembic for Postgres. Keep `create_all()` for dev/test SQLite.

4. **SQLite-specific queries:**
   - `services/wiki.py:247-248` — `json_each()` → dialect-aware `jsonb_array_elements_text()` for Postgres
   - `engine/compiler.py:308` — `.contains()` on JSON-as-TEXT → proper JSONB `@>` for Postgres

5. **Schema improvements:** Convert JSON-as-TEXT columns to `sa_type=JSON` where beneficial.

6. **New dependency:** `asyncpg`

**ADRs:** Create ADR-021 (Postgres compatibility). Amend ADR-001 (async SQLite) to note Postgres support.

### PR 3: R2 Storage Backend + Cloud Deployment

**`R2FileStorage`** implements `FileStorage` using `boto3` (S3-compatible):
- `read/read_bytes` → `s3.get_object()`
- `write/write_bytes` → `s3.put_object()`
- `delete` → `s3.delete_object()`
- `exists` → `s3.head_object()`
- `list` → `s3.list_objects_v2()`
- `append` → read + append + write (R2 has no native append)

All boto3 calls wrapped in `asyncio.to_thread()`.

**Config additions:**
- `WIKIMIND_STORAGE_BACKEND` — `local` (default) or `r2`
- `WIKIMIND_R2_BUCKET` — bucket name
- `WIKIMIND_R2_ENDPOINT_URL` — R2 endpoint
- Uses existing `aws_access_key_id` / `aws_secret_access_key` fields

**Factory selection:**
```python
def get_wiki_storage() -> FileStorage:
    if settings.storage_backend == "r2":
        return R2FileStorage(bucket, endpoint_url, prefix="wiki/")
    return LocalFileStorage(wiki_dir)
```

**Auth:** Postgres credentials + R2 keys in `.env`. No user-facing auth — single-user, credentials = device identity.

**Deployment:** Docker image works with any Postgres + S3-compatible storage. Documented options: Supabase/Neon (Postgres) + Cloudflare R2 (files) + Fly.io/Railway (compute).

**ADRs:** Create ADR-020 (cloud storage abstraction). Amend ADR-004 (markdown files + SQLite) to note R2 support.

## Issues Affected

- **#28** (Cloud sync service) — Simplified from sync service to shared backend. Infrastructure portion still relevant.
- **#74** (Sync engine) — Can be closed. No sync engine needed with shared backend approach.
- **#29** (Settings UI) — Sync status panel already exists (read-only). Can show connection status to Postgres/R2 in production mode.

## Verification

**PR 1:** `make dev` → ingest PDF → .md files in `~/.wikimind/wiki/` as before. All tests pass.

**PR 2:** SQLite default works unchanged. `DATABASE_URL=postgresql+asyncpg://...` → ingest + query works. Alembic `upgrade head` creates tables.

**PR 3:** `STORAGE_BACKEND=local` → unchanged. `STORAGE_BACKEND=r2` → files in R2. Second device with same config sees same wiki.
