"""Tests for database session lifecycle — commit on success, rollback on error."""

import contextlib

import pytest
from sqlmodel import select

from wikimind.database import get_session
from wikimind.models import Source, SourceType


@pytest.fixture
def session_factory(async_engine):
    """Override get_session to use the in-memory engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest.fixture
def _patch_session_factory(session_factory, monkeypatch):
    """Monkey-patch get_session_factory to use the test session factory."""
    monkeypatch.setattr("wikimind.database.get_session_factory", lambda: session_factory)


@pytest.mark.usefixtures("_patch_session_factory")
class TestSessionLifecycle:
    async def test_commit_on_success(self, session_factory):
        """Session auto-commits when the block exits normally."""
        gen = get_session()
        session = await gen.__anext__()

        source = Source(source_type=SourceType.URL, source_url="https://example.com")
        session.add(source)
        source_id = source.id

        # Close the generator — triggers commit
        with contextlib.suppress(StopAsyncIteration):
            await gen.__anext__()

        # Verify the row was persisted
        async with session_factory() as verify_session:
            result = await verify_session.execute(select(Source).where(Source.id == source_id))
            persisted = result.scalar_one_or_none()
            assert persisted is not None
            assert persisted.source_url == "https://example.com"

    async def test_rollback_on_error(self, session_factory):
        """Session rolls back when an exception is raised."""
        gen = get_session()
        session = await gen.__anext__()

        source = Source(source_type=SourceType.URL, source_url="https://rollback.example.com")
        session.add(source)
        source_id = source.id

        # Simulate an error — triggers rollback
        with pytest.raises(RuntimeError, match="simulated"):
            await gen.athrow(RuntimeError("simulated error"))

        # Verify the row was NOT persisted
        async with session_factory() as verify_session:
            result = await verify_session.execute(select(Source).where(Source.id == source_id))
            persisted = result.scalar_one_or_none()
            assert persisted is None
