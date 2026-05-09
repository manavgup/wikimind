"""Add source_newest_at to article and create reinforcement_event table.

Revision ID: 0008d
Revises: 0008c
Create Date: 2026-05-07

Adds staleness detection infrastructure (issue #425):
- ``article.source_newest_at`` — date of the most recent source used
- ``reinforcementevent`` table — audit trail for reinforcement events
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008d"
down_revision: str = "0008c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    """Return True if *column* exists on *table* (works on SQLite + Postgres)."""
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    """Return True if *table* exists in the database."""
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def upgrade() -> None:
    """Add staleness fields and reinforcement event table."""
    conn = op.get_bind()

    # Add source_newest_at to article
    if not _column_exists(conn, "article", "source_newest_at"):
        op.add_column(
            "article",
            sa.Column("source_newest_at", sa.DateTime(), nullable=True),
        )

    # Create reinforcementevent table
    if not _table_exists(conn, "reinforcementevent"):
        op.create_table(
            "reinforcementevent",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "article_id",
                sa.String(),
                sa.ForeignKey("article.id"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("user.id"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_reinforcementevent_article_id",
            "reinforcementevent",
            ["article_id"],
        )
        op.create_index(
            "ix_reinforcementevent_user_id",
            "reinforcementevent",
            ["user_id"],
        )


def downgrade() -> None:
    """Drop staleness fields and reinforcement event table."""
    conn = op.get_bind()

    if _table_exists(conn, "reinforcementevent"):
        op.drop_table("reinforcementevent")

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("article") as batch_op:
            if _column_exists(conn, "article", "source_newest_at"):
                batch_op.drop_column("source_newest_at")
    elif _column_exists(conn, "article", "source_newest_at"):
        op.drop_column("article", "source_newest_at")
