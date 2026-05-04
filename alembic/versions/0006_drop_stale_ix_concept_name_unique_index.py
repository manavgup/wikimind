"""Drop stale single-column UNIQUE index on concept.name.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-02

The ix_concept_name index enforces uniqueness on name alone, which blocks
multi-user compilation (two users cannot share a concept name).
The correct constraint is the composite uq_concept_user_name(user_id, name)
added in migration 0002. Closes #433.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(conn: sa.engine.Connection, table: str, index_name: str) -> bool:
    """Return True if *index_name* exists on *table*."""
    inspector = sa_inspect(conn)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table))


def _constraint_exists(conn: sa.engine.Connection, table: str, constraint_name: str) -> bool:
    """Return True if a unique constraint with *constraint_name* exists on *table*."""
    inspector = sa_inspect(conn)
    return any(
        uc["name"] == constraint_name for uc in inspector.get_unique_constraints(table)
    )


def upgrade() -> None:
    """Drop the legacy ix_concept_name unique index if it exists."""
    conn = op.get_bind()

    # Verify the composite constraint exists before dropping the old index
    if not _constraint_exists(conn, "concept", "uq_concept_user_name"):
        msg = (
            "Composite unique constraint uq_concept_user_name does not exist on concept. "
            "Run migration 0002 first."
        )
        raise RuntimeError(msg)

    if not _index_exists(conn, "concept", "ix_concept_name"):
        return  # Nothing to do — index was already removed

    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("concept") as batch_op:
            batch_op.drop_index("ix_concept_name")
    else:
        op.drop_index("ix_concept_name", table_name="concept")


def downgrade() -> None:
    """Re-create the single-column unique index on concept.name."""
    op.create_index("ix_concept_name", "concept", ["name"], unique=True)
