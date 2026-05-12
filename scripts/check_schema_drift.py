#!/usr/bin/env python3
"""Detect model/migration schema drift.

Compares the columns defined in SQLModel metadata (models.py) against
the columns that exist after running ``alembic upgrade head`` on a fresh
Postgres database.  Any column present in the model but missing from
the Alembic schema is a migration gap that will break production.

Usage (CI):
    python scripts/check_schema_drift.py

Requires DATABASE_URL pointing at a Postgres database where Alembic
migrations have been applied (but NOT create_all).

Exit codes:
    0  All model columns are covered by migrations.
    1  Drift detected — missing columns listed on stderr.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

import wikimind.models  # noqa: F401 — registers SQLModel tables in metadata


def _get_table_names(sync_conn):
    """Return all table names from the database."""
    return sa_inspect(sync_conn).get_table_names()


def _get_columns(table_name):
    """Return a callable that fetches columns for the given table."""

    def _inner(sync_conn):
        return sa_inspect(sync_conn).get_columns(table_name)

    return _inner


async def _check() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    # Normalise scheme for async driver
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        actual_tables = await conn.run_sync(_get_table_names)

    drift_found = False

    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in actual_tables:
            print(f"MISSING TABLE: {table_name}", file=sys.stderr)
            drift_found = True
            continue

        async with engine.connect() as conn:
            columns = await conn.run_sync(_get_columns(table_name))
        actual_columns = {col["name"] for col in columns}
        model_columns = {col.name for col in table.columns}
        missing = model_columns - actual_columns

        if missing:
            for col in sorted(missing):
                print(f"MISSING COLUMN: {table_name}.{col}", file=sys.stderr)
            drift_found = True

    await engine.dispose()

    if drift_found:
        print("\nSchema drift detected! Add Alembic migrations for the above.", file=sys.stderr)
        return 1

    print(f"OK: All {len(SQLModel.metadata.tables)} model tables and columns present.")
    return 0


def main() -> int:
    """Entry point for schema-drift detection."""
    return asyncio.run(_check())


if __name__ == "__main__":
    sys.exit(main())
