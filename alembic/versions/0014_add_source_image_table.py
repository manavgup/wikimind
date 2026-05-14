"""Add sourceimage table for DB-backed PDF image storage.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-14

Store extracted PDF images in Postgres so the web machine can serve them
without needing access to the worker machine's filesystem volume (issue #638).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0014"
down_revision: str = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "sourceimage" not in inspector.get_table_names():
        op.create_table(
            "sourceimage",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("source_id", sa.String(), sa.ForeignKey("source.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("image_data", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sourceimage_source_id", "sourceimage", ["source_id"])
        op.create_index("ix_sourceimage_user_id", "sourceimage", ["user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "sourceimage" in inspector.get_table_names():
        op.drop_index("ix_sourceimage_user_id", table_name="sourceimage")
        op.drop_index("ix_sourceimage_source_id", table_name="sourceimage")
        op.drop_table("sourceimage")
