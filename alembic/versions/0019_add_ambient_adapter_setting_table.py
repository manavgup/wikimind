"""Add ambient_adapter_setting table for persisted adapter configuration.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19

The AmbientAdapterSetting table stores per-user ambient adapter
configurations (enabled/disabled, adapter-specific settings JSON).
The model was introduced in issue #442 but shipped without a migration,
so deployed databases would lack the table.
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

    if "ambientadaptersetting" not in existing:
        op.create_table(
            "ambientadaptersetting",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("user.id"),
                nullable=False,
            ),
            sa.Column("adapter_type", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("settings_json", sa.String(), nullable=False, server_default="{}"),
            sa.Column("last_polled_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_ambientadaptersetting_user_id",
            "ambientadaptersetting",
            ["user_id"],
        )
        op.create_index(
            "ix_ambientadaptersetting_adapter_type",
            "ambientadaptersetting",
            ["adapter_type"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "ambientadaptersetting" in existing:
        op.drop_index(
            "ix_ambientadaptersetting_adapter_type",
            table_name="ambientadaptersetting",
        )
        op.drop_index(
            "ix_ambientadaptersetting_user_id",
            table_name="ambientadaptersetting",
        )
        op.drop_table("ambientadaptersetting")
