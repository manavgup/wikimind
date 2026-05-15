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

import functools
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import structlog
from slugify import slugify
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import wikimind.models  # noqa: F401 — register SQLModel tables in metadata
from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.db_compat import is_postgres, is_sqlite

log = structlog.get_logger()


def _dialect_insert(conn) -> Any:
    """Return the dialect-specific ``insert`` function for upsert support.

    SQLAlchemy's ``on_conflict_do_nothing()`` is only available on
    dialect-specific insert constructs, not the generic ``sqlalchemy.insert``.
    """
    import importlib  # noqa: PLC0415

    module_name = "sqlalchemy.dialects." + ("sqlite" if conn.dialect.name == "sqlite" else "postgresql")
    return importlib.import_module(module_name).insert


def _parse_ssl(url: str) -> tuple[str, dict]:
    """Strip sslmode/ssl from URL, return (clean_url, connect_args)."""
    if "sslmode=" not in url and "ssl=" not in url:
        return url, {}
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    mode = params.pop("sslmode", params.pop("ssl", ["prefer"]))[0]
    clean = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
    return clean, {"ssl": mode != "disable"}


def _create_engine_from_url(url: str):
    """Create an async engine appropriate for the database URL's dialect.

    SQLite: aiosqlite driver with check_same_thread=False.
    Postgres: asyncpg driver with connection pool tuning.

    Raises ValueError for unsupported dialects.
    """
    if is_sqlite(url):
        return create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    if is_postgres(url):
        url, connect_args = _parse_ssl(url)
        # Disable asyncpg's prepared-statement cache.  Fly.io Postgres
        # uses PgBouncer in transaction-pooling mode, which can reassign
        # backend connections between requests.  Cached statements from
        # one backend are invalid on another, causing
        # InvalidCachedStatementError.
        connect_args["statement_cache_size"] = 0
        return create_async_engine(
            url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    dialect = url.split("://", maxsplit=1)[0]
    msg = f"Unsupported dialect: {dialect}. Use sqlite+aiosqlite or postgresql+asyncpg."
    raise ValueError(msg)


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


@functools.lru_cache(maxsize=1)
def get_async_engine():
    """Return the singleton async engine."""
    return get_engine()


@functools.lru_cache(maxsize=1)
def get_session_factory():
    """Return the singleton session factory."""
    return async_sessionmaker(get_async_engine(), class_=AsyncSession, expire_on_commit=False)


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
        except Exception:  # Intentional broad catch — ensure rollback for any error
            await session.rollback()
            raise


async def _migration_applied(engine, version: str) -> bool:
    """Check whether the given migration version has already been recorded."""
    async with engine.begin() as conn:

        def _check(sync_conn):
            inspector = sa_inspect(sync_conn)
            if "migrationhistory" not in inspector.get_table_names():
                return False
            row = sync_conn.execute(
                sa_text("SELECT 1 FROM migrationhistory WHERE version = :v"),
                {"v": version},
            ).fetchone()
            return row is not None

        return await conn.run_sync(_check)


async def _record_migration(engine, version: str) -> None:
    """Record a migration version as applied (idempotent).

    Uses INSERT ... ON CONFLICT DO NOTHING so concurrent Gunicorn workers
    racing to record the same migration don't cause UniqueViolationError.
    """
    from wikimind.models import MigrationHistory  # noqa: PLC0415

    async with engine.begin() as conn:
        _insert = _dialect_insert(conn)
        stmt = _insert(MigrationHistory).values(version=version, applied_at=utcnow_naive()).on_conflict_do_nothing()
        await conn.execute(stmt)
    log.info("migration applied", version=version)


async def _ensure_anonymous_user(engine) -> None:
    """Create the 'anonymous' user row if it doesn't exist.

    When auth is disabled, ``get_current_user_id()`` returns ``"anonymous"``.
    Tables with ``user_id`` FK constraints need this row to exist.

    Uses INSERT ... ON CONFLICT DO NOTHING instead of check-then-insert
    to avoid TOCTOU races when multiple Gunicorn workers start simultaneously.
    """
    from wikimind.api.deps import ANONYMOUS_USER_ID  # noqa: PLC0415
    from wikimind.models import User  # noqa: PLC0415

    async with engine.begin() as conn:
        _insert = _dialect_insert(conn)
        stmt = (
            _insert(User)
            .values(
                id=ANONYMOUS_USER_ID,
                email="anonymous@localhost",
                name="Anonymous",
                auth_provider="none",
                auth_provider_id="anonymous",
            )
            .on_conflict_do_nothing()
        )
        result = await conn.execute(stmt)
        if result.rowcount:
            log.info("created anonymous user for no-auth mode")


async def _run_versioned_migrations(engine, versioned_migrations, session_migrations) -> None:
    """Execute versioned data migrations, skipping already-applied ones."""
    for version, migration_fn in versioned_migrations:
        if await _migration_applied(engine, version):
            continue
        if version in session_migrations:
            async with get_session_factory()() as session:
                await session_migrations[version](session)
        else:
            await migration_fn(engine)
        await _record_migration(engine, version)


async def init_db():
    """Create all tables and run idempotent data migrations.

    ``create_all()`` runs on both SQLite and Postgres (idempotent).
    Schema evolution is handled by Alembic; ``create_all`` ensures
    internal tables (e.g. migrationhistory) exist on first boot.

    Each data migration is guarded by a MigrationHistory version check so
    it runs at most once, avoiding O(n) startup scans on subsequent boots.
    """
    engine = get_async_engine()

    # create_all is idempotent — safe on both SQLite and Postgres.
    # Alembic handles schema evolution but create_all ensures
    # internal tables (e.g. migrationhistory) exist on first boot.
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Ensure the "anonymous" user row exists so FK constraints are satisfied
    # when auth is disabled (get_current_user_id returns "anonymous").
    await _ensure_anonymous_user(engine)

    # Create FTS virtual table for full-text search (idempotent).
    from wikimind.services.search import create_fts_table, rebuild_fts_index  # noqa: PLC0415

    await create_fts_table(engine)

    # Rebuild the FTS index if the table is empty but articles exist.
    # This ensures existing articles are searchable after first deploy
    # or if the FTS table was recreated.
    if not is_postgres(get_settings().database_url):
        async with get_session_factory()() as fts_session:
            fts_count = await fts_session.execute(sa_text("SELECT count(*) FROM article_fts"))
            fts_rows = fts_count.scalar() or 0

            article_count = await fts_session.execute(sa_text("SELECT count(*) FROM article"))
            article_rows = article_count.scalar() or 0

            if fts_rows == 0 and article_rows > 0:
                log.info(
                    "FTS index empty but articles exist, rebuilding",
                    article_count=article_rows,
                )
                await rebuild_fts_index(fts_session)

    # Versioned data migrations — each runs at most once.
    # On Postgres, use an advisory lock to serialize concurrent workers.
    _versioned_migrations: list[tuple[str, object]] = [
        ("0001_backfill_conversations", _backfill_conversation_for_legacy_queries),
        ("0002_repair_json_arrays", _repair_malformed_json_arrays),
        ("0003_backfill_concepts", _backfill_concepts_from_articles),
        ("0004_relative_paths", None),  # handled separately (needs session)
        ("0005_backfill_join_tables", _backfill_join_tables_from_json),
        ("0006_cleanup_orphan_concepts", None),  # handled separately (needs session)
    ]

    # Migrations that need a full AsyncSession (SQLModel ORM) instead of raw SQL
    _session_migrations = {
        "0004_relative_paths": _migrate_to_relative_paths,
        "0006_cleanup_orphan_concepts": _cleanup_orphan_concept_rows,
    }

    settings = get_settings()
    if is_postgres(settings.database_url):
        async with engine.begin() as lock_conn:
            await lock_conn.execute(sa_text("SELECT pg_advisory_xact_lock(737069)"))
            await _run_versioned_migrations(engine, _versioned_migrations, _session_migrations)
    else:
        await _run_versioned_migrations(engine, _versioned_migrations, _session_migrations)


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

        def _table_exists(sync_conn, name: str) -> bool:
            from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

            return name in sa_inspect(sync_conn).get_table_names()

        if not await conn.run_sync(lambda c: _table_exists(c, "query")):
            return  # Fresh DB — no legacy data to backfill

        def _select_legacy(sync_conn):
            return sync_conn.execute(
                sa_text(
                    "SELECT id, question, created_at, filed_article_id, user_id"
                    " FROM query WHERE conversation_id IS NULL"
                )
            ).fetchall()

        legacy_rows = await conn.run_sync(_select_legacy)

        for row in legacy_rows:
            query_id, question, created_at_raw, filed_article_id, user_id = row
            conv_id = str(uuid.uuid4())
            title = (question or "")[:title_max]
            # SQLite stores datetimes as strings via SQLModel; reuse the raw value if present
            created_at = created_at_raw or utcnow_naive().isoformat()

            await conn.execute(
                sa_text(
                    "INSERT INTO conversation (id, user_id, title, created_at, updated_at, filed_article_id) "
                    "VALUES (:id, :user_id, :title, :created_at, :updated_at, :filed_article_id)"
                ),
                {
                    "id": conv_id,
                    "user_id": user_id or "anonymous",
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
    inner = inner.removeprefix("[")
    inner = inner.removesuffix("]")

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
) -> tuple[dict[tuple[str, str], str], list[tuple[str, list[str]]]]:
    """Collect normalized concept names per user from article rows.

    Returns a tuple of:
    - ``all_names``: mapping ``(user_id, normalized) -> first raw name seen``.
    - ``article_concepts``: per-article list of ``(user_id, [normalized, ...])``.

    Concepts are partitioned by user because ``concept`` has a NOT NULL
    ``user_id`` FK and a ``UNIQUE(user_id, name)`` constraint — the same
    normalized name owned by two different users is two distinct rows.
    """
    all_names: dict[tuple[str, str], str] = {}
    article_concepts: list[tuple[str, list[str]]] = []
    for row in rows:
        _article_id, user_id, concept_ids_raw = row
        normalized_names = _parse_concept_names_from_json(concept_ids_raw)
        article_concepts.append((user_id, normalized_names))
        for name in normalized_names:
            key = (user_id, name)
            if key not in all_names:
                # Store the original raw value for the description
                try:
                    raw_list = json.loads(concept_ids_raw)
                    raw_match = next(
                        (str(n) for n in raw_list if slugify(str(n)) == name),
                        name,
                    )
                except (json.JSONDecodeError, TypeError):
                    raw_match = name
                all_names[key] = raw_match
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
                sa_text("SELECT id, user_id, concept_ids FROM article WHERE concept_ids IS NOT NULL")
            ).fetchall()

        rows = await conn.run_sync(_select_articles)
        all_names, article_concepts = _collect_concept_names(rows)

        if not all_names:
            return

        def _select_existing_concepts(sync_conn):
            return sync_conn.execute(sa_text("SELECT user_id, name FROM concept")).fetchall()

        existing_rows = await conn.run_sync(_select_existing_concepts)
        existing_keys = {(row[0], row[1]) for row in existing_rows}

        for (user_id, normalized), raw_name in all_names.items():
            if (user_id, normalized) not in existing_keys:
                concept_id = str(uuid.uuid4())
                await conn.execute(
                    sa_text(
                        "INSERT INTO concept "
                        "(id, user_id, name, description, article_count, created_at, concept_kind) "
                        "VALUES (:id, :user_id, :name, :desc, 0, :created_at, :concept_kind)"
                    ),
                    {
                        "id": concept_id,
                        "user_id": user_id,
                        "name": normalized,
                        "desc": raw_name,
                        "created_at": utcnow_naive(),
                        "concept_kind": "topic",
                    },
                )

        # Recalculate article counts per (user_id, name)
        counts: dict[tuple[str, str], int] = {}
        for user_id, names in article_concepts:
            for name in names:
                key = (user_id, name)
                counts[key] = counts.get(key, 0) + 1

        for (user_id, normalized), count in counts.items():
            await conn.execute(
                sa_text("UPDATE concept SET article_count = :count WHERE user_id = :user_id AND name = :name"),
                {"count": count, "user_id": user_id, "name": normalized},
            )

        unreferenced = (existing_keys | set(all_names.keys())) - set(counts.keys())
        for user_id, name in unreferenced:
            await conn.execute(
                sa_text("UPDATE concept SET article_count = 0 WHERE user_id = :user_id AND name = :name"),
                {"user_id": user_id, "name": name},
            )


async def _backfill_concept_links(conn, article_id: str, concept_ids_raw: str) -> None:
    """Insert ArticleConcept rows from a JSON-encoded concept list.

    Args:
        conn: Active async connection (inside a transaction).
        article_id: The article UUID.
        concept_ids_raw: JSON string of concept names.
    """
    try:
        concept_names = json.loads(concept_ids_raw)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(concept_names, list):
        return
    from wikimind.models import ArticleConcept  # noqa: PLC0415

    _insert = _dialect_insert(conn)
    for name in concept_names:
        if name:
            stmt = (
                _insert(ArticleConcept)
                .values(
                    article_id=article_id,
                    concept_name=str(name),
                )
                .on_conflict_do_nothing()
            )
            await conn.execute(stmt)


async def _backfill_source_links(conn, article_id: str, source_ids_raw: str) -> None:
    """Insert ArticleSource rows from a JSON-encoded source ID list.

    Args:
        conn: Active async connection (inside a transaction).
        article_id: The article UUID.
        source_ids_raw: JSON string of source UUIDs.
    """
    try:
        source_ids = json.loads(source_ids_raw)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(source_ids, list):
        return
    from wikimind.models import ArticleSource  # noqa: PLC0415

    _insert = _dialect_insert(conn)
    for sid in source_ids:
        if sid:
            stmt = (
                _insert(ArticleSource)
                .values(
                    article_id=article_id,
                    source_id=str(sid),
                )
                .on_conflict_do_nothing()
            )
            await conn.execute(stmt)


async def _backfill_join_tables_from_json(engine) -> None:
    """Populate ArticleConcept and ArticleSource from legacy JSON columns.

    Idempotent: existing rows are skipped via INSERT OR IGNORE (SQLite)
    or ON CONFLICT DO NOTHING (PostgreSQL).
    """
    async with engine.begin() as conn:

        def _table_exists(sync_conn, table_name: str) -> bool:
            inspector = sa_inspect(sync_conn)
            return table_name in inspector.get_table_names()

        has_ac = await conn.run_sync(lambda c: _table_exists(c, "articleconcept"))
        has_as = await conn.run_sync(lambda c: _table_exists(c, "articlesource"))

        if not has_ac or not has_as:
            return  # Tables not yet created; skip backfill

        def _select_articles(sync_conn):
            return sync_conn.execute(
                sa_text(
                    "SELECT id, concept_ids, source_ids FROM article"
                    " WHERE concept_ids IS NOT NULL OR source_ids IS NOT NULL"
                )
            ).fetchall()

        rows = await conn.run_sync(_select_articles)

        for row in rows:
            article_id, concept_ids_raw, source_ids_raw = row
            if concept_ids_raw:
                await _backfill_concept_links(conn, article_id, concept_ids_raw)
            if source_ids_raw:
                await _backfill_source_links(conn, article_id, source_ids_raw)


async def _cleanup_orphan_concept_rows(session: AsyncSession) -> None:
    """Delete concept-page Article rows whose markdown files no longer exist on disk.

    Stale rows appear when the naming scheme changes (e.g. the old non-prefixed
    ``prompt-caching/`` was replaced by ``concept-prompt-caching/``) and the DB
    rows were never cleaned up.  This removes the Article **and** any Backlink
    rows that reference it.

    Runs once at startup.  Idempotent -- re-running when no orphans exist is a
    no-op.  See issue #169.
    """
    from sqlalchemy import delete as sa_delete  # noqa: PLC0415
    from sqlalchemy import or_ as sa_or  # noqa: PLC0415

    from wikimind.models import Article, Backlink, PageType  # noqa: PLC0415
    from wikimind.storage import get_wiki_storage  # noqa: PLC0415

    result = await session.execute(select(Article).where(Article.page_type == PageType.CONCEPT))
    concept_articles = list(result.scalars().all())

    cleaned = 0
    for article in concept_articles:
        wiki_storage = get_wiki_storage(article.user_id)
        try:
            exists = await wiki_storage.exists(article.file_path)
        except ValueError:
            exists = False
        if exists:
            continue

        # Remove backlinks referencing the orphaned article first.
        await session.execute(
            sa_delete(Backlink).where(
                sa_or(
                    Backlink.source_article_id == article.id,
                    Backlink.target_article_id == article.id,
                )
            )
        )
        await session.execute(sa_delete(Article).where(Article.id == article.id))

        from wikimind.services.search import remove_article as fts_remove_article  # noqa: PLC0415

        await fts_remove_article(session, article.id)
        cleaned += 1
        log.warning(
            "startup: removed orphaned concept page (file missing)",
            article_id=article.id,
            slug=article.slug,
            path=article.file_path,
        )

    if cleaned:
        await session.commit()
        log.info("startup: cleaned orphaned concept rows", count=cleaned)


async def _migrate_to_relative_paths(session: AsyncSession) -> None:
    """Convert absolute file_path values to relative paths.

    Runs once at startup. Idempotent -- already-relative paths are skipped.
    """
    from wikimind.models import Article, Source  # noqa: PLC0415

    settings = get_settings()
    wiki_prefix = str(Path(settings.data_dir) / "wiki") + "/"
    raw_prefix = str(Path(settings.data_dir) / "raw") + "/"

    # Migrate Article.file_path (wiki-relative)
    result = await session.execute(select(Article).where(Article.file_path.startswith("/")))
    for article in result.scalars().all():
        if article.file_path.startswith(wiki_prefix):
            article.file_path = article.file_path[len(wiki_prefix) :]
            session.add(article)

    # Migrate Source.file_path (raw-relative)
    result = await session.execute(select(Source).where(Source.file_path.startswith("/")))  # type: ignore[union-attr]
    for source in result.scalars().all():
        if source.file_path and source.file_path.startswith(raw_prefix):
            source.file_path = source.file_path[len(raw_prefix) :]
            session.add(source)

    await session.commit()


async def close_db():
    """Close database connections. Called on app shutdown."""
    if get_async_engine.cache_info().currsize:
        await get_async_engine().dispose()
    get_async_engine.cache_clear()
    get_session_factory.cache_clear()
