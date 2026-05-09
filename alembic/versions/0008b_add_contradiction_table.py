"""Add Contradiction table for persisted navigable contradictions.

Revision ID: 0008b
Revises: 0008
Create Date: 2026-05-07

Persists linter contradiction findings as first-class wiki content so users
can browse, resolve, and dismiss them over time. See issue #416.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008b"
down_revision: str = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn, table: str) -> bool:
    """Check if a table already exists."""
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def upgrade() -> None:
    """Create the contradiction table."""
    conn = op.get_bind()

    if not _table_exists(conn, "contradiction"):
        op.create_table(
            "contradiction",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("claim_a", sa.String(), nullable=False),
            sa.Column("claim_b", sa.String(), nullable=False),
            sa.Column(
                "article_a_id",
                sa.String(),
                sa.ForeignKey("article.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "article_b_id",
                sa.String(),
                sa.ForeignKey("article.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("source_finding_id", sa.String(), nullable=True),
            sa.Column("detected_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("resolution", sa.String(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", sa.String(), nullable=True),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
        )


def downgrade() -> None:
    """Drop the contradiction table."""
    op.drop_table("contradiction")
