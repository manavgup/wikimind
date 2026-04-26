"""Add OpenAI-compatible provider enum value.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26

Adds the Provider.OPENAI_COMPATIBLE value for PostgreSQL deployments that
materialize SQLModel enums as native Postgres enum types. SQLite and varchar
backends need no schema change.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the OPENAI_COMPATIBLE enum value when the native enum exists."""
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    enum_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'provider'"),
    ).scalar()
    if enum_exists:
        conn.execute(sa.text("ALTER TYPE provider ADD VALUE IF NOT EXISTS 'OPENAI_COMPATIBLE'"))


def downgrade() -> None:
    """No-op: PostgreSQL cannot safely remove enum values in-place."""
