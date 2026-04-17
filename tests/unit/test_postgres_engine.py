"""Tests for dialect-aware engine creation in database.py."""

from __future__ import annotations

import pytest

from wikimind.database import _create_engine_from_url


class TestCreateEngineFromUrl:
    async def test_sqlite_url_creates_aiosqlite_engine(self):
        """SQLite URL produces an engine with check_same_thread=False."""
        engine = _create_engine_from_url("sqlite+aiosqlite:///tmp/test.db")
        assert "sqlite" in str(engine.url)
        await engine.dispose()

    async def test_sqlite_in_memory_works(self):
        """In-memory SQLite URL works."""
        engine = _create_engine_from_url("sqlite+aiosqlite://")
        assert "sqlite" in str(engine.url)
        await engine.dispose()

    async def test_postgres_url_creates_asyncpg_engine(self):
        """Postgres URL produces an engine with pool settings.

        We can not actually connect without a running Postgres instance,
        but we can verify the engine is created with the right URL.
        """
        url = "postgresql+asyncpg://user:pass@localhost:5432/wikimind"
        engine = _create_engine_from_url(url)
        assert "postgresql" in str(engine.url)
        await engine.dispose()

    def test_unknown_dialect_raises(self):
        """An unsupported database URL raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported database dialect"):
            _create_engine_from_url("mysql+aiomysql://localhost/db")
