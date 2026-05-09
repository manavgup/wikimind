"""Add is_stub column to article.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-08

Supports stub pages (issue #451). Stub articles are user-created
placeholder pages for concepts not yet covered by compiled sources.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists on *table* (works on SQLite + Postgres)."""
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add ``is_stub`` to ``article``.

    Idempotent: skips column if it already exists (e.g. when a fresh DB
    was created from the current SQLModel definitions in 0001).
    """
    conn = op.get_bind()

    if not _column_exists(conn, "article", "is_stub"):
        op.add_column(
            "article",
            sa.Column(
                "is_stub",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    """Drop the column added in :func:`upgrade`."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("article") as batch_op:
            if _column_exists(conn, "article", "is_stub"):
                batch_op.drop_column("is_stub")
    elif _column_exists(conn, "article", "is_stub"):
        op.drop_column("article", "is_stub")
