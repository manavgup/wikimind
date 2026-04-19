"""Add user_id FK to all data tables for multi-user isolation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-17

Adds a nullable user_id column (FK to user.id) to all data tables.
Changes Article.slug and Concept.name from globally unique to composite
unique on (user_id, slug) and (user_id, name) respectively.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_TABLES = [
    "source",
    "article",
    "concept",
    "backlink",
    "conversation",
    "query",
    "job",
    "costlog",
    "synclog",
    "userpreference",
    "lintreport",
    "contradictionfinding",
    "orphanfinding",
    "structuralfinding",
]


def upgrade() -> None:
    """Add user_id column, indexes, and composite unique constraints."""
    for table in _DATA_TABLES:
        op.add_column(table, sa.Column("user_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
        op.create_foreign_key(f"fk_{table}_user_id", table, "user", ["user_id"], ["id"])

    # Replace Article.slug global unique with composite (user_id, slug)
    with op.batch_alter_table("article") as batch_op:
        batch_op.drop_constraint("uq_article_slug", type_="unique")
        batch_op.create_unique_constraint("uq_article_user_slug", ["user_id", "slug"])

    # Replace Concept.name global unique with composite (user_id, name)
    with op.batch_alter_table("concept") as batch_op:
        batch_op.drop_constraint("uq_concept_name", type_="unique")
        batch_op.create_unique_constraint("uq_concept_user_name", ["user_id", "name"])


def downgrade() -> None:
    """Remove user_id columns and restore global unique constraints."""
    with op.batch_alter_table("concept") as batch_op:
        batch_op.drop_constraint("uq_concept_user_name", type_="unique")
        batch_op.create_unique_constraint("uq_concept_name", ["name"])

    with op.batch_alter_table("article") as batch_op:
        batch_op.drop_constraint("uq_article_user_slug", type_="unique")
        batch_op.create_unique_constraint("uq_article_slug", ["slug"])

    for table in reversed(_DATA_TABLES):
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_user_id", table)
        op.drop_column(table, "user_id")
