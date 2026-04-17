"""Tests for database dialect compatibility helpers."""

from __future__ import annotations

from wikimind.db_compat import (
    get_dialect_name,
    is_postgres,
    is_sqlite,
    json_array_contains,
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
