# ADR-001: FastAPI + async SQLite for local-first daemon

## Status

Accepted

## Context

WikiMind runs as a local daemon on the user's machine, serving a REST + WebSocket
API on `localhost:7842`. The framework choice directly affects startup time, async
support, developer productivity, and the ability to run without external services.

The database must store metadata (sources, articles, jobs, cost logs) while article
content lives as plain markdown files on disk (see ADR-004). The database therefore
needs to handle structured queries and relationships, not large blobs of text.

A core design principle is **zero-dependency startup**: a new user runs `make dev`
and has a working system without installing Postgres, Redis, or any other service.

## Decision

We chose **FastAPI** as the web framework and **SQLite** (via aiosqlite + SQLModel)
as the metadata database.

FastAPI provides native async support, automatic OpenAPI documentation, and Pydantic
integration for request/response validation. Its dependency injection system via
`Depends()` keeps route handlers thin and testable. WebSocket support is built in,
which we use for real-time job progress events.

SQLite is embedded, requires no server process, and stores everything in a single
file at `~/.wikimind/db/wikimind.db`. This makes backups trivial (copy one file),
supports the local-first privacy model, and eliminates deployment complexity.
We use `aiosqlite` for async I/O so database calls do not block the event loop.

## Alternatives Considered

**Django** -- Full-featured but heavyweight for a local daemon. Its ORM is
synchronous by default, admin interface is unnecessary for a desktop app, and
startup time is noticeably slower. Django's batteries-included philosophy adds
dependencies we do not need.

**Flask** -- Lightweight but lacks native async support and requires additional
libraries (Flask-SocketIO, Flask-SQLAlchemy) to match FastAPI's built-in
capabilities. No automatic OpenAPI generation.

**PostgreSQL** -- Superior for multi-user server deployments but requires a
separate process, installation, and configuration. Violates the zero-dependency
startup principle. Our data volume (metadata for a personal wiki) never exceeds
what SQLite handles well.

**DuckDB** -- Excellent for analytics workloads but less mature for OLTP-style
read/write patterns. Limited async driver support at the time of this decision.

## Consequences

**Enables:**
- Single-binary-like deployment: one `uvicorn` process serves everything
- Zero external dependencies for development or production
- Trivial backup and portability (copy `~/.wikimind/` to another machine)
- Tests use in-memory SQLite with no setup

**Constrains:**
- SQLite write concurrency is limited to one writer at a time; the ARQ worker
  and the API server must coordinate via WAL mode
- If WikiMind ever becomes multi-user, SQLite will need to be replaced with
  Postgres (but the SQLModel abstraction makes this a manageable migration)

**Risks:**
- WAL mode contention under heavy parallel compilation jobs; mitigated by
  limiting `max_jobs=4` in the ARQ worker configuration

## Amendment (2026-04-17): PostgreSQL support added

As of ADR-021, the database layer is dialect-aware. SQLite remains the default
for development and testing (zero-dependency startup principle unchanged).
Production deployments can use PostgreSQL by setting `WIKIMIND_DATABASE_URL` to a
`postgresql+asyncpg://` URL.

The constraint noted above -- "If WikiMind ever becomes multi-user, SQLite will
need to be replaced with Postgres" -- is now addressed for the shared-backend
multi-device use case, though WikiMind remains single-user.
