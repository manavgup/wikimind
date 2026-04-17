# Postgres Compatibility Implementation Plan (PR 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the database layer work on both SQLite (dev) and Postgres (production) with zero application logic changes. Dev defaults to SQLite. Production uses Postgres via `WIKIMIND_DATABASE_URL`.

**Architecture:** A `database_url` setting in `Settings` replaces the hardcoded SQLite URL. Engine creation branches on the URL scheme: SQLite gets `aiosqlite` + `check_same_thread=False` (current behavior); Postgres gets `asyncpg` + connection pooling. The `PRAGMA table_info` migration is replaced with SQLAlchemy `Inspector.get_columns()`. SQLite-specific queries (`json_each`, `.contains()` on JSON-as-TEXT) are wrapped in dialect-aware helpers. Alembic is configured for Postgres schema management. Seven TEXT columns storing JSON are converted to `sa_type=JSON`.

**Tech Stack:** Python 3.11+, SQLModel, SQLAlchemy (Inspector, JSON type), asyncpg, Alembic, pytest

**Depends on:** PR 1 (FileStorage Abstraction) must be merged first.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/wikimind/config.py` | Add `database_url` field to Settings |
| Modify | `src/wikimind/database.py` | Dialect-aware engine creation, Inspector-based migration |
| Modify | `src/wikimind/models.py` | Convert 7 TEXT columns to `sa_type=JSON` |
| Modify | `src/wikimind/services/wiki.py` | Replace `json_each()` with dialect-aware helper |
| Modify | `src/wikimind/engine/compiler.py` | Replace `.contains()` with dialect-aware JSON query |
| Modify | `pyproject.toml` | Add `asyncpg` dependency and `postgres` marker |
| Create | `src/wikimind/db_compat.py` | Dialect detection helpers and JSON query builders |
| Create | `tests/unit/test_db_compat.py` | Tests for dialect-aware helpers |
| Create | `tests/unit/test_postgres_engine.py` | Tests for engine creation logic |
| Create | `alembic.ini` | Alembic configuration |
| Create | `alembic/env.py` | Alembic environment with async support |
| Create | `alembic/script.py.mako` | Alembic migration template |
| Create | `alembic/versions/0001_initial_schema.py` | Initial migration from SQLModel definitions |
| Create | `docs/adr/adr-021-postgres-compatibility.md` | ADR for Postgres compatibility |
| Modify | `docs/adr/adr-001-fastapi-async-sqlite.md` | Amend to note Postgres support |
| Modify | `.env.example` | Add `WIKIMIND_DATABASE_URL` |
| Modify | `README.md` | Add Postgres setup section |

---

### Task 1: Add database_url to Settings

**Files:**
- Modify: `src/wikimind/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write test for database_url default**

Append to `tests/unit/test_config.py`:

```python
# Append to tests/unit/test_config.py

class TestDatabaseUrl:
    def test_default_database_url_is_sqlite(self, _isolated_data_dir):
        """database_url defaults to an aiosqlite URL under data_dir."""
        settings = get_settings()
        expected = f"sqlite+aiosqlite:///{settings.data_dir}/db/wikimind.db"
        assert settings.database_url == expected

    def test_database_url_from_env(self, monkeypatch, _isolated_data_dir):
        """database_url can be overridden via environment variable."""
        monkeypatch.setenv("WIKIMIND_DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/wikimind")
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.database_url == "postgresql+asyncpg://user:pass@localhost/wikimind"
        get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && .venv/bin/pytest tests/unit/test_config.py::TestDatabaseUrl -v`
Expected: FAIL -- `AttributeError: 'Settings' object has no attribute 'database_url'`

- [ ] **Step 3: Add database_url field to Settings**

In `src/wikimind/config.py`, add the field to the `Settings` class (after line 190, the `data_dir` field):

```python
    # Database URL — defaults to SQLite in data_dir. Set to a Postgres URL
    # (postgresql+asyncpg://...) for production. See ADR-021.
    database_url: str = ""

    @model_validator(mode="after")
    def _default_database_url(self) -> Settings:
        """Set database_url default after data_dir is resolved."""
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir}/db/wikimind.db"
        return self
```

Note: The default must be computed in a validator because it depends on `data_dir`. An empty string field with a post-validator is the cleanest Pydantic pattern for this.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_config.py::TestDatabaseUrl -v`
Expected: 2 tests PASS

- [ ] **Step 5: Run full config test suite for regression**

Run: `.venv/bin/pytest tests/unit/test_config.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/config.py tests/unit/test_config.py
git commit -s -m "feat(config): add database_url setting with SQLite default"
```

---

### Task 2: Create dialect detection helpers

**Files:**
- Create: `src/wikimind/db_compat.py`
- Create: `tests/unit/test_db_compat.py`

- [ ] **Step 1: Write tests for dialect helpers**

```python
# tests/unit/test_db_compat.py
"""Tests for database dialect compatibility helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

from wikimind.db_compat import (
    is_sqlite,
    is_postgres,
    get_dialect_name,
    json_array_contains,
    json_array_elements_query,
)


class TestDialectDetection:
    def test_sqlite_url_detected(self):
        assert is_sqlite("sqlite+aiosqlite:///path/to/db") is True
        assert is_postgres("sqlite+aiosqlite:///path/to/db") is False

    def test_postgres_url_detected(self):
        assert is_postgres("postgresql+asyncpg://user:pass@localhost/db") is True
        assert is_sqlite("postgresql+asyncpg://user:pass@localhost/db") is False

    def test_in_memory_sqlite_detected(self):
        assert is_sqlite("sqlite+aiosqlite://") is True

    def test_get_dialect_name(self):
        assert get_dialect_name("sqlite+aiosqlite:///foo") == "sqlite"
        assert get_dialect_name("postgresql+asyncpg://localhost/db") == "postgresql"


class TestJsonArrayContains:
    def test_sqlite_uses_like(self):
        """For SQLite, json_array_contains uses LIKE with the needle."""
        clause = json_array_contains("sqlite", "source_ids", "src-123")
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        # Should produce a LIKE '%"src-123"%' pattern
        assert "LIKE" in sql_str.upper() or "like" in sql_str

    def test_postgres_uses_jsonb_contains(self):
        """For Postgres, json_array_contains uses the @> operator."""
        clause = json_array_contains("postgresql", "source_ids", "src-123")
        sql_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "@>" in sql_str or "?" in sql_str  # JSONB containment
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_db_compat.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'wikimind.db_compat'`

- [ ] **Step 3: Implement db_compat module**

```python
# src/wikimind/db_compat.py
"""Database dialect compatibility helpers.

