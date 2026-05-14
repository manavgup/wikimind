"""Add clean_text column to source table.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-12

Store source content in Postgres so the worker can read it without needing
access to the web machine's filesystem volume (issue #626).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0013"
down_revision: str = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "source", "clean_text"):
        op.add_column("source", sa.Column("clean_text", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"
    if _column_exists(conn, "source", "clean_text"):
        if is_sqlite:
            with op.batch_alter_table("source") as batch_op:
                batch_op.drop_column("clean_text")
        else:
            op.drop_column("source", "clean_text")
