"""Add source extraction metadata columns.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-08

Records the PDF extraction engine and page count used during ingest so the UI
can explain the Extract step without needing to re-run document conversion.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0024"
down_revision: str = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    """Add nullable extraction metadata columns to source."""
    conn = op.get_bind()
    if not _column_exists(conn, "source", "extraction_engine"):
        op.add_column("source", sa.Column("extraction_engine", sa.String(), nullable=True))
    if not _column_exists(conn, "source", "extraction_page_count"):
        op.add_column("source", sa.Column("extraction_page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove extraction metadata columns from source."""
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("source") as batch_op:
            if _column_exists(conn, "source", "extraction_page_count"):
                batch_op.drop_column("extraction_page_count")
            if _column_exists(conn, "source", "extraction_engine"):
                batch_op.drop_column("extraction_engine")
        return

    if _column_exists(conn, "source", "extraction_page_count"):
        op.drop_column("source", "extraction_page_count")
    if _column_exists(conn, "source", "extraction_engine"):
        op.drop_column("source", "extraction_engine")
