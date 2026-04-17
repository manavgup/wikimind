"""Database dialect compatibility helpers.

Provides functions that generate dialect-appropriate SQL fragments for
operations that differ between SQLite and PostgreSQL: JSON array querying,
column introspection, and engine configuration.

SQLite uses json_each() and LIKE-based JSON searching.
PostgreSQL uses jsonb_array_elements_text() and the @> operator.
"""

from __future__ import annotations

import json as json_mod
from typing import Any

from sqlalchemy import literal_column, text
from sqlalchemy.sql import ClauseElement


def get_dialect_name(url: str) -> str:
    """Extract the dialect name from a database URL.

    Returns 'sqlite' or 'postgresql' (never the driver suffix).
    """
    scheme = url.split("://", maxsplit=1)[0].split("+", maxsplit=1)[0]
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
        return text(f"{column_name}::jsonb @> cast(:val as jsonb)").bindparams(val=json_mod.dumps([value]))
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
        value_ref: Any = literal_column(value_alias)
    else:
        from_clause = f"{table_name}, json_each({table_name}.{column_name})"
        value_ref = literal_column("json_each.value")
    return text(from_clause), value_ref
