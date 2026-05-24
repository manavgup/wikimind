"""Add stale column to sourcespan table.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-23

Adds a boolean ``stale`` column to the ``sourcespan`` table so that spans
whose content no longer matches after a source re-ingestion can be flagged.
Claims referencing stale spans surface as linter warnings. See issue #450,
Phase 5.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0023"
down_revision: str = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "sourcespan" in existing:
        columns = [c["name"] for c in inspector.get_columns("sourcespan")]
        if "stale" not in columns:
            op.add_column(
                "sourcespan",
                sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "sourcespan" in existing:
        columns = [c["name"] for c in inspector.get_columns("sourcespan")]
        if "stale" in columns:
            op.drop_column("sourcespan", "stale")
