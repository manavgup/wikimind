"""Tests for dialect-aware engine creation in database.py."""

from __future__ import annotations

import pytest

from wikimind.database import _create_engine_from_url, _parse_ssl


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
        with pytest.raises(ValueError, match="Unsupported dialect"):
            _create_engine_from_url("mysql+aiomysql://localhost/db")


class TestParseSsl:
    """Verify _parse_ssl extracts sslmode from URL and returns connect_args."""

    def test_no_sslmode_returns_empty(self):
        url = "postgresql+asyncpg://u:p@host:5432/db"
        clean, args = _parse_ssl(url)
        assert clean == url
        assert args == {}

    def test_sslmode_disable(self):
        url = "postgresql+asyncpg://u:p@host:5432/db?sslmode=disable"
        clean, args = _parse_ssl(url)
        assert "sslmode" not in clean
        assert args == {"ssl": False}

    def test_sslmode_require(self):
        url = "postgresql+asyncpg://u:p@host:5432/db?sslmode=require"
        clean, args = _parse_ssl(url)
        assert "sslmode" not in clean
        assert args == {"ssl": True}

    def test_sslmode_with_other_params(self):
        url = "postgresql+asyncpg://u:p@host:5432/db?sslmode=disable&application_name=test"
        clean, args = _parse_ssl(url)
        assert "application_name=test" in clean
        assert "sslmode" not in clean
        assert args == {"ssl": False}

    def test_ssl_param_disable(self):
        url = "postgresql+asyncpg://u:p@host:5432/db?ssl=disable"
        clean, args = _parse_ssl(url)
        assert "ssl" not in clean
        assert args == {"ssl": False}
