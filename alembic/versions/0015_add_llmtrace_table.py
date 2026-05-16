"""Add llmtrace table for opt-in LLM call tracing.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-15

Stores lightweight LLM call metrics (tokens, latency, model, operation).
Prompt/completion text is only populated when trace_store_content is enabled.
See issue #620.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0015"
down_revision: str = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "llmtrace" not in inspector.get_table_names():
        op.create_table(
            "llmtrace",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False),
            sa.Column("completion_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("prompt_text", sa.Text(), nullable=True),
            sa.Column("completion_text", sa.Text(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("operation", sa.String(), nullable=False),
        )
        op.create_index("ix_llmtrace_user_id", "llmtrace", ["user_id"])
        op.create_index("ix_llmtrace_created_at", "llmtrace", ["created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "llmtrace" in inspector.get_table_names():
        op.drop_index("ix_llmtrace_created_at", table_name="llmtrace")
        op.drop_index("ix_llmtrace_user_id", table_name="llmtrace")
        op.drop_table("llmtrace")
