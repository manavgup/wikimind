"""Add OAuth 2.1 authorization code and access token tables.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-16

Supports the OAuth 2.1 Authorization Server for MCP remote connections.
See issue #764.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0017"
down_revision: str = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "oauthauthorizationcode" not in existing:
        op.create_table(
            "oauthauthorizationcode",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("code", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("redirect_uri", sa.String(), nullable=False),
            sa.Column("code_challenge", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index(
            "ix_oauthauthorizationcode_code", "oauthauthorizationcode", ["code"]
        )

    if "oauthaccesstoken" not in existing:
        op.create_table(
            "oauthaccesstoken",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        )
        op.create_index(
            "ix_oauthaccesstoken_token_hash", "oauthaccesstoken", ["token_hash"]
        )
        op.create_index(
            "ix_oauthaccesstoken_user_id", "oauthaccesstoken", ["user_id"]
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    if "oauthaccesstoken" in existing:
        op.drop_index("ix_oauthaccesstoken_user_id", table_name="oauthaccesstoken")
        op.drop_index("ix_oauthaccesstoken_token_hash", table_name="oauthaccesstoken")
        op.drop_table("oauthaccesstoken")

    if "oauthauthorizationcode" in existing:
        op.drop_index(
            "ix_oauthauthorizationcode_code", table_name="oauthauthorizationcode"
        )
        op.drop_table("oauthauthorizationcode")
