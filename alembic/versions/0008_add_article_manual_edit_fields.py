"""Add manually_edited and edited_at to article.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07

Supports manual article editing (issue #449). When a user edits an
article directly, ``manually_edited`` is set to True and ``edited_at``
records the timestamp. Recompilation respects this flag.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists on *table* (works on SQLite + Postgres)."""
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add ``manually_edited`` and ``edited_at`` to ``article``.

    Idempotent: skips columns that already exist (e.g. when a fresh DB
    was created from the current SQLModel definitions in 0001).
    """
    conn = op.get_bind()

    if not _column_exists(conn, "article", "manually_edited"):
        op.add_column(
            "article",
            sa.Column(
                "manually_edited",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )
    if not _column_exists(conn, "article", "edited_at"):
        op.add_column(
            "article",
            sa.Column("edited_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Drop the columns added in :func:`upgrade`."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("article") as batch_op:
            if _column_exists(conn, "article", "edited_at"):
                batch_op.drop_column("edited_at")
            if _column_exists(conn, "article", "manually_edited"):
                batch_op.drop_column("manually_edited")
    else:
        if _column_exists(conn, "article", "edited_at"):
            op.drop_column("article", "edited_at")
        if _column_exists(conn, "article", "manually_edited"):
            op.drop_column("article", "manually_edited")
