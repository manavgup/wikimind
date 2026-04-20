"""Add ArticleConcept and ArticleSource join tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-19

Replaces JSON-array columns (Article.concept_ids, Article.source_ids) with
proper join tables for indexed lookups. Migrates existing JSON data into the
new tables. The old columns are kept temporarily for rollback safety.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn, table: str) -> bool:
    """Check if a table already exists."""
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def upgrade() -> None:
    """Create join tables and migrate existing JSON data."""
    conn = op.get_bind()

    # --- Create ArticleConcept ---
    if not _table_exists(conn, "articleconcept"):
        op.create_table(
            "articleconcept",
            sa.Column("article_id", sa.String(), sa.ForeignKey("article.id"), primary_key=True),
            sa.Column("concept_name", sa.String(), primary_key=True, index=True),
        )

    # --- Create ArticleSource ---
    if not _table_exists(conn, "articlesource"):
        op.create_table(
            "articlesource",
            sa.Column("article_id", sa.String(), sa.ForeignKey("article.id"), primary_key=True),
            sa.Column("source_id", sa.String(), sa.ForeignKey("source.id"), primary_key=True, index=True),
        )

    # --- Migrate existing JSON data ---
    rows = conn.execute(
        sa.text("SELECT id, concept_ids, source_ids FROM article")
    ).fetchall()

    for article_id, concept_ids_raw, source_ids_raw in rows:
        if concept_ids_raw:
            try:
                concept_names = json.loads(concept_ids_raw)
                if isinstance(concept_names, list):
                    for name in concept_names:
                        if name:
                            conn.execute(
                                sa.text(
                                    "INSERT OR IGNORE INTO articleconcept (article_id, concept_name) "
                                    "VALUES (:article_id, :concept_name)"
                                ),
                                {"article_id": article_id, "concept_name": str(name)},
                            )
            except (json.JSONDecodeError, TypeError):
                pass

        if source_ids_raw:
            try:
                source_ids = json.loads(source_ids_raw)
                if isinstance(source_ids, list):
                    for sid in source_ids:
                        if sid:
                            conn.execute(
                                sa.text(
                                    "INSERT OR IGNORE INTO articlesource (article_id, source_id) "
                                    "VALUES (:article_id, :source_id)"
                                ),
                                {"article_id": article_id, "source_id": str(sid)},
                            )
            except (json.JSONDecodeError, TypeError):
                pass


def downgrade() -> None:
    """Drop join tables (JSON columns are still intact for rollback)."""
    op.drop_table("articlesource")
    op.drop_table("articleconcept")
