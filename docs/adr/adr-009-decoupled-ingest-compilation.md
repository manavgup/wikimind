# ADR-009: Decoupled ingest and compilation

## Status

Accepted

## Context

Ingest endpoints were crashing with `redis.exceptions.ConnectionError` because
`IngestService._enqueue_compilation()` called `arq.create_pool()` which tried
to connect to Redis on localhost:6379. The fakeredis library listed in
dependencies cannot work with ARQ across processes (ARQ workers run in a
separate process with separate memory, so an in-process fake broker is
invisible to the worker). This meant every ingest call failed without a running
Redis instance, breaking the zero-dependency dev experience promised by ADR-001.

Ingest and compilation are fundamentally different operations:

- **Ingest** is fast I/O: fetch a URL, save a file, persist a Source row.
  Typical latency is under 100 ms.
- **Compilation** is slow LLM work: read the raw file, call an LLM API, parse
  the response, save an Article. Typical latency is 10-30 seconds.

Coupling them via a synchronous `await enqueue_compile()` in the ingest path
meant that ingest could not succeed unless the job queue broker was reachable.

## Decision

Decouple ingest from compilation. Ingest saves the source and returns
immediately. Compilation is scheduled asynchronously by a new
`BackgroundCompiler` class (`wikimind.jobs.background`).

`BackgroundCompiler` has two modes:

1. **Dev mode** (no `REDIS_URL` environment variable): uses
   `asyncio.create_task()` to run `compile_source()` in the same process as
   the API server. No Redis required.
2. **Prod mode** (`REDIS_URL` is set): uses `arq.create_pool()` to enqueue
   the job via Redis, where a separate ARQ worker picks it up.

Both modes emit WebSocket progress events identically because the underlying
`compile_source()` and `lint_wiki()` job functions are the same.

The service layer (`wikimind.services.ingest`) calls
`background_compiler.schedule_compile(source.id)` after the adapter returns.
The compiler service (`wikimind.services.compiler`) uses `BackgroundCompiler`
for `trigger_compile()` and `trigger_lint()`.

## Alternatives Considered

**fakeredis wired into ARQ** -- fakeredis runs in-process. ARQ workers run as
a separate process (`arq wikimind.jobs.worker.WorkerSettings`). The worker
process would have its own fakeredis instance with no jobs in it. This
fundamentally cannot work for cross-process job dispatch.

**Synchronous compilation in the ingest path** -- Would block the API for
10-30 seconds per ingest call, making the UI unresponsive and preventing
parallel ingestion.

**Always require Redis** -- Adds an infrastructure dependency for local
development, violating the zero-dependency principle from ADR-001.

## Revision (2026-04-15)

Recompilation is now a first-class action triggered via API, not just at
ingest time. See ADR-016 for details. The same `BackgroundCompiler` class
handles both initial compilation and recompilation jobs.

## Consequences

**Enables:**
- Zero-dependency dev startup: `make dev` works without Redis
- Ingest endpoints return immediately (< 100 ms) in all environments
- Same user experience in dev and prod: WebSocket progress events fire in both
  modes
- The ARQ worker still works unchanged in production

**Constrains:**
- In dev mode, compilation runs in the API server process. A hung LLM call
  will not block the event loop (it is async) but will consume memory. This is
  acceptable for local development.
- `asyncio.create_task()` fire-and-forget means dev-mode compilation failures
  are logged but not surfaced via the HTTP response. This matches the prod
  behavior where ARQ job failures are also asynchronous.

**Supersedes:**
- ADR-002 (ARQ + fakeredis): fakeredis is no longer used for job dispatch.
  ARQ remains the production queue, but dev mode uses in-process async tasks.
