"""Add missing columns and tables not covered by prior migrations.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-12

Migration 0001 uses ``create_all()`` which creates tables from the current
``models.py`` snapshot.  On a fresh DB this creates everything; on an existing
DB where 0001 ran with an older ``models.py``, columns added to existing
tables are never created (``create_all`` only creates missing *tables*, not
missing *columns*).

This migration explicitly adds every column and table that models.py defines
but that no prior migration creates.  All operations are idempotent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0012"
down_revision: str = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa_inspect(conn)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def _add_column_if_missing(
    conn: sa.engine.Connection,
    table: str,
    column: sa.Column,
) -> None:
    if not _column_exists(conn, table, column.name):
        op.add_column(table, column)


def _create_table_if_missing(conn: sa.engine.Connection, table_name: str, *columns) -> None:
    if not _table_exists(conn, table_name):
        op.create_table(table_name, *columns)


def upgrade() -> None:
    conn = op.get_bind()

    # ── Missing columns on existing tables ───────────────────────

    # article: compilation monitoring (issue #547)
    _add_column_if_missing(conn, "article", sa.Column("compiled_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(
        conn, "article", sa.Column("compilation_duration_ms", sa.Integer(), nullable=True)
    )
    _add_column_if_missing(
        conn, "article", sa.Column("compilation_tokens", sa.Integer(), nullable=True)
    )

    # article: page_type and provider
    _add_column_if_missing(
        conn,
        "article",
        sa.Column("page_type", sa.String(), nullable=True, server_default="source"),
    )
    _add_column_if_missing(conn, "article", sa.Column("provider", sa.String(), nullable=True))

    # contradiction: claim_fingerprint (added after 0008b)
    if _table_exists(conn, "contradiction"):
        _add_column_if_missing(
            conn,
            "contradiction",
            sa.Column("claim_fingerprint", sa.String(), nullable=False, server_default=""),
        )
        # Add index if not present
        inspector = sa_inspect(conn)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("contradiction")}
        if "ix_contradiction_claim_fingerprint" not in existing_indexes:
            op.create_index(
                "ix_contradiction_claim_fingerprint",
                "contradiction",
                ["claim_fingerprint"],
            )

    # conversation: forking support
    _add_column_if_missing(
        conn,
        "conversation",
        sa.Column("parent_conversation_id", sa.String(), nullable=True),
    )
    _add_column_if_missing(
        conn, "conversation", sa.Column("forked_at_turn_index", sa.Integer(), nullable=True)
    )
    # Add index on parent_conversation_id if not present
    if _column_exists(conn, "conversation", "parent_conversation_id"):
        inspector = sa_inspect(conn)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("conversation")}
        if "ix_conversation_parent_conversation_id" not in existing_indexes:
            op.create_index(
                "ix_conversation_parent_conversation_id",
                "conversation",
                ["parent_conversation_id"],
            )

    # ── Missing tables ───────────────────────────────────────────
    # These are created by create_all() at app boot, but should also
    # exist in the migration chain for a clean Alembic-only schema.

    _create_table_if_missing(
        conn,
        "tag",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )

    _create_table_if_missing(
        conn,
        "articletag",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("article_id", sa.String(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("tag_id", sa.String(), sa.ForeignKey("tag.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("article_id", "tag_id", name="uq_articletag_article_tag"),
    )

    _create_table_if_missing(
        conn,
        "sharelink",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("article_id", sa.String(), sa.ForeignKey("article.id"), nullable=False),
        sa.Column("token", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(), nullable=True),
    )

    _create_table_if_missing(
        conn,
        "savedsearch",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("filters_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    _create_table_if_missing(
        conn,
        "capturesource",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("triaged_at", sa.DateTime(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
        sa.Column("discarded_at", sa.DateTime(), nullable=True),
        sa.Column("discard_reason", sa.String(), nullable=True),
    )

    _create_table_if_missing(
        conn,
        "rssfeed",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("feed_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("last_polled_at", sa.DateTime(), nullable=True),
        sa.Column("last_entry_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    _create_table_if_missing(
        conn,
        "compilationdraft",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_takeaways", sa.Text(), nullable=True),
        sa.Column("draft_result_json", sa.Text(), nullable=True),
        sa.Column("user_guidance", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_review"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )

    _create_table_if_missing(
        conn,
        "conceptkinddef",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("prompt_template_key", sa.String(), nullable=True),
        sa.Column("required_sections", sa.String(), nullable=True),
        sa.Column("linter_rules", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
    )

    _create_table_if_missing(
        conn,
        "userapikey",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("encrypted_key", sa.String(), nullable=False),
        sa.Column("salt", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_userapikey_user_provider"),
    )

    _create_table_if_missing(
        conn,
        "dismissedfinding",
        sa.Column("content_hash", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
    )

    _create_table_if_missing(
        conn,
        "lintpaircache",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("article_a_id", sa.String(), nullable=False),
        sa.Column("article_b_id", sa.String(), nullable=False),
        sa.Column("article_a_updated_at", sa.DateTime(), nullable=False),
        sa.Column("article_b_updated_at", sa.DateTime(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    # Drop tables (reverse order of creation)
    for table in [
        "lintpaircache",
        "dismissedfinding",
        "userapikey",
        "conceptkinddef",
        "compilationdraft",
        "rssfeed",
        "capturesource",
        "savedsearch",
        "sharelink",
        "articletag",
        "tag",
    ]:
        if _table_exists(conn, table):
            op.drop_table(table)

    # Drop columns (reverse order of addition)
    if is_sqlite:
        # SQLite needs batch mode for column drops
        if _column_exists(conn, "conversation", "forked_at_turn_index"):
            with op.batch_alter_table("conversation") as batch_op:
                batch_op.drop_column("forked_at_turn_index")
        if _column_exists(conn, "conversation", "parent_conversation_id"):
            with op.batch_alter_table("conversation") as batch_op:
                batch_op.drop_column("parent_conversation_id")
        if _table_exists(conn, "contradiction") and _column_exists(
            conn, "contradiction", "claim_fingerprint"
        ):
            with op.batch_alter_table("contradiction") as batch_op:
                batch_op.drop_column("claim_fingerprint")
        for col in ["provider", "page_type", "compilation_tokens",
                     "compilation_duration_ms", "compiled_at"]:
            if _column_exists(conn, "article", col):
                with op.batch_alter_table("article") as batch_op:
                    batch_op.drop_column(col)
    else:
        if _column_exists(conn, "conversation", "forked_at_turn_index"):
            op.drop_column("conversation", "forked_at_turn_index")
        if _column_exists(conn, "conversation", "parent_conversation_id"):
            op.drop_index("ix_conversation_parent_conversation_id", "conversation")
            op.drop_column("conversation", "parent_conversation_id")
        if _table_exists(conn, "contradiction") and _column_exists(
            conn, "contradiction", "claim_fingerprint"
        ):
            op.drop_index("ix_contradiction_claim_fingerprint", "contradiction")
            op.drop_column("contradiction", "claim_fingerprint")
        for col in ["provider", "page_type", "compilation_tokens",
                     "compilation_duration_ms", "compiled_at"]:
            if _column_exists(conn, "article", col):
                op.drop_column("article", col)
