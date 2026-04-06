# ADR-002: ARQ + fakeredis for job queue

## Status

Accepted

## Context

Source compilation is the most expensive operation in WikiMind: each source
requires one or more LLM API calls that can take 5-30 seconds. This work must
happen asynchronously so the API remains responsive. We need a job queue that
supports async Python, provides job progress tracking, and integrates with our
WebSocket event bus to push real-time status updates to the UI.

Consistent with ADR-001, we want zero-dependency startup. A new developer should
not need to install or run Redis just to work on WikiMind locally.

## Decision

We chose **ARQ** as the async job queue and use **fakeredis** as the default
broker for local development.

ARQ is a lightweight async-native job queue built on Redis. It supports job
priorities, timeouts (`job_timeout=300`), result retention (`keep_result=3600`),
cron scheduling (weekly linter runs), and integrates naturally with our async
codebase. The worker runs as a separate process via
`arq wikimind.jobs.worker.WorkerSettings`.

For local development, `get_redis_settings()` returns localhost settings. In CI
and dev environments, we rely on fakeredis or a local Redis instance. In
production, a real `REDIS_URL` environment variable points to an actual Redis
server.

Job functions (`compile_source`, `lint_wiki`) emit WebSocket events at each
progress stage (10%, 30%, 50%, 80%, 100%) so the UI can show live compilation
status.

## Alternatives Considered

**Celery** -- The most popular Python task queue, but it is synchronous by design.
Running async code in Celery requires workarounds (`asgiref.sync_to_async` or
running a nested event loop). It also pulls in a large dependency tree and
requires a separate broker (RabbitMQ or Redis). Overweight for a local-first app.

**RQ (Redis Queue)** -- Simpler than Celery but also synchronous. No native
async support, no built-in cron scheduling, and limited job progress reporting.

**Dramatiq** -- Good middleware system but, like Celery, primarily synchronous.
The async story requires third-party extensions.

**In-process asyncio.Queue** -- Simplest option but jobs would not survive
process restarts, and there would be no isolation between the API server and
worker. A hung LLM call could block the event loop.

## Consequences

**Enables:**
- Non-blocking compilation: users can ingest multiple sources and watch
  progress in real time via WebSocket
- Cron-scheduled linter runs (Monday 2am) without a separate scheduler
- Clean separation between API process and worker process
- `max_jobs=4` prevents overwhelming the LLM API with parallel requests

**Constrains:**
- ARQ requires a Redis-compatible broker; in production, Redis must be available
- Job state is ephemeral (Redis-based); long-term job history is tracked in the
  SQLite `job` table instead

**Risks:**
- fakeredis does not perfectly replicate Redis behavior in edge cases; integration
  tests should run against real Redis in CI
