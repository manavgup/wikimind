"""Initial schema from SQLModel definitions.

Revision ID: 0001
Revises:
Create Date: 2026-04-17

Creates all tables as defined by the SQLModel metadata. This migration
is used for Postgres deployments; SQLite uses create_all() directly.
"""

from collections.abc import Sequence

from sqlmodel import SQLModel

from alembic import op

# Import all models so metadata is populated
from wikimind import models  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables from SQLModel metadata."""
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    """Drop all tables."""
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)
