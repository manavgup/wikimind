"""Add source_span table and source_span_ids column on compiledclaim.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19

Adds the SourceSpan table for paragraph-level citation anchoring and a
source_span_ids JSON column on CompiledClaim to link claims to their
source spans. See issue #450.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    # ── sourcespan ──────────────────────────────────────────────────────────
    if "sourcespan" not in existing:
        op.create_table(
            "sourcespan",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "source_id",
                sa.String(),
                sa.ForeignKey("source.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("user.id"),
                nullable=False,
            ),
            sa.Column("locator_kind", sa.String(), nullable=False),
            sa.Column("locator", sa.JSON(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sourcespan_source_id", "sourcespan", ["source_id"])
        op.create_index("ix_sourcespan_user_id", "sourcespan", ["user_id"])
        op.create_index("ix_sourcespan_fingerprint", "sourcespan", ["fingerprint"])

    # ── source_span_ids on compiledclaim ────────────────────────────────────
    if "compiledclaim" in existing:
        claim_columns = [c["name"] for c in inspector.get_columns("compiledclaim")]
        if "source_span_ids" not in claim_columns:
            op.add_column(
                "compiledclaim",
                sa.Column(
                    "source_span_ids",
                    sa.String(),
                    nullable=False,
                    server_default="[]",
                ),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    # Drop source_span_ids from compiledclaim
    if "compiledclaim" in existing:
        claim_columns = [c["name"] for c in inspector.get_columns("compiledclaim")]
        if "source_span_ids" in claim_columns:
            op.drop_column("compiledclaim", "source_span_ids")

    # Drop sourcespan table
    if "sourcespan" in existing:
        op.drop_index("ix_sourcespan_fingerprint", table_name="sourcespan")
        op.drop_index("ix_sourcespan_user_id", table_name="sourcespan")
        op.drop_index("ix_sourcespan_source_id", table_name="sourcespan")
        op.drop_table("sourcespan")
