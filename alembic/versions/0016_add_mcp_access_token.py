"""Add mcp_access_token table for personal access token authentication.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-16

Personal access tokens (PATs) allow MCP clients like Claude Desktop to
authenticate with the WikiMind API using long-lived bearer tokens instead
of browser-session JWTs. See ADR-027.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0016"
down_revision: str = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "mcp_access_token" not in inspector.get_table_names():
        op.create_table(
            "mcp_access_token",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("token_prefix", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index("ix_mcp_access_token_user_id", "mcp_access_token", ["user_id"])
        op.create_index("ix_mcp_access_token_token_hash", "mcp_access_token", ["token_hash"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if "mcp_access_token" in inspector.get_table_names():
        op.drop_index("ix_mcp_access_token_token_hash", table_name="mcp_access_token")
        op.drop_index("ix_mcp_access_token_user_id", table_name="mcp_access_token")
        op.drop_table("mcp_access_token")
