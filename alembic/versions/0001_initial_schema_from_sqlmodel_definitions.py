"""Initial schema from SQLModel definitions.

Revision ID: 0001
Revises:
Create Date: 2026-04-17

Creates all tables as defined by the SQLModel metadata. This migration
is used for Postgres deployments; SQLite uses create_all() directly.
"""

from typing import Sequence, Union

from alembic import op
from sqlmodel import SQLModel

# Import all models so metadata is populated
from wikimind import models  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from SQLModel metadata."""
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    """Drop all tables."""
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind)
