"""Backfill compiled_claim rows from article markdown key-claims sections.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19

Articles compiled before the ``compiledclaim`` table existed (migration 0010)
have key claims only in their markdown ``## Key Claims`` section.  This data
migration parses those claims and inserts ``compiledclaim`` rows so that all
claim consumers (linter, search, concept clustering) can query a single
authoritative source.

The migration is idempotent: articles that already have ``compiledclaim`` rows
are skipped.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def _parse_claims_from_markdown(content: str) -> list[str]:
    """Parse bullet-point claims from a ``## Key Claims`` markdown section."""
    lines = content.split("\n")
    claims: list[str] = []
    in_claims_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## key claims") or stripped.lower().startswith(
            "## key_claims"
        ):
            in_claims_section = True
            continue
        if in_claims_section:
            if stripped.startswith("## "):
                break
            if stripped.startswith(("- ", "* ")):
                claims.append(stripped[2:].strip())

    return claims


def upgrade() -> None:
    """Backfill compiledclaim rows from article markdown files.

    Uses raw SQL to avoid importing the ORM models (which may change
    after this migration is written).  Reads wiki file content via the
    storage layer only if the article has no existing compiledclaim rows.
    """
    conn = op.get_bind()

    if not _table_exists(conn, "compiledclaim"):
        # Table doesn't exist yet — nothing to backfill.
        return

    if not _table_exists(conn, "article"):
        return

    # Find articles that have NO compiledclaim rows yet.
    articles_without_claims = conn.execute(
        sa.text(
            """
            SELECT a.id, a.user_id, a.file_path, a.created_at
            FROM article a
            LEFT JOIN compiledclaim cc ON cc.article_id = a.id
            WHERE cc.id IS NULL
              AND a.file_path IS NOT NULL
            """
        )
    ).fetchall()

    if not articles_without_claims:
        return

    # We need the storage layer to resolve file paths.  Import lazily
    # because Alembic migrations should minimise app-level imports.
    try:
        from wikimind.storage import get_wiki_storage  # noqa: PLC0415
    except ImportError:
        # If the app code is not importable (e.g. running bare Alembic),
        # skip the data migration — it will be retried on next deploy.
        return

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    rows_to_insert: list[dict] = []

    for article_id, user_id, file_path, created_at in articles_without_claims:
        try:
            storage = get_wiki_storage(user_id)
            # Read file synchronously — the async storage.read() just wraps
            # Path.read_text via asyncio.to_thread, so call it directly.
            resolved = storage.resolve_path(file_path)
            content = resolved.read_text(encoding="utf-8")
        except (FileNotFoundError, ValueError):
            continue

        claims = _parse_claims_from_markdown(content)
        article_created = created_at or now

        for claim_text in claims:
            if not claim_text:
                continue
            rows_to_insert.append(
                {
                    "id": str(uuid.uuid4()),
                    "article_id": article_id,
                    "user_id": user_id,
                    "text": claim_text,
                    "subjects": "[]",
                    "predicate": None,
                    "confidence_level": "sourced",
                    "confidence_score": 0.5,
                    "source_ids": "[]",
                    "last_reinforced_at": article_created,
                    "quote": None,
                    "embedding": None,
                    "embedding_version": None,
                    "cluster_assignment_reconciled": False,
                    "created_at": now,
                    "updated_at": now,
                }
            )

    if rows_to_insert:
        compiled_claim_table = sa.table(
            "compiledclaim",
            sa.column("id", sa.String),
            sa.column("article_id", sa.String),
            sa.column("user_id", sa.String),
            sa.column("text", sa.String),
            sa.column("subjects", sa.String),
            sa.column("predicate", sa.String),
            sa.column("confidence_level", sa.String),
            sa.column("confidence_score", sa.Float),
            sa.column("source_ids", sa.String),
            sa.column("last_reinforced_at", sa.DateTime),
            sa.column("quote", sa.String),
            sa.column("embedding", sa.LargeBinary),
            sa.column("embedding_version", sa.String),
            sa.column("cluster_assignment_reconciled", sa.Boolean),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        )
        op.bulk_insert(compiled_claim_table, rows_to_insert)


def downgrade() -> None:
    """No-op — we do not delete backfilled claims on downgrade.

    The claims are valid data regardless of migration direction.
    """
