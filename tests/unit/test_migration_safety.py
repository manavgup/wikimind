"""Tests for scripts/check_migration_safety.py."""

import textwrap
from pathlib import Path

import pytest

from scripts.check_migration_safety import check_file


def _write_migration(tmp_path: Path, code: str) -> Path:
    """Write a migration file and return the path."""
    p = tmp_path / "test_migration.py"
    p.write_text(textwrap.dedent(code))
    return p


class TestCheckFile:
    """Tests for the check_file function."""

    def test_additive_migration_passes(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.create_table("foo", sa.Column("id", sa.String(), primary_key=True))
                op.add_column("bar", sa.Column("name", sa.String()))

            def downgrade():
                op.drop_table("foo")
                op.drop_column("bar", "name")
            """,
        )
        assert check_file(p) == []

    def test_drop_table_in_upgrade_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.drop_table("old_table")

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "drop_table" in violations[0]
        assert "not rollback-safe" in violations[0]

    def test_drop_column_in_upgrade_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.drop_column("users", "legacy_field")

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "drop_column" in violations[0]

    def test_alter_column_type_change_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.alter_column("users", "age", type_=sa.BigInteger())

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "alter_column" in violations[0]
        assert "type" in violations[0].lower()

    def test_alter_column_nullable_change_passes(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.alter_column("users", "name", nullable=True)

            def downgrade():
                pass
            """,
        )
        assert check_file(p) == []

    def test_raw_sql_drop_table_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.execute("DROP TABLE old_data")

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "DROP TABLE" in violations[0]

    def test_raw_sql_drop_column_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.execute("ALTER TABLE users DROP COLUMN legacy")

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "DROP COLUMN" in violations[0]

    def test_drop_index_passes(self, tmp_path: Path) -> None:
        """DROP INDEX is safe — indexes don't affect correctness."""
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.drop_index("ix_old_index", table_name="users")

            def downgrade():
                pass
            """,
        )
        assert check_file(p) == []

    def test_drop_constraint_passes(self, tmp_path: Path) -> None:
        """DROP CONSTRAINT is safe — relaxing constraints is backward-compatible."""
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.drop_constraint("uq_old_constraint", "users", type_="unique")

            def downgrade():
                pass
            """,
        )
        assert check_file(p) == []

    def test_rollback_safe_comment_exempts(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                op.drop_table("dup")  # rollback-safe: drops empty duplicate before rename

            def downgrade():
                pass
            """,
        )
        assert check_file(p) == []

    def test_destructive_in_downgrade_ignored(self, tmp_path: Path) -> None:
        """Destructive ops in downgrade() are fine — downgrade is manual."""
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.create_table("foo", sa.Column("id", sa.String(), primary_key=True))

            def downgrade():
                op.drop_table("foo")
                op.drop_column("bar", "name")
            """,
        )
        assert check_file(p) == []

    def test_destructive_in_helper_function_ignored(self, tmp_path: Path) -> None:
        """Destructive ops in helper functions (not upgrade) are not flagged.

        Note: this is a known limitation — we only check the direct AST
        of upgrade(), not called helper functions. Helper functions with
        destructive ops called from upgrade() would need manual review.
        """
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def _cleanup():
                op.drop_table("old_table")

            def upgrade():
                _cleanup()

            def downgrade():
                pass
            """,
        )
        assert check_file(p) == []

    def test_multiple_violations_reported(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.drop_table("old_table")
                op.drop_column("users", "legacy")
                op.alter_column("users", "age", type_=sa.BigInteger())

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 3

    def test_batch_op_drop_column_fails(self, tmp_path: Path) -> None:
        p = _write_migration(
            tmp_path,
            """\
            from alembic import op

            def upgrade():
                with op.batch_alter_table("users") as batch_op:
                    batch_op.drop_column("legacy_field")

            def downgrade():
                pass
            """,
        )
        violations = check_file(p)
        assert len(violations) == 1
        assert "drop_column" in violations[0]


class TestExistingMigrations:
    """Verify all existing migrations pass the safety check."""

    def test_all_existing_migrations_pass(self) -> None:
        versions_dir = Path("alembic/versions")
        if not versions_dir.exists():
            pytest.skip("alembic/versions not found")

        all_violations: list[str] = []
        for filepath in sorted(versions_dir.glob("*.py")):
            violations = check_file(filepath)
            all_violations.extend(violations)

        assert all_violations == [], "Existing migrations have unexempted destructive operations:\n" + "\n".join(
            f"  {v}" for v in all_violations
        )
