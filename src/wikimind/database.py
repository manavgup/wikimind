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

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

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
    """
    additions: list[tuple[str, str, str]] = [
        # (table, column, ALTER fragment)
        ("source", "content_hash", "ALTER TABLE source ADD COLUMN content_hash TEXT"),
        ("article", "provider", "ALTER TABLE article ADD COLUMN provider TEXT"),
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


async def close_db():
    """Close database connections. Called on app shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