Provides functions that generate dialect-appropriate SQL fragments for
operations that differ between SQLite and PostgreSQL: JSON array querying,
column introspection, and engine configuration.

SQLite uses json_each() and LIKE-based JSON searching.
PostgreSQL uses jsonb_array_elements_text() and the @> operator.
"""

from __future__ import annotations

from sqlalchemy import Column, literal_column, text
from sqlalchemy.sql import ClauseElement
from sqlmodel import select


def get_dialect_name(url: str) -> str:
    """Extract the dialect name from a database URL.

    Returns 'sqlite' or 'postgresql' (never the driver suffix).
    """
    scheme = url.split("://")[0].split("+")[0]
    return scheme


def is_sqlite(url: str) -> bool:
    """Return True if the URL targets a SQLite database."""
    return get_dialect_name(url) == "sqlite"


def is_postgres(url: str) -> bool:
    """Return True if the URL targets a PostgreSQL database."""
    return get_dialect_name(url) in ("postgresql", "postgres")


def json_array_contains(dialect: str, column_name: str, value: str) -> ClauseElement:
    """Build a WHERE clause that checks if a JSON array column contains a value.

    SQLite: column LIKE '%"value"%' (TEXT-based search, matches current behavior)
    PostgreSQL: column::jsonb @> '["value"]'::jsonb (native JSONB containment)
    """
    if dialect == "postgresql":
        import json as json_mod

        return text(f"{column_name}::jsonb @> :val::jsonb").bindparams(val=json_mod.dumps([value]))
    else:
        # SQLite: LIKE-based search matching the existing .contains() pattern
        needle = f'"{value}"'
        return literal_column(column_name).contains(needle)


def json_array_elements_subquery(dialect: str, table_name: str, column_name: str, value_alias: str = "elem"):
    """Build a subquery that unnests a JSON array column for filtering.

    SQLite: SELECT ... FROM table, json_each(table.column)
    PostgreSQL: SELECT ... FROM table, jsonb_array_elements_text(table.column::jsonb) AS elem

    Returns a tuple of (from_clause_text, value_column_ref) for use in
    constructing WHERE ... IN subqueries.
    """
    if dialect == "postgresql":
        from_clause = f"{table_name}, jsonb_array_elements_text({table_name}.{column_name}::jsonb) AS {value_alias}"
        value_ref = literal_column(value_alias)
    else:
        from_clause = f"{table_name}, json_each({table_name}.{column_name})"
        value_ref = literal_column("json_each.value")
    return text(from_clause), value_ref
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_db_compat.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/db_compat.py tests/unit/test_db_compat.py
git commit -s -m "feat(db): add dialect compatibility helpers for SQLite/Postgres"
```

---

### Task 3: Dialect-aware engine creation

**Files:**
- Modify: `src/wikimind/database.py`
- Create: `tests/unit/test_postgres_engine.py`

- [ ] **Step 1: Write tests for engine creation**

```python
# tests/unit/test_postgres_engine.py
"""Tests for dialect-aware engine creation in database.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wikimind.database import _create_engine_from_url


