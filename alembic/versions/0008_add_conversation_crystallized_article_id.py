"""Add crystallized_article_id to conversation table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07

Tracks which synthesis article was created when a conversation is
crystallized, enabling idempotency (issue #424 grill fix).
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
    """Add ``crystallized_article_id`` FK to ``conversation``.

    Idempotent: skips if the column already exists (e.g. fresh DB from
    current SQLModel definitions).
    """
    conn = op.get_bind()

    if not _column_exists(conn, "conversation", "crystallized_article_id"):
        op.add_column(
            "conversation",
            sa.Column(
                "crystallized_article_id",
                sa.String(),
                sa.ForeignKey("article.id"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    """Drop the column added in :func:`upgrade`."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("conversation") as batch_op:
            if _column_exists(conn, "conversation", "crystallized_article_id"):
                batch_op.drop_column("crystallized_article_id")
    else:
        if _column_exists(conn, "conversation", "crystallized_article_id"):
            op.drop_column("conversation", "crystallized_article_id")
