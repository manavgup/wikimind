"""Add concept-layer and compilation-schema tables.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-09

Adds four tables introduced in PRs #522/#521 that were never given their
own migration:

- ``compiledclaim``     (was ``compiled_claim`` in #522, renamed in #541)
- ``conceptcluster``    (was ``concept_cluster``)
- ``claimconcept``      (was ``claim_concept``)
- ``compilationschema`` (was ``compilation_schema`` in #521)

Handles four deployment scenarios:
1. **Fresh DB** — tables don't exist yet: create them.
2. **Old names only** (``compiled_claim`` etc.) — rename to ORM-expected names.
3. **Both old and new exist** — ``create_all()`` created empty new-name tables
   alongside populated old-name tables. Drop the empty new tables, then rename
   old tables to new names (preserving data).
4. **New names already present, old names gone** — no-op.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mapping: (new_name, old_name_if_renamed)
_RENAME_MAP: list[tuple[str, str]] = [
    ("compiledclaim", "compiled_claim"),
    ("conceptcluster", "concept_cluster"),
    ("claimconcept", "claim_concept"),
    ("compilationschema", "compilation_schema"),
]


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    inspector = sa_inspect(conn)
    return table in inspector.get_table_names()


def _repair_concept_layer_name_collisions(conn: sa.engine.Connection) -> None:
    """Repair the old+new table-name collision for the concept-layer tables.

    ``claimconcept`` depends on both parent tables, so its new-name copy must be
    dropped before replacing ``compiledclaim`` / ``conceptcluster``.
    """
    if _table_exists(conn, "claimconcept") and _table_exists(conn, "claim_concept"):
        op.drop_table("claimconcept")

    for new_name, old_name in [
        ("compiledclaim", "compiled_claim"),
        ("conceptcluster", "concept_cluster"),
    ]:
        has_new = _table_exists(conn, new_name)
        has_old = _table_exists(conn, old_name)
        if has_new and has_old:
            op.drop_table(new_name)
            op.rename_table(old_name, new_name)
        elif not has_new and has_old:
            op.rename_table(old_name, new_name)

    if not _table_exists(conn, "claimconcept") and _table_exists(conn, "claim_concept"):
        op.rename_table("claim_concept", "claimconcept")


def _create_compiledclaim() -> None:
    op.create_table(
        "compiledclaim",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "article_id",
            sa.String(),
            sa.ForeignKey("article.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("user.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("subjects", sa.String(), nullable=False, server_default="[]"),
        sa.Column("predicate", sa.String(), nullable=True),
        sa.Column("confidence_level", sa.String(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source_ids", sa.String(), nullable=False, server_default="[]"),
        sa.Column("last_reinforced_at", sa.DateTime(), nullable=False),
        sa.Column("quote", sa.String(), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_version", sa.String(), nullable=True),
        sa.Column(
            "cluster_assignment_reconciled",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def _create_conceptcluster() -> None:
    op.create_table(
        "conceptcluster",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("user.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("canonical_text", sa.String(), nullable=False),
        sa.Column("centroid_embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_version", sa.String(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="candidate"),
        sa.Column(
            "superseded_by",
            sa.String(),
            sa.ForeignKey("conceptcluster.id"),
            nullable=True,
        ),
        sa.Column("last_reinforced_at", sa.DateTime(), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def _create_claimconcept() -> None:
    op.create_table(
        "claimconcept",
        sa.Column(
            "claim_id",
            sa.String(),
            sa.ForeignKey("compiledclaim.id"),
            primary_key=True,
        ),
        sa.Column(
            "concept_id",
            sa.String(),
            sa.ForeignKey("conceptcluster.id"),
            primary_key=True,
            index=True,
        ),
        sa.Column("role", sa.String(), primary_key=True),
        sa.Column("advisory", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _create_compilationschema() -> None:
    op.create_table(
        "compilationschema",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("user.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("article_max_length", sa.Integer(), nullable=True),
        sa.Column("required_sections", sa.String(), nullable=True),
        sa.Column("style", sa.String(), nullable=True),
        sa.Column("focus", sa.String(), nullable=True),
        sa.Column("concept_max_depth", sa.Integer(), nullable=True),
        sa.Column("concept_naming", sa.String(), nullable=True),
        sa.Column("extraction_always_note", sa.String(), nullable=True),
        sa.Column("extraction_ignore", sa.String(), nullable=True),
        sa.Column("custom_directives", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_compilationschema_user_name"),
    )


# Table creation functions keyed by new table name.
_CREATORS: dict[str, callable] = {
    "compiledclaim": _create_compiledclaim,
    "conceptcluster": _create_conceptcluster,
    "claimconcept": _create_claimconcept,
    "compilationschema": _create_compilationschema,
}


def upgrade() -> None:
    """Create or rename concept-layer and compilation-schema tables.

    Order matters: ``compiledclaim`` and ``conceptcluster`` must exist
    before ``claimconcept`` (which has foreign keys to both).
    """
    conn = op.get_bind()

    _repair_concept_layer_name_collisions(conn)

    # Process any remaining independent cases after collision repair.
    ordered = [
        ("compiledclaim", "compiled_claim"),
        ("conceptcluster", "concept_cluster"),
        ("compilationschema", "compilation_schema"),
        ("claimconcept", "claim_concept"),
    ]
    for new_name, old_name in ordered:
        has_new = _table_exists(conn, new_name)
        has_old = _table_exists(conn, old_name)

        if has_new and has_old:
            # Only ``compilationschema`` can still reach this path. The
            # concept-layer collision is handled above to respect FK ordering.
            op.drop_table(new_name)  # rollback-safe: drops empty duplicate before rename
            op.rename_table(old_name, new_name)
        elif has_new:
            # Scenario 4: already migrated — nothing to do.
            continue
        elif has_old:
            # Scenario 2: deployed DB has old name only — rename it.
            op.rename_table(old_name, new_name)
        else:
            # Scenario 1: fresh deploy — create from scratch.
            _CREATORS[new_name]()


def downgrade() -> None:
    """Drop tables created in :func:`upgrade`.

    Reverse dependency order: drop ``claimconcept`` first (it references
    the other two), then the rest.
    """
    conn = op.get_bind()
    for table in ["claimconcept", "compilationschema", "conceptcluster", "compiledclaim"]:
        if _table_exists(conn, table):
            op.drop_table(table)
