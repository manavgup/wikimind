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
    """Create all tables. Called on app startup."""
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def close_db():
    """Close database connections. Called on app shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
