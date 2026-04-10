"""Async SQLite database layer via SQLModel and aiosqlite.

Metadata (sources, articles, jobs, costs) lives in SQLite.
Article content (.md files) lives in the filesystem under ~/.wikimind/wiki/.

Session lifecycle
-----------------
``get_session`` is a FastAPI dependency that yields a session with
commit-on-success / rollback-on-error semantics.  The caller never needs
to call ``session.commit()`` for read-only work; writes are committed
automatically when the request handler returns without raising.  Any
exception — including connection errors — triggers a rollback so the
session is always left in a clean state.
"""

import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from slugify import slugify
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings


def get_db_path() -> Path:
    """Return the path to the SQLite database file."""
    settings = get_settings()
    db_dir = Path(settings.data_dir) / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "wikimind.db"


def get_engine():
    """Create a new async database engine."""
    db_path = get_db_path()
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})


_engine = None
_session_factory = None


def get_async_engine():
    """Return the singleton async engine."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def get_session_factory():
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_async_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session with commit/rollback lifecycle.

    On success the session is committed so that any pending writes are
    flushed.  On any exception — including ``SQLAlchemyError`` connection
    errors — the session is rolled back and the exception re-raised.
    """
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables and run idempotent column migrations.

    `SQLModel.metadata.create_all` creates fresh tables from the current
    SQLModel definitions but does not add new columns to pre-existing
    tables. We follow it with `_migrate_added_columns` which inspects the
    live schema and runs `ALTER TABLE` for any column the model declares
    that isn't already present. This is the project's lightweight
    alternative to Alembic and is safe to call on every startup.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await _migrate_added_columns(engine)
    await _backfill_conversation_for_legacy_queries(engine)
    await _repair_malformed_json_arrays(engine)
    await _backfill_concepts_from_articles(engine)


async def _migrate_added_columns(engine) -> None:
    """Add missing columns to existing tables (idempotent).

    Inspects each tracked table via `PRAGMA table_info` and runs
    `ALTER TABLE ... ADD COLUMN` for any column declared in the SQLModel
    definitions that isn't already on disk. SQLite-specific because the
    project is single-file SQLite — that assumption is documented in
    ADR-001.

    Currently tracks:
        - source.content_hash (issue #67) + index
        - article.provider    (issue #67)
        - query.conversation_id (ADR-011)
        - query.turn_index    (ADR-011)
    """
    additions: list[tuple[str, str, str]] = [
        # (table, column, ALTER fragment)
        ("source", "content_hash", "ALTER TABLE source ADD COLUMN content_hash TEXT"),
        ("article", "provider", "ALTER TABLE article ADD COLUMN provider TEXT"),
        # ADR-011 — conversation grouping for Q&A turns
        (
            "query",
            "conversation_id",
            "ALTER TABLE query ADD COLUMN conversation_id TEXT REFERENCES conversation(id)",
        ),
        ("query", "turn_index", "ALTER TABLE query ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"),
    ]
    indexes: list[tuple[str, str]] = [
        # (index name, CREATE fragment)
        (
            "ix_source_content_hash",
            "CREATE INDEX IF NOT EXISTS ix_source_content_hash ON source (content_hash)",
        ),
    ]

    async with engine.begin() as conn:
        for table, column, alter_sql in additions:
            existing = await conn.run_sync(
                lambda sync_conn, t=table: {
                    row[1] for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({t})").fetchall()
                }
            )
            if column not in existing:
                await conn.exec_driver_sql(alter_sql)
        for _name, create_sql in indexes:
            await conn.exec_driver_sql(create_sql)


async def _backfill_conversation_for_legacy_queries(engine) -> None:
    """Create a Conversation row for any Query that has NULL conversation_id.

    Idempotent: re-running finds zero NULL rows and is a no-op. Each
    legacy Query becomes a single-turn Conversation whose title is the
    question (truncated to qa.conversation_title_max_chars), whose
    timestamps mirror the Query's, and whose filed_article_id mirrors
    the Query's existing filed_article_id (so legacy file-back state
    is preserved).

    See ADR-011.
    """
    settings = get_settings()
    title_max = settings.qa.conversation_title_max_chars

    async with engine.begin() as conn:

        def _select_legacy(sync_conn):
            return sync_conn.exec_driver_sql(
                "SELECT id, question, created_at, filed_article_id FROM query WHERE conversation_id IS NULL"
            ).fetchall()

        legacy_rows = await conn.run_sync(_select_legacy)

        for row in legacy_rows:
            query_id, question, created_at_raw, filed_article_id = row
            conv_id = str(uuid.uuid4())
            title = (question or "")[:title_max]
            # SQLite stores datetimes as strings via SQLModel; reuse the raw value if present
            created_at = created_at_raw or utcnow_naive().isoformat()

            await conn.exec_driver_sql(
                "INSERT INTO conversation (id, title, created_at, updated_at, filed_article_id) VALUES (?, ?, ?, ?, ?)",
                (conv_id, title, created_at, created_at, filed_article_id),
            )
            await conn.exec_driver_sql(
                "UPDATE query SET conversation_id = ?, turn_index = 0 WHERE id = ?",
                (conv_id, query_id),
            )