class TestCreateEngineFromUrl:
    def test_sqlite_url_creates_aiosqlite_engine(self):
        """SQLite URL produces an engine with check_same_thread=False."""
        engine = _create_engine_from_url("sqlite+aiosqlite:///tmp/test.db")
        assert "sqlite" in str(engine.url)
        engine.dispose()

    def test_sqlite_in_memory_works(self):
        """In-memory SQLite URL works."""
        engine = _create_engine_from_url("sqlite+aiosqlite://")
        assert "sqlite" in str(engine.url)
        engine.dispose()

    def test_postgres_url_creates_asyncpg_engine(self):
        """Postgres URL produces an engine with pool settings.

        We can not actually connect without a running Postgres instance,
        but we can verify the engine is created with the right URL.
        """
        url = "postgresql+asyncpg://user:pass@localhost:5432/wikimind"
        engine = _create_engine_from_url(url)
        assert "postgresql" in str(engine.url)
        assert engine.pool.size() == 10  # pool_size=10
        engine.dispose()

    def test_unknown_dialect_raises(self):
        """An unsupported database URL raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported database dialect"):
            _create_engine_from_url("mysql+aiomysql://localhost/db")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_postgres_engine.py -v`
Expected: FAIL -- `ImportError: cannot import name '_create_engine_from_url'`

- [ ] **Step 3: Refactor database.py to be dialect-aware**

Replace `get_db_path()` and `get_engine()` in `src/wikimind/database.py` (lines 30-41) with:

```python
def _create_engine_from_url(url: str):
    """Create an async engine appropriate for the database URL's dialect.

    SQLite: aiosqlite driver with check_same_thread=False.
    Postgres: asyncpg driver with connection pool tuning.

    Raises ValueError for unsupported dialects.
    """
    from wikimind.db_compat import is_postgres, is_sqlite

    if is_sqlite(url):
        return create_async_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    elif is_postgres(url):
        return create_async_engine(
            url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    else:
        dialect = url.split("://")[0]
        raise ValueError(f"Unsupported database dialect: {dialect}. Use sqlite+aiosqlite or postgresql+asyncpg.")


def get_db_path() -> Path:
    """Return the path to the SQLite database file.

    Only meaningful when using the SQLite backend. Ensures the parent
    directory exists.
    """
    settings = get_settings()
    db_dir = Path(settings.data_dir) / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "wikimind.db"


def get_engine():
    """Create a new async database engine from settings."""
    settings = get_settings()
    url = settings.database_url
    # Ensure SQLite directory exists
    from wikimind.db_compat import is_sqlite
    if is_sqlite(url):
        db_dir = Path(settings.data_dir) / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
    return _create_engine_from_url(url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_postgres_engine.py -v`
Expected: All tests PASS (the Postgres pool_size assertion may need adjustment if asyncpg is not installed -- see Step 5)

- [ ] **Step 5: Add asyncpg dependency to pyproject.toml**

In `pyproject.toml`, add `asyncpg` to the `dependencies` list (after `aiosqlite`):

```toml
    # Database
    "sqlmodel>=0.0.21",
    "aiosqlite>=0.20.0",
    "asyncpg>=0.30.0",
```

Also add an `alembic` dependency:

```toml
    "alembic>=1.14.0",
```

Add a `postgres` marker to pytest:

```toml
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "e2e: end-to-end tests requiring full stack",
    "external: tests that call external APIs",
    "postgres: tests that require a running PostgreSQL instance",
]
```

Run: `.venv/bin/pip install -e ".[dev]"` to install the new dependency.

- [ ] **Step 6: Run full test suite for regression**

Run: `.venv/bin/pytest tests/unit/test_database.py tests/unit/test_postgres_engine.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/database.py pyproject.toml tests/unit/test_postgres_engine.py
git commit -s -m "feat(db): dialect-aware engine creation for SQLite and Postgres"
```

---

### Task 4: Replace PRAGMA table_info with Inspector API

**Files:**
- Modify: `src/wikimind/database.py` (function `_migrate_added_columns`, lines 106-201)

- [ ] **Step 1: Write test for Inspector-based migration**

Add to `tests/unit/test_database.py`:

```python
# Append to tests/unit/test_database.py

from wikimind.database import _migrate_added_columns


class TestMigrateAddedColumnsInspector:
    """Verify _migrate_added_columns works with Inspector API (not PRAGMA)."""

    async def test_migration_adds_missing_columns(self, async_engine):
        """Migration adds columns that exist in the model but not on disk.

        Uses the in-memory SQLite engine which already has all columns
        from create_all(). This test verifies the Inspector path is
        idempotent (no errors when all columns already exist).
        """
        # Should not raise — all columns already present
        await _migrate_added_columns(async_engine)

    async def test_migration_is_idempotent(self, async_engine):
        """Running migration twice causes no errors."""
        await _migrate_added_columns(async_engine)
        await _migrate_added_columns(async_engine)
```

- [ ] **Step 2: Run tests to verify they pass with current code**

Run: `.venv/bin/pytest tests/unit/test_database.py::TestMigrateAddedColumnsInspector -v`
Expected: PASS (current PRAGMA-based code works on SQLite)

- [ ] **Step 3: Replace PRAGMA with Inspector API**

Replace the `_migrate_added_columns` function body (lines 106-201) in `src/wikimind/database.py`:

```python
async def _migrate_added_columns(engine) -> None:
    """Add missing columns to existing tables (idempotent).

    Uses SQLAlchemy's Inspector API to check existing columns, which
    works on both SQLite and PostgreSQL. Runs ALTER TABLE ADD COLUMN
    for any column declared in the SQLModel definitions that isn't
    already on disk.

    Currently tracks:
        - source.content_hash (issue #67) + index
        - article.provider    (issue #67)
        - query.conversation_id (ADR-011)
        - query.turn_index    (ADR-011)
        - article.page_type   (issue #143)
        - backlink.relation_type + resolution columns (issue #143)
        - concept.concept_kind (issue #143)
    """
    from sqlalchemy import inspect as sa_inspect

    additions: list[tuple[str, str, str]] = [
        # (table, column, ALTER fragment)
        ("source", "content_hash", "ALTER TABLE source ADD COLUMN content_hash TEXT"),
        ("article", "provider", "ALTER TABLE article ADD COLUMN provider TEXT"),
        (
            "query",
            "conversation_id",
            "ALTER TABLE query ADD COLUMN conversation_id TEXT REFERENCES conversation(id)",
        ),
        ("query", "turn_index", "ALTER TABLE query ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"),
        (
            "lintreport",
            "missing_pages_count",
            "ALTER TABLE lintreport ADD COLUMN missing_pages_count INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "lintreport",
            "dismissed_count",
            "ALTER TABLE lintreport ADD COLUMN dismissed_count INTEGER NOT NULL DEFAULT 0",
        ),
        ("lintreport", "total_pairs", "ALTER TABLE lintreport ADD COLUMN total_pairs INTEGER NOT NULL DEFAULT 0"),
        ("lintreport", "checked_pairs", "ALTER TABLE lintreport ADD COLUMN checked_pairs INTEGER NOT NULL DEFAULT 0"),
        (
            "conversation",
            "parent_conversation_id",
            "ALTER TABLE conversation ADD COLUMN parent_conversation_id TEXT REFERENCES conversation(id)",
        ),
        (
            "conversation",
            "forked_at_turn_index",
            "ALTER TABLE conversation ADD COLUMN forked_at_turn_index INTEGER",
        ),
        ("article", "page_type", "ALTER TABLE article ADD COLUMN page_type TEXT NOT NULL DEFAULT 'source'"),
        (
            "backlink",
            "relation_type",
            "ALTER TABLE backlink ADD COLUMN relation_type TEXT NOT NULL DEFAULT 'references'",
        ),
        ("backlink", "resolution", "ALTER TABLE backlink ADD COLUMN resolution TEXT"),
        ("backlink", "resolution_note", "ALTER TABLE backlink ADD COLUMN resolution_note TEXT"),
        ("backlink", "resolved_at", "ALTER TABLE backlink ADD COLUMN resolved_at TEXT"),
        ("backlink", "resolved_by", "ALTER TABLE backlink ADD COLUMN resolved_by TEXT"),
        ("concept", "concept_kind", "ALTER TABLE concept ADD COLUMN concept_kind TEXT NOT NULL DEFAULT 'topic'"),
        (
            "lintreport",
            "structural_count",
            "ALTER TABLE lintreport ADD COLUMN structural_count INTEGER NOT NULL DEFAULT 0",
        ),
        ("lintreport", "checked_articles", "ALTER TABLE lintreport ADD COLUMN checked_articles INTEGER"),
    ]
    indexes: list[tuple[str, str]] = [
        (
            "ix_source_content_hash",
            "CREATE INDEX IF NOT EXISTS ix_source_content_hash ON source (content_hash)",
        ),
        (
            "ix_conversation_parent_id",
            "CREATE INDEX IF NOT EXISTS ix_conversation_parent_id ON conversation (parent_conversation_id)",
        ),
    ]

    async with engine.begin() as conn:
        # Use Inspector to get existing column names (works on both SQLite and Postgres)
        def _get_existing_columns(sync_conn, table_name: str) -> set[str]:
            inspector = sa_inspect(sync_conn)
            if table_name not in inspector.get_table_names():
                return set()
            return {col["name"] for col in inspector.get_columns(table_name)}

        for table, column, alter_sql in additions:
            existing = await conn.run_sync(lambda sync_conn, t=table: _get_existing_columns(sync_conn, t))
            if column not in existing:
                await conn.exec_driver_sql(alter_sql)
        for _name, create_sql in indexes:
            await conn.exec_driver_sql(create_sql)
```

- [ ] **Step 4: Run tests to verify Inspector-based migration works**

Run: `.venv/bin/pytest tests/unit/test_database.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/database.py tests/unit/test_database.py
git commit -s -m "refactor(db): replace PRAGMA table_info with SQLAlchemy Inspector API

Inspector.get_columns() works on both SQLite and PostgreSQL, removing
the last SQLite-only system call from the migration helper."
```

---

### Task 5: Convert parameterized SQL from ? to :named placeholders

**Files:**
- Modify: `src/wikimind/database.py`

The `?` positional placeholder is SQLite-specific. PostgreSQL uses `$1, $2` and SQLAlchemy's `text()` uses `:name`. Converting raw `exec_driver_sql` calls to use `text()` with named parameters makes them dialect-agnostic.

- [ ] **Step 1: Refactor _backfill_conversation_for_legacy_queries**

In `src/wikimind/database.py`, replace the `exec_driver_sql` calls in `_backfill_conversation_for_legacy_queries` (lines 235-242) with SQLAlchemy `text()`:

```python
async def _backfill_conversation_for_legacy_queries(engine) -> None:
    """Create a Conversation row for any Query that has NULL conversation_id.

    Idempotent: re-running finds zero NULL rows and is a no-op.
    See ADR-011.
    """
    from sqlalchemy import text as sa_text

    settings = get_settings()
    title_max = settings.qa.conversation_title_max_chars

    async with engine.begin() as conn:

        def _select_legacy(sync_conn):
            return sync_conn.execute(
                sa_text("SELECT id, question, created_at, filed_article_id FROM query WHERE conversation_id IS NULL")
            ).fetchall()

        legacy_rows = await conn.run_sync(_select_legacy)

        for row in legacy_rows:
            query_id, question, created_at_raw, filed_article_id = row
            conv_id = str(uuid.uuid4())
            title = (question or "")[:title_max]
            created_at = created_at_raw or utcnow_naive().isoformat()

            await conn.execute(
                sa_text(
                    "INSERT INTO conversation (id, title, created_at, updated_at, filed_article_id) "
                    "VALUES (:id, :title, :created_at, :updated_at, :filed_article_id)"
                ),
                {"id": conv_id, "title": title, "created_at": created_at, "updated_at": created_at, "filed_article_id": filed_article_id},
            )
            await conn.execute(
                sa_text("UPDATE query SET conversation_id = :conv_id, turn_index = 0 WHERE id = :qid"),
                {"conv_id": conv_id, "qid": query_id},
            )
```

- [ ] **Step 2: Refactor _backfill_concepts_from_articles**

Replace the `exec_driver_sql` calls in `_backfill_concepts_from_articles` (lines 359-408) similarly with `text()` and named parameters:

```python
async def _backfill_concepts_from_articles(engine) -> None:
    """Create missing Concept rows and recalculate counts. Idempotent."""
    from sqlalchemy import text as sa_text

    async with engine.begin() as conn:

        def _select_articles(sync_conn):
            return sync_conn.execute(
                sa_text("SELECT id, concept_ids FROM article WHERE concept_ids IS NOT NULL")
            ).fetchall()

        rows = await conn.run_sync(_select_articles)
        all_names, article_concepts = _collect_concept_names(rows)

        if not all_names:
            return

        def _select_existing_concepts(sync_conn):
            return sync_conn.execute(sa_text("SELECT name FROM concept")).fetchall()

        existing_rows = await conn.run_sync(_select_existing_concepts)
        existing_names = {row[0] for row in existing_rows}

        for normalized, raw_name in all_names.items():
            if normalized not in existing_names:
                concept_id = str(uuid.uuid4())
                await conn.execute(
                    sa_text(
                        "INSERT INTO concept (id, name, description, article_count, created_at) "
                        "VALUES (:id, :name, :desc, 0, :created_at)"
                    ),
                    {"id": concept_id, "name": normalized, "desc": raw_name, "created_at": utcnow_naive().isoformat()},
                )

        counts: dict[str, int] = {}
        for names in article_concepts:
            for name in names:
                counts[name] = counts.get(name, 0) + 1

        for normalized, count in counts.items():
            await conn.execute(
                sa_text("UPDATE concept SET article_count = :count WHERE name = :name"),
                {"count": count, "name": normalized},
            )

        unreferenced = (existing_names | set(all_names.keys())) - set(counts.keys())
        for name in unreferenced:
            await conn.execute(
                sa_text("UPDATE concept SET article_count = 0 WHERE name = :name"),
                {"name": name},
            )
```

- [ ] **Step 3: Refactor _repair_malformed_json_arrays**

Replace the `exec_driver_sql` calls in `_repair_malformed_json_arrays` (lines 270-296):

```python
async def _repair_malformed_json_arrays(engine) -> None:
    """Fix concept_ids and source_ids rows containing malformed JSON. Idempotent."""
    from sqlalchemy import text as sa_text

    async with engine.begin() as conn:

        def _select_articles(sync_conn):
            return sync_conn.execute(
                sa_text(
                    "SELECT id, concept_ids, source_ids FROM article"
                    " WHERE concept_ids IS NOT NULL OR source_ids IS NOT NULL"
                )
            ).fetchall()

        rows = await conn.run_sync(_select_articles)

        for row in rows:
            article_id, concept_ids, source_ids = row
            repaired_concepts = _repair_json_array(concept_ids) if concept_ids else None
            repaired_sources = _repair_json_array(source_ids) if source_ids else None

            if repaired_concepts is not None or repaired_sources is not None:
                new_concepts = repaired_concepts if repaired_concepts is not None else concept_ids
                new_sources = repaired_sources if repaired_sources is not None else source_ids
                await conn.execute(
                    sa_text("UPDATE article SET concept_ids = :concepts, source_ids = :sources WHERE id = :id"),
                    {"concepts": new_concepts, "sources": new_sources, "id": article_id},
                )
```

- [ ] **Step 4: Add the `text` import at module level**

At the top of `src/wikimind/database.py`, add to the existing imports:

```python
from sqlalchemy import text as sa_text
```

Then replace the `from sqlalchemy import text as sa_text` in each function body with the module-level import. The inline imports in the function bodies above are written defensively -- once the module-level import is added, remove the per-function imports.

- [ ] **Step 5: Run tests to verify no regression**

Run: `.venv/bin/pytest tests/unit/test_database.py -v`
Expected: All tests PASS (the repair + backfill tests exercise these code paths)

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/database.py
git commit -s -m "refactor(db): convert raw SQL from ? placeholders to :named params

Named parameters via SQLAlchemy text() are dialect-agnostic. SQLite's ?
placeholders only work with exec_driver_sql which bypasses the
SQLAlchemy engine layer."
```

---

### Task 6: Replace json_each() and .contains() with dialect-aware helpers

**Files:**
- Modify: `src/wikimind/services/wiki.py` (lines 246-251)
- Modify: `src/wikimind/engine/compiler.py` (lines 306-308)

- [ ] **Step 1: Write test for concept-filtered article listing**

The existing test suite for `wiki.py` should cover this. Verify by running:

Run: `.venv/bin/pytest tests/unit/test_wiki_service.py -v -k "concept"`
If no concept-filtered test exists, add one to `tests/unit/test_wiki_service.py`:

```python
# Append to tests/unit/test_wiki_service.py (if not already present)

async def test_list_articles_by_concept_filter(db_session):
    """list_articles with concept filter returns matching articles."""
    from wikimind.models import Article, ConfidenceLevel
    import json

    article = Article(
        slug="concept-test",
        title="Concept Test",
        file_path="concept-test.md",
        concept_ids=json.dumps(["machine-learning", "deep-learning"]),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(article)
    await db_session.commit()

    service = WikiService()
    results = await service.list_articles(session=db_session, concept="machine-learning")
    assert len(results) >= 1
    assert any(r.slug == "concept-test" for r in results)
```

- [ ] **Step 2: Refactor wiki.py json_each to use db_compat**

In `src/wikimind/services/wiki.py`, replace lines 246-251 (the concept filter in `list_articles`):

```python
# At the top of wiki.py, add import:
from wikimind.db_compat import json_array_elements_subquery, is_sqlite
from wikimind.config import get_settings

# Replace lines 246-251 in list_articles:
        if concept:
            settings = get_settings()
            dialect = "sqlite" if is_sqlite(settings.database_url) else "postgresql"
            from_clause, value_ref = json_array_elements_subquery(dialect, "article", "concept_ids")
            query = query.where(
                literal_column("article.id").in_(
                    select(literal_column("article.id"))
                    .select_from(from_clause)
                    .where(value_ref == concept)
                )
            )
```

- [ ] **Step 3: Refactor compiler.py .contains() to use db_compat**

In `src/wikimind/engine/compiler.py`, replace lines 306-308 (the `_find_article_for_source_and_provider` method):

```python
    async def _find_article_for_source_and_provider(
        self,
        session: AsyncSession,
        source_id: str,
        provider: Provider | None,
    ) -> Article | None:
        """Find an article previously compiled from this source by this provider."""
        if provider is None:
            return None
        from wikimind.config import get_settings
        from wikimind.db_compat import is_sqlite, json_array_contains

        settings = get_settings()
        dialect = "sqlite" if is_sqlite(settings.database_url) else "postgresql"
        needle = f'"{source_id}"'
        if dialect == "postgresql":
            clause = json_array_contains(dialect, "source_ids", source_id)
            result = await session.execute(select(Article).where(clause))
        else:
            result = await session.execute(
                select(Article).where(Article.source_ids.contains(needle))  # type: ignore[union-attr]
            )
        for article in result.scalars().all():
            if article.provider == provider:
                return article
        return None
```

- [ ] **Step 4: Run tests to verify no regression**

Run: `.venv/bin/pytest tests/unit/test_wiki_service.py tests/unit/test_engine_compiler.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/services/wiki.py src/wikimind/engine/compiler.py
git commit -s -m "refactor(db): replace json_each() and .contains() with dialect-aware helpers

wiki.py now uses json_array_elements_subquery() which generates
json_each() for SQLite and jsonb_array_elements_text() for Postgres.
compiler.py uses json_array_contains() for the same dual-dialect
support."
```

---

### Task 7: Convert JSON-as-TEXT columns to sa_type=JSON

**Files:**
- Modify: `src/wikimind/models.py`

This task changes 7 fields from plain `str | None` TEXT columns to proper `sa_type=JSON` columns. SQLAlchemy's `JSON` type maps to `TEXT` on SQLite (with automatic JSON serialization) and `JSONB` on PostgreSQL. This is transparent to application code because SQLModel will automatically serialize/deserialize Python lists and dicts.

**Important:** This is a schema change. Existing SQLite databases store these as TEXT containing JSON strings. With `sa_type=JSON` on SQLite, SQLAlchemy still stores them as TEXT but expects them to be raw JSON, not double-encoded strings. The existing data is already raw JSON strings, so no data migration is needed -- SQLAlchemy's JSON type on SQLite simply passes through TEXT values and parses them via json.loads on read.

- [ ] **Step 1: Write test verifying JSON round-trip**

Add to `tests/unit/test_models.py`:

```python
# Append to tests/unit/test_models.py
import json

from sqlmodel import select

from wikimind.models import Article, ConfidenceLevel, ConceptKindDef, Query, LintPairCache


class TestJsonColumns:
    """Verify JSON columns round-trip Python objects through SQLModel."""

    async def test_article_concept_ids_round_trip(self, db_session):
        """Article.concept_ids stores and retrieves a Python list."""
        concepts = ["machine-learning", "deep-learning"]
        article = Article(
            slug="json-test",
            title="JSON Test",
            file_path="json-test.md",
            concept_ids=json.dumps(concepts),
            source_ids=json.dumps(["src-1"]),
            confidence=ConfidenceLevel.SOURCED,
        )
        db_session.add(article)
        await db_session.commit()

        result = await db_session.execute(select(Article).where(Article.slug == "json-test"))
        loaded = result.scalar_one()
        # With sa_type=JSON, the value comes back as a Python list on Postgres
        # and as a JSON string on SQLite. Both are valid.
        if isinstance(loaded.concept_ids, str):
            assert json.loads(loaded.concept_ids) == concepts
        else:
            assert loaded.concept_ids == concepts

    async def test_query_source_article_ids_round_trip(self, db_session):
        """Query.source_article_ids stores and retrieves a JSON array."""
        ids = ["art-1", "art-2"]
        q = Query(
            question="test?",
            answer="yes",
            source_article_ids=json.dumps(ids),
        )
        db_session.add(q)
        await db_session.commit()

        result = await db_session.execute(select(Query).where(Query.id == q.id))
        loaded = result.scalar_one()
        if isinstance(loaded.source_article_ids, str):
            assert json.loads(loaded.source_article_ids) == ids
        else:
            assert loaded.source_article_ids == ids
```

- [ ] **Step 2: Run tests to verify they pass with current TEXT columns**

Run: `.venv/bin/pytest tests/unit/test_models.py::TestJsonColumns -v`
Expected: PASS (current TEXT columns store JSON strings fine)

- [ ] **Step 3: Convert columns to sa_type=JSON**

In `src/wikimind/models.py`, add the import:

```python
from sqlalchemy import JSON
```

Then change these field definitions:

**Article.concept_ids** (line 149):
```python
    concept_ids: str | None = Field(default=None, sa_type=JSON)  # JSON array of concept IDs
```

**Article.source_ids** (line 155):
```python
    source_ids: str | None = Field(default=None, sa_type=JSON)  # JSON array of source IDs
```

**ConceptKindDef.required_sections** (line 176):
```python
    required_sections: str = Field(sa_type=JSON)  # JSON array
```

**ConceptKindDef.linter_rules** (line 177):
```python
    linter_rules: str = Field(sa_type=JSON)  # JSON array
```

**Query.source_article_ids** (line 235):
```python
    source_article_ids: str | None = Field(default=None, sa_type=JSON)  # JSON array
```

**Query.related_article_ids** (line 236):
```python
    related_article_ids: str | None = Field(default=None, sa_type=JSON)  # JSON array
```

**LintPairCache.result_json** (line 617):
```python
    result_json: str = Field(sa_type=JSON)  # JSON list of contradiction dicts
```

**Note on Python types:** The Python type annotations remain `str | None` (or `str`) because existing application code calls `json.loads()` / `json.dumps()` on these fields. Changing the Python type to `list | None` would require updating every read/write site simultaneously. The `sa_type=JSON` annotation only affects the DDL (generating `JSONB` on Postgres instead of `TEXT`). On SQLite, the JSON type still stores TEXT. On Postgres, it enables JSONB operators (`@>`, `jsonb_array_elements_text`).

- [ ] **Step 4: Run tests to verify JSON columns work**

Run: `.venv/bin/pytest tests/unit/test_models.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full test suite for regression**

Run: `.venv/bin/pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/models.py tests/unit/test_models.py
git commit -s -m "feat(models): convert 7 JSON-as-TEXT columns to sa_type=JSON

Uses SQLAlchemy JSON type which maps to TEXT on SQLite (no behavior
change) and JSONB on PostgreSQL (enables native JSON operators).
Fields: Article.concept_ids, Article.source_ids,
ConceptKindDef.required_sections, ConceptKindDef.linter_rules,
Query.source_article_ids, Query.related_article_ids,
LintPairCache.result_json."
```

---

### Task 8: Set up Alembic for Postgres migrations

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial_schema.py`
- Modify: `src/wikimind/database.py` (conditional Alembic vs create_all)

- [ ] **Step 1: Create alembic.ini**

```ini
# alembic.ini
[alembic]
script_location = alembic
# URL is overridden at runtime by env.py reading Settings.database_url
sqlalchemy.url = sqlite+aiosqlite:///placeholder.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Create alembic/env.py with async support**

```python
# alembic/env.py
"""Alembic environment for async migrations.

Reads database_url from WikiMind settings. Supports both SQLite (offline
mode) and PostgreSQL (async online mode).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine
from sqlmodel import SQLModel

# Import all models so metadata is populated
from wikimind import models  # noqa: F401
from wikimind.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def get_url() -> str:
    """Read database URL from WikiMind settings."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL script."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Run migrations with a live connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async 'online' mode."""
    url = get_url()
    connectable = create_async_engine(url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations — delegates to async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Create alembic/script.py.mako**

```mako
# alembic/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create initial migration**

Generate the initial migration by running:

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind
.venv/bin/alembic revision --autogenerate -m "initial schema from SQLModel definitions" --rev-id 0001
```

Review the generated file in `alembic/versions/0001_initial_schema_from_sqlmodel_definitions.py` and verify it creates all tables matching the SQLModel definitions.

- [ ] **Step 5: Modify init_db to skip lightweight migration on Postgres**

In `src/wikimind/database.py`, modify `init_db()`:

```python
async def init_db():
    """Create all tables and run idempotent column migrations.

    SQLite (dev/test): Uses create_all() + lightweight migration helpers.
    Postgres (production): Expects Alembic migrations to be run separately
    via `alembic upgrade head`. Only runs backfill helpers.
    """
    from wikimind.db_compat import is_sqlite

    engine = get_async_engine()
    settings = get_settings()

    if is_sqlite(settings.database_url):
        # SQLite: create_all + lightweight column migration (fast, no Alembic overhead)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        await _migrate_added_columns(engine)
    # else: Postgres uses Alembic — tables must exist before startup.
    # Run `alembic upgrade head` as part of deployment.

    # Backfill helpers run on both dialects
    await _backfill_conversation_for_legacy_queries(engine)
    await _repair_malformed_json_arrays(engine)
    await _backfill_concepts_from_articles(engine)

    # Convert absolute file paths to relative (idempotent)
    async with get_session_factory()() as session:
        await _migrate_to_relative_paths(session)
```

- [ ] **Step 6: Run full test suite (SQLite path)**

Run: `.venv/bin/pytest -v`
Expected: All tests PASS (tests use SQLite, so create_all path is exercised)

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/ src/wikimind/database.py
git commit -s -m "feat(db): add Alembic migration system for Postgres

Alembic handles schema migrations for Postgres deployments.
SQLite continues using create_all() + lightweight migration helpers
for zero-overhead dev/test. init_db() branches based on dialect."
```

---

### Task 9: ADRs and documentation

**Files:**
- Create: `docs/adr/adr-021-postgres-compatibility.md`
- Modify: `docs/adr/adr-001-fastapi-async-sqlite.md`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Create ADR-021**

```markdown
# ADR-021: PostgreSQL compatibility for production deployments

## Status

Accepted

## Context

WikiMind was built as a local-first application with SQLite (ADR-001). As we
add cloud deployment support (see design spec: cloud-deployment-design.md),
production instances need a shared database that multiple devices can connect to
concurrently. SQLite's single-writer limitation and file-based storage make it
unsuitable for this use case.

## Decision

Make the database layer dialect-aware so it works on both SQLite (dev/test) and
PostgreSQL (production) with zero application logic changes.

**Configuration:** A single `WIKIMIND_DATABASE_URL` setting selects the backend.
It defaults to `sqlite+aiosqlite:///{data_dir}/db/wikimind.db` so the zero-
dependency dev experience is unchanged.

**Engine creation:** The URL scheme determines the async driver and connection
parameters. SQLite uses `aiosqlite` with `check_same_thread=False`. PostgreSQL
uses `asyncpg` with connection pooling (`pool_size=10`, `max_overflow=20`,
`pool_pre_ping=True`).

**Schema management:** SQLite uses `create_all()` plus lightweight column
migration helpers (fast, no Alembic overhead). PostgreSQL uses Alembic with an
initial migration generated from SQLModel definitions. Deployments run
`alembic upgrade head` before starting the server.

**Query compatibility:** SQLite-specific constructs are replaced with
dialect-aware helpers:
- `PRAGMA table_info` → `Inspector.get_columns()` (SQLAlchemy)
- `json_each()` → `jsonb_array_elements_text()` (via helper function)
- `.contains()` on TEXT → `@>` on JSONB (via helper function)
- `?` positional params → `:named` params (SQLAlchemy `text()`)

**Column types:** Seven JSON-as-TEXT columns gain `sa_type=JSON`, which maps to
TEXT on SQLite (no change) and JSONB on PostgreSQL (enables native operators).

## Alternatives Considered

**Full Alembic for both dialects** — Adds overhead to dev startup and test runs
for no benefit. SQLite's `create_all()` is instantaneous and perfectly reliable
for ephemeral dev databases.

**Separate PostgreSQL-specific models** — Would duplicate the entire model layer
and create a maintenance burden.

**CockroachDB** — Wire-compatible with PostgreSQL but adds operational complexity
and cost for a single-user system.

## Consequences

**Enables:**
- Production deployment to any managed Postgres service (Supabase, Neon, RDS)
- Multiple devices sharing the same database
- Future horizontal scaling if needed

**Constrains:**
- Raw SQL must use named parameters (`:name`) instead of positional (`?`)
- New queries involving JSON arrays must use the `db_compat` helpers
- PostgreSQL deployments require running Alembic migrations before startup

**Risks:**
- Dialect-specific bugs that only surface in one backend; mitigated by running
  the full test suite on both SQLite and (in CI) PostgreSQL
```

- [ ] **Step 2: Amend ADR-001**

Append to `docs/adr/adr-001-fastapi-async-sqlite.md`:

```markdown

## Amendment (2026-04-17): PostgreSQL support added

As of ADR-021, the database layer is dialect-aware. SQLite remains the default
for development and testing (zero-dependency startup principle unchanged).
Production deployments can use PostgreSQL by setting `WIKIMIND_DATABASE_URL` to a
`postgresql+asyncpg://` URL.

The constraint noted above — "If WikiMind ever becomes multi-user, SQLite will
need to be replaced with Postgres" — is now addressed for the shared-backend
multi-device use case, though WikiMind remains single-user.
```

- [ ] **Step 3: Update .env.example**

Add the following section to `.env.example` after the existing `# Database (optional)` section (replace the existing database section):

```bash
# ----------------------------------------------------------------------------
# Database (optional)
# ----------------------------------------------------------------------------
# Defaults to SQLite at ~/.wikimind/db/wikimind.db. Override for Postgres:
# WIKIMIND_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/wikimind
#
# For Postgres, run `alembic upgrade head` before first startup.
#
# Verbose SQL query logging — dev only, very noisy
# WIKIMIND_DATABASE__ECHO=false
```

- [ ] **Step 4: Update README.md**

Add a section after the existing "Quick start" section:

```markdown
## Production (PostgreSQL)

For shared access across multiple devices, use PostgreSQL instead of SQLite:

```bash
# 1. Set the database URL in .env
echo 'WIKIMIND_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/wikimind' >> .env

# 2. Run Alembic migrations (first time only, and after upgrades)
alembic upgrade head

# 3. Start the server
make dev
```

All features work identically on both backends. SQLite is recommended for
single-device development. PostgreSQL is required for cloud deployments where
multiple devices share the same database.
```

- [ ] **Step 5: Commit**

```bash
git add docs/adr/adr-021-postgres-compatibility.md docs/adr/adr-001-fastapi-async-sqlite.md .env.example README.md
git commit -s -m "docs: add ADR-021 (Postgres compatibility), update docs and .env.example"
```

---

### Task 10: Postgres integration tests (skipped without Postgres)

**Files:**
- Create: `tests/integration/test_postgres_integration.py`

- [ ] **Step 1: Write Postgres integration tests**

```python
# tests/integration/test_postgres_integration.py
"""Integration tests for PostgreSQL backend.

Skipped automatically when WIKIMIND_TEST_POSTGRES_URL is not set.
To run: export WIKIMIND_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@localhost:5432/wikimind_test
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from wikimind.db_compat import is_postgres
from wikimind.models import Article, ConfidenceLevel, Query, Source, SourceType

POSTGRES_URL = os.environ.get("WIKIMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="WIKIMIND_TEST_POSTGRES_URL not set"),
]


@pytest.fixture
async def pg_engine():
    """Create a Postgres engine and tables for testing, drop after."""
    engine = create_async_engine(POSTGRES_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine) -> AsyncSession:
    """Async session backed by Postgres test database."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


class TestPostgresBasicOperations:
    async def test_create_and_read_source(self, pg_session):
        """Basic CRUD works on Postgres."""
        source = Source(source_type=SourceType.URL, source_url="https://example.com")
        pg_session.add(source)
        await pg_session.commit()

        result = await pg_session.execute(select(Source).where(Source.id == source.id))
        loaded = result.scalar_one()
        assert loaded.source_url == "https://example.com"

    async def test_json_column_round_trip(self, pg_session):
        """JSON columns store and retrieve Python objects on Postgres."""
        concepts = ["ai", "ml"]
        article = Article(
            slug="pg-json-test",
            title="PG JSON",
            file_path="pg-json-test.md",
            concept_ids=json.dumps(concepts),
            source_ids=json.dumps(["src-1"]),
            confidence=ConfidenceLevel.SOURCED,
        )
        pg_session.add(article)
        await pg_session.commit()

        result = await pg_session.execute(select(Article).where(Article.slug == "pg-json-test"))
        loaded = result.scalar_one()
        # On Postgres with JSONB, SQLAlchemy returns Python objects directly
        if isinstance(loaded.concept_ids, list):
            assert loaded.concept_ids == concepts
        else:
            assert json.loads(loaded.concept_ids) == concepts

    async def test_query_with_json_fields(self, pg_session):
        """Query model JSON fields work on Postgres."""
        q = Query(
            question="What is AI?",
            answer="Artificial Intelligence",
            source_article_ids=json.dumps(["art-1"]),
            related_article_ids=json.dumps(["art-2"]),
        )
        pg_session.add(q)
        await pg_session.commit()

        result = await pg_session.execute(select(Query).where(Query.id == q.id))
        loaded = result.scalar_one()
        assert loaded.question == "What is AI?"


class TestPostgresMigrationHelpers:
    async def test_inspector_migration_on_postgres(self, pg_engine):
        """_migrate_added_columns runs without error on Postgres."""
        from wikimind.database import _migrate_added_columns

        # All columns already exist from create_all — should be a no-op
        await _migrate_added_columns(pg_engine)

    async def test_backfill_concepts_on_postgres(self, pg_engine, pg_session):
        """_backfill_concepts_from_articles works with named params on Postgres."""
        from wikimind.database import _backfill_concepts_from_articles

        article = Article(
            slug="pg-backfill",
            title="PG Backfill",
            file_path="pg-backfill.md",
            concept_ids=json.dumps(["new-concept"]),
            confidence=ConfidenceLevel.SOURCED,
        )
        pg_session.add(article)
        await pg_session.commit()

        await _backfill_concepts_from_articles(pg_engine)
```

- [ ] **Step 2: Verify tests are skipped without Postgres**

Run: `.venv/bin/pytest tests/integration/test_postgres_integration.py -v`
Expected: All tests SKIPPED (no `WIKIMIND_TEST_POSTGRES_URL` set)

- [ ] **Step 3: Verify tests pass with Postgres (if available)**

If a local Postgres is available:
```bash
export WIKIMIND_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/wikimind_test
createdb wikimind_test 2>/dev/null || true
.venv/bin/pytest tests/integration/test_postgres_integration.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_postgres_integration.py
git commit -s -m "test: add Postgres integration tests (skipped without WIKIMIND_TEST_POSTGRES_URL)"
```

---

### Task 11: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind
.venv/bin/pytest -v
```

Expected: All tests PASS

- [ ] **Step 2: Run linter**

```bash
.venv/bin/ruff check src/ tests/
```

Expected: No errors

- [ ] **Step 3: Verify SQLite default behavior is unchanged**

```bash
.venv/bin/python -c "
from wikimind.config import get_settings
s = get_settings()
print(f'database_url: {s.database_url}')
assert 'sqlite+aiosqlite' in s.database_url
print('OK: SQLite default verified')
"
```

- [ ] **Step 4: Verify Alembic can generate SQL**

```bash
.venv/bin/alembic upgrade head --sql
```

Expected: Prints SQL DDL for the initial migration

---

## Summary of all commits in order

1. `feat(config): add database_url setting with SQLite default`
2. `feat(db): add dialect compatibility helpers for SQLite/Postgres`
3. `feat(db): dialect-aware engine creation for SQLite and Postgres`
4. `refactor(db): replace PRAGMA table_info with SQLAlchemy Inspector API`
5. `refactor(db): convert raw SQL from ? placeholders to :named params`
6. `refactor(db): replace json_each() and .contains() with dialect-aware helpers`
7. `feat(models): convert 7 JSON-as-TEXT columns to sa_type=JSON`
8. `feat(db): add Alembic migration system for Postgres`
9. `docs: add ADR-021 (Postgres compatibility), update docs and .env.example`
10. `test: add Postgres integration tests (skipped without WIKIMIND_TEST_POSTGRES_URL)`

---

### Critical Files for Implementation
- `/Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/database.py`
- `/Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/config.py`
- `/Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/models.py`
- `/Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/services/wiki.py`
- `/Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/engine/compiler.py`
