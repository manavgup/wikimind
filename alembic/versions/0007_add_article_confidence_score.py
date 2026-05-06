"""Add numeric confidence_score and last_reinforced_at to article.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-06

Adds article-level numeric confidence with decay (issue #422). The
existing categorical ``article.confidence`` (a ConfidenceLevel enum) is
kept for per-article LLM-derived confidence and is unrelated to this
new numeric score, which is computed from source-count, recency, and
contradiction count by ``wikimind.engine.confidence``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists on *table* (works on SQLite + Postgres)."""
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add ``confidence_score`` and ``last_reinforced_at`` to ``article``.

    Idempotent: skips columns that already exist (e.g. when a fresh DB
    was created from the current SQLModel definitions in 0001).
    """
    conn = op.get_bind()

    if not _column_exists(conn, "article", "confidence_score"):
        op.add_column(
            "article",
            sa.Column(
                "confidence_score",
                sa.Float(),
                nullable=False,
                server_default="0.5",
            ),
        )
    if not _column_exists(conn, "article", "last_reinforced_at"):
        op.add_column(
            "article",
            sa.Column("last_reinforced_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Drop the columns added in :func:`upgrade`."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("article") as batch_op:
            if _column_exists(conn, "article", "last_reinforced_at"):
                batch_op.drop_column("last_reinforced_at")
            if _column_exists(conn, "article", "confidence_score"):
                batch_op.drop_column("confidence_score")
    else:
        if _column_exists(conn, "article", "last_reinforced_at"):
            op.drop_column("article", "last_reinforced_at")
        if _column_exists(conn, "article", "confidence_score"):
            op.drop_column("article", "confidence_score")