def _repair_json_array(raw: str) -> str | None:
    """Attempt to repair a malformed JSON array string.

    The old serialiser produced strings like ``["a"b"c"]`` (missing commas).
    This function strips the outer ``[]``, splits on ``"``, filters empties,
    and re-serialises with :func:`json.dumps`.

    Returns the repaired JSON string, or ``None`` if *raw* is already valid.
    """
    try:
        json.loads(raw)
        return None  # already valid
    except (json.JSONDecodeError, TypeError):
        pass

    inner = raw.strip()
    if inner.startswith("["):
        inner = inner[1:]
    if inner.endswith("]"):
        inner = inner[:-1]

    items = [part for part in inner.split('"') if part.strip()]
    return json.dumps(items)


async def _repair_malformed_json_arrays(engine) -> None:
    """Fix ``concept_ids`` and ``source_ids`` rows containing malformed JSON.

    Idempotent: rows that already contain valid JSON are left untouched.
    See issue #112.
    """
    async with engine.begin() as conn:

        def _select_articles(sync_conn):
            return sync_conn.exec_driver_sql(
                "SELECT id, concept_ids, source_ids FROM article"
                " WHERE concept_ids IS NOT NULL OR source_ids IS NOT NULL"
            ).fetchall()

        rows = await conn.run_sync(_select_articles)

        for row in rows:
            article_id, concept_ids, source_ids = row
            repaired_concepts = _repair_json_array(concept_ids) if concept_ids else None
            repaired_sources = _repair_json_array(source_ids) if source_ids else None

            if repaired_concepts is not None or repaired_sources is not None:
                new_concepts = repaired_concepts if repaired_concepts is not None else concept_ids
                new_sources = repaired_sources if repaired_sources is not None else source_ids
                await conn.exec_driver_sql(
                    "UPDATE article SET concept_ids = ?, source_ids = ? WHERE id = ?",
                    (new_concepts, new_sources, article_id),
                )


def _parse_concept_names_from_json(raw: str) -> list[str]:
    """Parse and normalize concept names from a JSON array string.

    Returns a list of slugified concept names, filtering out empty values.
    """
    try:
        names = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(names, list):
        return []
    result = []
    for name in names:
        if not name:
            continue
        normalized = slugify(str(name))
        if normalized:
            result.append(normalized)
    return result


def _collect_concept_names(
    rows: list,
) -> tuple[dict[str, str], list[list[str]]]:
    """Collect normalized concept names from article rows.

    Returns a tuple of (all_names mapping, per-article normalized lists).
    """
    all_names: dict[str, str] = {}  # normalized -> first raw name seen
    article_concepts: list[list[str]] = []
    for row in rows:
        _article_id, concept_ids_raw = row
        normalized_names = _parse_concept_names_from_json(concept_ids_raw)
        article_concepts.append(normalized_names)
        for name in normalized_names:
            if name not in all_names:
                # Store the original raw value for the description
                try:
                    raw_list = json.loads(concept_ids_raw)
                    raw_match = next(
                        (str(n) for n in raw_list if slugify(str(n)) == name),
                        name,
                    )
                except (json.JSONDecodeError, TypeError):
                    raw_match = name
                all_names[name] = raw_match
    return all_names, article_concepts


async def _backfill_concepts_from_articles(engine) -> None:
    """Create missing Concept rows from articles' concept_ids and recalculate counts.

    Scans all articles, parses each ``concept_ids`` JSON array, and
    upserts a Concept row for each normalized name that does not already
    exist. Then recalculates ``article_count`` for every Concept.

    Idempotent: re-running finds all concepts already present and is a
    no-op for the insert path; the count recalculation is always safe.
    """
    async with engine.begin() as conn:

        def _select_articles(sync_conn):
            return sync_conn.exec_driver_sql(
                "SELECT id, concept_ids FROM article WHERE concept_ids IS NOT NULL"
            ).fetchall()

        rows = await conn.run_sync(_select_articles)
        all_names, article_concepts = _collect_concept_names(rows)

        if not all_names:
            return

        def _select_existing_concepts(sync_conn):
            return sync_conn.exec_driver_sql("SELECT name FROM concept").fetchall()

        existing_rows = await conn.run_sync(_select_existing_concepts)
        existing_names = {row[0] for row in existing_rows}

        for normalized, raw_name in all_names.items():
            if normalized not in existing_names:
                concept_id = str(uuid.uuid4())
                await conn.exec_driver_sql(
                    "INSERT INTO concept (id, name, description, article_count, created_at) VALUES (?, ?, ?, 0, ?)",
                    (
                        concept_id,
                        normalized,
                        raw_name,
                        utcnow_naive().isoformat(),
                    ),
                )

        # Recalculate article counts
        counts: dict[str, int] = {}
        for names in article_concepts:
            for name in names:
                counts[name] = counts.get(name, 0) + 1

        for normalized, count in counts.items():
            await conn.exec_driver_sql(
                "UPDATE concept SET article_count = ? WHERE name = ?",
                (count, normalized),
            )

        unreferenced = (existing_names | set(all_names.keys())) - set(counts.keys())
        for name in unreferenced:
            await conn.exec_driver_sql(
                "UPDATE concept SET article_count = 0 WHERE name = ?",
                (name,),
            )


async def close_db():
    """Close database connections. Called on app shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
