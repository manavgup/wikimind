"""Make user_id NOT NULL on all data models.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-01

Backfills NULL user_id rows with 'anonymous' (for legacy data), then
alters each column to SET NOT NULL. Closes #393.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [
    "source",
    "article",
    "concept",
    "backlink",
    "conversation",
    "query",
    "job",
    "costlog",
    "synclog",
    "userpreference",
    "lintreport",
    "contradictionfinding",
    "orphanfinding",
    "structuralfinding",
]


def upgrade() -> None:
    """Backfill NULL user_id rows and make the column NOT NULL."""
    conn = op.get_bind()

    # Backfill legacy NULL rows
    for table in _TABLES:
        op.execute(sa.text(f"UPDATE {table} SET user_id = 'anonymous' WHERE user_id IS NULL"))

    # Make columns NOT NULL
    if conn.dialect.name == "sqlite":
        # SQLite does not support ALTER COLUMN; use batch mode
        for table in _TABLES:
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column("user_id", existing_type=sa.String(), nullable=False)
    else:
        for table in _TABLES:
            op.alter_column(table, "user_id", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Revert user_id columns back to nullable."""
    conn = op.get_bind()

    if conn.dialect.name == "sqlite":
        for table in _TABLES:
            with op.batch_alter_table(table) as batch_op:
                batch_op.alter_column("user_id", existing_type=sa.String(), nullable=True)
    else:
        for table in _TABLES:
            op.alter_column(table, "user_id", existing_type=sa.String(), nullable=True)
