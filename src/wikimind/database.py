"""Async database layer via SQLModel — supports both SQLite and PostgreSQL.

Metadata (sources, articles, jobs, costs) lives in the database.
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
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.db_compat import is_postgres, is_sqlite


def _create_engine_from_url(url: str):
    """Create an async engine appropriate for the database URL's dialect.

    SQLite: aiosqlite driver with check_same_thread=False.
    Postgres: asyncpg driver with connection pool tuning.

    Raises ValueError for unsupported dialects.
    """
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
        dialect = url.split("://", maxsplit=1)[0]
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
    if is_sqlite(url):
        db_dir = Path(settings.data_dir) / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
    return _create_engine_from_url(url)


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

    SQLite (dev/test): Uses create_all() + lightweight migration helpers.
    Postgres (production): Expects Alembic migrations to be run separately
    via ``alembic upgrade head``. Only runs backfill helpers.
    """
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
        # Lint report — additional columns
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
        # Issue #89 — conversation branching (fork-on-edit)
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
        # Issue #143 — schema overhaul Phase 1
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
        # PR #151 — backlink enforcer integration
        (
            "lintreport",
            "structural_count",
            "ALTER TABLE lintreport ADD COLUMN structural_count INTEGER NOT NULL DEFAULT 0",
        ),
        ("lintreport", "checked_articles", "ALTER TABLE lintreport ADD COLUMN checked_articles INTEGER"),
    ]
    indexes: list[tuple[str, str]] = [
        # (index name, CREATE fragment)
        (
            "ix_source_content_hash",
            "CREATE INDEX IF NOT EXISTS ix_source_content_hash ON source (content_hash)",
        ),
        (
            "ix_conversation_parent_id",
            "CREATE INDEX IF NOT EXISTS ix_conversation_parent_id ON conversation (parent_conversation_id)",
        ),
    ]

    def _get_existing_columns(sync_conn, table_name: str) -> set[str]:
        inspector = sa_inspect(sync_conn)
        if table_name not in inspector.get_table_names():
            return set()
        return {col["name"] for col in inspector.get_columns(table_name)}

    async with engine.begin() as conn:
        for table, column, alter_sql in additions:
            existing = await conn.run_sync(lambda sync_conn, t=table: _get_existing_columns(sync_conn, t))
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
            return sync_conn.execute(
                sa_text("SELECT id, question, created_at, filed_article_id FROM query WHERE conversation_id IS NULL")
            ).fetchall()

        legacy_rows = await conn.run_sync(_select_legacy)

        for row in legacy_rows:
            query_id, question, created_at_raw, filed_article_id = row
            conv_id = str(uuid.uuid4())
            title = (question or "")[:title_max]
            # SQLite stores datetimes as strings via SQLModel; reuse the raw value if present
            created_at = created_at_raw or utcnow_naive().isoformat()

            await conn.execute(
                sa_text(
                    "INSERT INTO conversation (id, title, created_at, updated_at, filed_article_id) "
                    "VALUES (:id, :title, :created_at, :updated_at, :filed_article_id)"
                ),
                {
                    "id": conv_id,
                    "title": title,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "filed_article_id": filed_article_id,
                },
            )
            await conn.execute(
                sa_text("UPDATE query SET conversation_id = :conv_id, turn_index = 0 WHERE id = :qid"),
                {"conv_id": conv_id, "qid": query_id},
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

        # Recalculate article counts
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


async def _migrate_to_relative_paths(session: AsyncSession) -> None:
    """Convert absolute file_path values to relative paths.

    Runs once at startup. Idempotent -- already-relative paths are skipped.
    """
    from wikimind.models import Article, Source  # noqa: PLC0415

    settings = get_settings()
    wiki_prefix = str(Path(settings.data_dir) / "wiki") + "/"
    raw_prefix = str(Path(settings.data_dir) / "raw") + "/"

    # Migrate Article.file_path (wiki-relative)
    result = await session.execute(select(Article).where(Article.file_path.startswith("/")))  # type: ignore[union-attr]
    for article in result.scalars().all():
        if article.file_path.startswith(wiki_prefix):
            article.file_path = article.file_path[len(wiki_prefix) :]
            session.add(article)

    # Migrate Source.file_path (raw-relative)
    result = await session.execute(select(Source).where(Source.file_path.startswith("/")))  # type: ignore[union-attr,arg-type]
    for source in result.scalars().all():
        if source.file_path and source.file_path.startswith(raw_prefix):
            source.file_path = source.file_path[len(raw_prefix) :]
            session.add(source)

    await session.commit()


async def close_db():
    """Close database connections. Called on app shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
