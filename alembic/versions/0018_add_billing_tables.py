"""Add billing tables (plan, subscription, webhook_event, storage_usage, query_count).

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-19

Adds the full billing schema for the WikiMind subscription system, including
plan definitions, user subscriptions, Lemon Squeezy webhook deduplication,
and per-user quota tracking. Seeds default free and pro plans.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from alembic import op

revision: str = "0018"
down_revision: str = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    # ── plan ─────────────────────────────────────────────────────────────────
    if "plan" not in existing:
        op.create_table(
            "plan",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("price_cents", sa.Integer(), nullable=False),
            sa.Column("billing_interval", sa.String(), nullable=True),
            sa.Column("max_sources", sa.Integer(), nullable=True),
            sa.Column("max_articles", sa.Integer(), nullable=True),
            sa.Column("max_queries_per_day", sa.Integer(), nullable=True),
            sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True),
            sa.Column("max_active_shares", sa.Integer(), nullable=True),
            sa.Column("daily_llm_spend_cap_cents", sa.Integer(), nullable=True),
            sa.Column("allowed_exports", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column(
                "llm_provider",
                sa.String(),
                nullable=False,
                server_default="openai_compatible",
            ),
            sa.Column(
                "llm_model", sa.String(), nullable=False, server_default="gpt-4o-mini"
            ),
            sa.Column("byok_allowed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lemon_squeezy_variant_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    # ── subscription ─────────────────────────────────────────────────────────
    if "subscription" not in existing:
        op.create_table(
            "subscription",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("plan_id", sa.String(), sa.ForeignKey("plan.id"), nullable=False),
            sa.Column(
                "lemon_squeezy_subscription_id", sa.String(), nullable=False, unique=True
            ),
            sa.Column("lemon_squeezy_customer_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column(
                "cancel_at_period_end", sa.Boolean(), nullable=False, server_default="0"
            ),
            sa.Column("current_period_start", sa.DateTime(), nullable=False),
            sa.Column("current_period_end", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        # Partial unique index: only one active subscription per user
        op.create_index(
            "ix_subscription_active_user",
            "subscription",
            ["user_id"],
            unique=True,
            postgresql_where=text("status = 'active'"),
        )

    # ── webhook_event ─────────────────────────────────────────────────────────
    if "webhook_event" not in existing:
        op.create_table(
            "webhook_event",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "lemon_squeezy_event_id", sa.String(), nullable=False, unique=True
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=False),
            sa.Column("payload_hash", sa.String(), nullable=False),
        )

    # ── storage_usage ─────────────────────────────────────────────────────────
    if "storage_usage" not in existing:
        op.create_table(
            "storage_usage",
            sa.Column("user_id", sa.String(), primary_key=True),
            sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    # ── query_count ───────────────────────────────────────────────────────────
    if "query_count" not in existing:
        op.create_table(
            "query_count",
            sa.Column("user_id", sa.String(), primary_key=True),
            sa.Column("date", sa.Date(), primary_key=True),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        )

    # ── New columns on user table ─────────────────────────────────────────────
    user_columns = [c["name"] for c in inspector.get_columns("user")]

    if "plan_id" not in user_columns:
        op.add_column("user", sa.Column("plan_id", sa.String(), nullable=True))

    if "plan_effective_until" not in user_columns:
        op.add_column(
            "user", sa.Column("plan_effective_until", sa.DateTime(), nullable=True)
        )

    if "lemon_squeezy_customer_id" not in user_columns:
        op.add_column(
            "user", sa.Column("lemon_squeezy_customer_id", sa.String(), nullable=True)
        )

    # ── Seed default plans ────────────────────────────────────────────────────
    conn.execute(
        text(
            """
            INSERT INTO plan (
                id, name, display_name, price_cents, billing_interval,
                max_sources, max_articles, max_queries_per_day, max_storage_bytes,
                max_active_shares, daily_llm_spend_cap_cents,
                allowed_exports, mcp_enabled,
                llm_provider, llm_model, byok_allowed,
                is_default, is_active, sort_order,
                lemon_squeezy_variant_id, created_at, updated_at
            ) VALUES
            (
                gen_random_uuid()::text, 'free', 'Free', 0, NULL,
                20, 30, 10, 26214400,
                3, 50,
                '["markdown"]', false,
                'openai_compatible', 'gpt-4o-mini', false,
                true, true, 0,
                NULL, now(), now()
            ),
            (
                gen_random_uuid()::text, 'pro', 'Pro', 1200, 'month',
                500, 1000, 200, 5368709120,
                100, 1000,
                '["markdown","json","pdf","linkedin","slides","obsidian"]', true,
                'openai_compatible', 'gpt-4o', true,
                false, true, 1,
                NULL, now(), now()
            )
            ON CONFLICT (name) DO NOTHING
            """
        )
    )

    # ── Backfill storage_usage for existing users ─────────────────────────────
    conn.execute(
        text(
            """
            INSERT INTO storage_usage (user_id, total_bytes, updated_at)
            SELECT id, 0, now()
            FROM "user"
            ON CONFLICT (user_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    existing = inspector.get_table_names()

    # Drop tables (reverse dependency order)
    if "query_count" in existing:
        op.drop_table("query_count")

    if "storage_usage" in existing:
        op.drop_table("storage_usage")

    if "webhook_event" in existing:
        op.drop_table("webhook_event")

    if "subscription" in existing:
        indexes = [idx["name"] for idx in inspector.get_indexes("subscription")]
        if "ix_subscription_active_user" in indexes:
            op.drop_index("ix_subscription_active_user", table_name="subscription")
        op.drop_table("subscription")

    if "plan" in existing:
        op.drop_table("plan")

    # Drop columns added to user table
    user_columns = [c["name"] for c in inspector.get_columns("user")]
    for col in ("lemon_squeezy_customer_id", "plan_effective_until", "plan_id"):
        if col in user_columns:
            op.drop_column("user", col)
