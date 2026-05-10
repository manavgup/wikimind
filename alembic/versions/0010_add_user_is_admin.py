"""Add is_admin column to user table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-10

Adds an ``is_admin`` boolean column to the user table, defaulting to False.
Admin users can access the /admin/* dashboard endpoints.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists on *table* (works on SQLite + Postgres)."""
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add ``is_admin`` to ``user``.

    Idempotent: skips column if it already exists (e.g. when a fresh DB
    was created from the current SQLModel definitions in 0001).
    """
    conn = op.get_bind()

    if not _column_exists(conn, "user", "is_admin"):
        op.add_column(
            "user",
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    """Drop the column added in :func:`upgrade`."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch_op:
            if _column_exists(conn, "user", "is_admin"):
                batch_op.drop_column("is_admin")
    elif _column_exists(conn, "user", "is_admin"):
        op.drop_column("user", "is_admin")
