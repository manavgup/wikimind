# ADR-021: PostgreSQL compatibility for production deployments

## Status

Accepted

## Context

WikiMind was built as a local-first application with SQLite (ADR-001). As we
add cloud deployment support (see design spec: cloud-deployment-design.md),
production instances need a shared database that multiple devices can connect to
concurrently. SQLite's single-writer limitation and file-based storage make it
unsuitable for this use case.

## Decision

Make the database layer dialect-aware so it works on both SQLite (dev/test) and
PostgreSQL (production) with zero application logic changes.

**Configuration:** A single `WIKIMIND_DATABASE_URL` setting selects the backend.
It defaults to `sqlite+aiosqlite:///{data_dir}/db/wikimind.db` so the zero-
dependency dev experience is unchanged.

**Engine creation:** The URL scheme determines the async driver and connection
parameters. SQLite uses `aiosqlite` with `check_same_thread=False`. PostgreSQL
uses `asyncpg` with connection pooling (`pool_size=10`, `max_overflow=20`,
`pool_pre_ping=True`).

**Schema management:** SQLite uses `create_all()` plus lightweight column
migration helpers (fast, no Alembic overhead). PostgreSQL uses Alembic with an
initial migration generated from SQLModel definitions. Deployments run
`alembic upgrade head` before starting the server.

**Query compatibility:** SQLite-specific constructs are replaced with
dialect-aware helpers:
- `PRAGMA table_info` -> `Inspector.get_columns()` (SQLAlchemy)
- `json_each()` -> `jsonb_array_elements_text()` (via helper function)
- `.contains()` on TEXT -> `@>` on JSONB (via helper function)
- `?` positional params -> `:named` params (SQLAlchemy `text()`)

## Alternatives Considered

**Full Alembic for both dialects** -- Adds overhead to dev startup and test runs
for no benefit. SQLite's `create_all()` is instantaneous and perfectly reliable
for ephemeral dev databases.

**Separate PostgreSQL-specific models** -- Would duplicate the entire model layer
and create a maintenance burden.

**CockroachDB** -- Wire-compatible with PostgreSQL but adds operational complexity
and cost for a single-user system.

## Consequences

**Enables:**
- Production deployment to any managed Postgres service (Supabase, Neon, RDS)
- Multiple devices sharing the same database
- Future horizontal scaling if needed

**Constrains:**
- Raw SQL must use named parameters (`:name`) instead of positional (`?`)
- New queries involving JSON arrays must use the `db_compat` helpers
- PostgreSQL deployments require running Alembic migrations before startup

**Risks:**
- Dialect-specific bugs that only surface in one backend; mitigated by running
  the full test suite on both SQLite and (in CI) PostgreSQL
