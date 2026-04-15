# ADR-016: Article recompilation as a first-class action

## Status

Accepted

## Context

The Health Dashboard surfaces contradictions and orphans, but the only action
was "Dismiss." The detect-surface loop lacked the "act" step. Users needed to
manually find and re-ingest articles when the linter flagged issues.

Recompilation is needed in two forms:

1. **Source recompile** — re-read the raw file from disk, call the source
   compiler again. Picks up prompt improvements, schema changes, or source
   file updates.
2. **Concept re-synthesis** — re-run the concept compiler for a concept page.
   Incorporates new sources, contradiction resolutions, or updated source
   articles.

## Decision

Add `POST /wiki/articles/{article_id}/recompile` as a first-class API endpoint.
Recompilation is always asynchronous via BackgroundCompiler (extending
ADR-009's decoupled pattern). The endpoint:

1. Infers mode from the article's `page_type` (source vs concept) unless
   explicitly overridden via `?mode=source|concept`.
2. Creates a `Job` record with `job_type=RECOMPILE_ARTICLE`.
3. Schedules the job via `BackgroundCompiler` (dev: asyncio.create_task,
   prod: ARQ).
4. Returns `{"status": "scheduled", "job_id": "..."}` immediately.
5. Emits `article.recompiled` WebSocket event on completion.

The frontend shows an optimistic "Recompiling..." spinner and auto-refreshes
when the WebSocket event fires.

## Alternatives Considered

**Synchronous recompile.** Source recompiles take 10-30s (LLM call). Blocking
the API would make the UI unresponsive, inconsistent with the async pattern
established by ADR-009.

**Separate endpoints per mode.** Two endpoints (`/recompile-source`,
`/recompile-concept`) would be redundant. A single endpoint with mode
inference is simpler and handles the common case (infer from page_type)
without requiring the caller to know the distinction.

## Consequences

- Users can trigger recompilation directly from the Health Dashboard
- The detect-surface-act loop is closed
- Same async pattern as ingest compilation (ADR-009)
- Frontend gets optimistic UI via WebSocket events
