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

import sys

from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

# Register all models in metadata
import wikimind.models  # noqa: F401


def main() -> int:
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    # Normalise scheme for SQLAlchemy
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(db_url)
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())

    drift_found = False

    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in actual_tables:
            print(f"MISSING TABLE: {table_name}", file=sys.stderr)
            drift_found = True
            continue

        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        model_columns = {col.name for col in table.columns}
        missing = model_columns - actual_columns

        if missing:
            for col in sorted(missing):
                print(f"MISSING COLUMN: {table_name}.{col}", file=sys.stderr)
            drift_found = True

    if drift_found:
        print("\nSchema drift detected! Add Alembic migrations for the above.", file=sys.stderr)
        return 1

    print(f"OK: All {len(SQLModel.metadata.tables)} model tables and columns present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
