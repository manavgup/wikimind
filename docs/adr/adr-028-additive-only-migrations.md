# ADR-028: Additive-Only Migration Policy for Schema-Safe Rollback

## Status

Accepted

## Context

The deploy pipeline rolls back production by redeploying the previous Docker image
when post-deploy verification fails. Each image runs `alembic upgrade head` on
startup via `release_command` in `fly.toml`. This means:

1. A deploy applies forward migrations (new columns, tables).
2. On rollback, the old image runs its own `alembic upgrade head` — a no-op since
   its migration set is a subset of what's already applied.
3. The old code runs against a database that may have extra columns/tables it
   doesn't know about — which is fine.

The problem: if a migration drops a column or table, the rolled-back image expects
schema objects that no longer exist, causing runtime crashes.

Three options were evaluated:

| Option | Approach | Tradeoff |
|--------|----------|----------|
| 1 | Additive-only migrations, enforced by CI | Simple, safe, prevents the problem |
| 2 | Alembic downgrade step in rollback job | Fragile, downgrade() rarely tested in production |
| 3 | Manual approval gate for schema changes | Adds friction, no automation |

## Decision

**Option 1: Additive-only migrations with CI enforcement.**

All Alembic migration `upgrade()` functions must be backward-compatible. The
`migration-safety` CI workflow runs `scripts/check_migration_safety.py` which
uses AST analysis to detect destructive operations:

- `op.drop_table()`
- `op.drop_column()`
- `op.alter_column(..., type_=...)` (column type changes)
- Raw SQL containing `DROP TABLE` or `DROP COLUMN`

Safe operations are allowed: `DROP INDEX`, `DROP CONSTRAINT`, `CREATE TABLE`,
`ADD COLUMN`, `CREATE INDEX`, data-only changes.

Lines annotated with `# rollback-safe: <reason>` are exempted for rare cases
where a destructive operation is genuinely safe (e.g., dropping an empty
duplicate table during a rename).

For genuine destructive changes, use a two-phase deploy:
1. Deploy code that stops using the column/table.
2. Separate PR to drop the column/table from the schema.

## Consequences

- Rollback is always schema-safe — the old image can work with extra schema objects.
- Developers must plan destructive schema changes as two-phase deploys.
- The CI check catches mistakes before merge, not after production breakage.
- Legacy migration 0010 has one exempted `drop_table` (table rename collision repair).
