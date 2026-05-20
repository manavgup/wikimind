"""Add discussion_message table for HITL compilation discussions.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19

Adds the discussion_message table that stores user and LLM messages
in pre-compilation discussion threads (issue #418).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0022"
down_revision: str = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create discussionmessage table."""
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "discussionmessage" not in existing:
        op.create_table(
            "discussionmessage",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("article_id", sa.String(), sa.ForeignKey("article.id"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_discussionmessage_article_id", "discussionmessage", ["article_id"])
        op.create_index("ix_discussionmessage_user_id", "discussionmessage", ["user_id"])


def downgrade() -> None:
    """Drop discussionmessage table."""
    op.drop_index("ix_discussionmessage_user_id", table_name="discussionmessage")
    op.drop_index("ix_discussionmessage_article_id", table_name="discussionmessage")
    op.drop_table("discussionmessage")
