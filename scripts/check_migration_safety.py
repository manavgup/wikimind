"""Check Alembic migrations for destructive operations in upgrade() functions.

Policy: all auto-deployed migrations MUST be backward-compatible (additive only).
This ensures that a rollback to the previous Docker image leaves the database in a
state the old code can still work with.  Destructive schema changes (DROP TABLE,
DROP COLUMN, ALTER COLUMN type changes) require a manual two-phase deploy:

  Phase 1: Deploy code that no longer uses the column/table.
  Phase 2: A separate PR removes the column/table from the schema.

Allowed operations (additive / safe):
  - CREATE TABLE, ADD COLUMN, CREATE INDEX
  - ADD CONSTRAINT (non-destructive)
  - DROP INDEX (indexes are not required for correctness, only performance)
  - DROP CONSTRAINT (relaxing constraints is backward-compatible)
  - Data-only migrations (INSERT, UPDATE)

Forbidden operations in upgrade():
  - op.drop_table(...)
  - op.drop_column(...)
  - op.alter_column(..., type_=...)   [column type change]
  - Raw SQL containing DROP TABLE or DROP COLUMN

Lines with a ``# rollback-safe: <reason>`` comment are exempted.

Exit codes:
  0 — all migrations are safe
  1 — destructive operations found

Usage:
  python scripts/check_migration_safety.py                    # check all
  python scripts/check_migration_safety.py alembic/versions/0023_*.py  # check specific
"""

import ast
import sys
from pathlib import Path

# Operations that are destructive and forbidden in upgrade() functions.
FORBIDDEN_OPS = {"drop_table", "drop_column"}


class _DestructiveOpVisitor(ast.NodeVisitor):
    """AST visitor that finds destructive operations inside upgrade() functions."""

    def __init__(self, filepath: str, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []
        self._in_upgrade = False

    def _is_exempted(self, lineno: int) -> bool:
        """Return True if the line has a ``# rollback-safe:`` bypass comment."""
        if lineno < 1 or lineno > len(self.source_lines):
            return False
        return "# rollback-safe:" in self.source_lines[lineno - 1]

    def _check_forbidden_op(self, node: ast.Call) -> None:
        """Flag op.drop_table / op.drop_column / batch_op.drop_column."""
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr not in FORBIDDEN_OPS:
            return
        if self._is_exempted(node.lineno):
            return
        self.violations.append(
            f"{self.filepath}:{node.lineno}: op.{node.func.attr}() is destructive and not rollback-safe"
        )

    def _check_alter_column_type(self, node: ast.Call) -> None:
        """Flag op.alter_column(..., type_=...) — column type change."""
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr != "alter_column" or self._is_exempted(node.lineno):
            return
        for kw in node.keywords:
            if kw.arg == "type_":
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: op.alter_column(type_=...) changes column type — not rollback-safe"
                )
                break

    def _check_raw_sql(self, node: ast.Call) -> None:
        """Flag op.execute('... DROP TABLE/COLUMN ...')."""
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr != "execute" or self._is_exempted(node.lineno):
            return
        for arg in node.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            sql_upper = arg.value.upper()
            if "DROP TABLE" in sql_upper:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: raw SQL contains DROP TABLE — not rollback-safe"
                )
            if "DROP COLUMN" in sql_upper:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: raw SQL contains DROP COLUMN — not rollback-safe"
                )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "upgrade":
            self._in_upgrade = True
            self.generic_visit(node)
            self._in_upgrade = False
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not self._in_upgrade:
            self.generic_visit(node)
            return

        self._check_forbidden_op(node)
        self._check_alter_column_type(node)
        self._check_raw_sql(node)

        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    """Parse a migration file and return a list of violation messages."""
    source = filepath.read_text()
    source_lines = source.splitlines()
    tree = ast.parse(source, filename=str(filepath))
    visitor = _DestructiveOpVisitor(str(filepath), source_lines)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    """Check migration files for destructive operations.

    If positional arguments are provided, check only those files.
    Otherwise, check all files in alembic/versions/.
    """
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:]]
    else:
        versions_dir = Path("alembic/versions")
        if not versions_dir.exists():
            print("alembic/versions/ not found — skipping migration safety check")
            return 0
        files = sorted(versions_dir.glob("*.py"))

    all_violations: list[str] = []
    for filepath in files:
        if not filepath.exists():
            continue
        violations = check_file(filepath)
        all_violations.extend(violations)

    if all_violations:
        print("MIGRATION SAFETY CHECK FAILED")
        print("=" * 60)
        print()
        print("The following destructive operations were found in upgrade() functions:")
        print()
        for v in all_violations:
            print(f"  {v}")
        print()
        print("Policy: migrations must be additive-only (backward-compatible)")
        print("so that rollback to the previous image leaves the DB usable.")
        print()
        print("If you need to remove a column or table, use a two-phase deploy:")
        print("  Phase 1: Deploy code that stops using the column/table")
        print("  Phase 2: Separate PR to drop the column/table")
        print()
        print("To bypass this check (rare, requires justification):")
        print("  Add '# rollback-safe: <reason>' comment on the op line")
        return 1

    print(f"Migration safety check passed ({len(files)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
