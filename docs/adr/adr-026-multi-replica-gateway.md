# ADR-026: Multi-Replica Gateway — Horizontal Scaling

**Status:** Accepted  
**Date:** 2026-04-21  
**Issue:** [#212](https://github.com/manavgup/wikimind/issues/212)  
**Supersedes:** ADR-024 blocker list (items 1–3 resolved)

## Context

ADR-024 identified four blockers preventing the gateway from running as multiple replicas behind a load balancer. Each blocker involved in-process state that would diverge across replicas:

1. **WebSocket `ConnectionManager`** — per-process `set[WebSocket]` meant broadcasts only reached clients on the same replica.
2. **ChromaDB `PersistentClient`** — writes to local SQLite, unsafe for concurrent writers.
3. **LLM budget tracking** — `_budget_warning_sent` / `_budget_exceeded_sent` flags were per-process, causing duplicate alerts.
4. **`BackgroundCompiler` queue** — needed verification.

## Decision

### 1. WebSocket broadcasts — Redis Pub/Sub

`ConnectionManager.broadcast()` now publishes events to a Redis Pub/Sub channel (`wikimind:ws:broadcast`). Each replica runs a background subscriber task that receives messages from the channel and delivers them to its local WebSocket connections via `_local_broadcast()`.

**Fallback:** When `Settings.redis_url` is not set (dev mode), `broadcast()` calls `_local_broadcast()` directly — identical to the pre-change behavior.

**Why Pub/Sub over Redis Streams:** Pub/Sub is fire-and-forget, which matches WebSocket event semantics (no need for replay or persistence). It adds zero storage overhead and the `redis` package is already a transitive dependency of `arq`.

### 2. ChromaDB — single-writer via ARQ

ChromaDB's `PersistentClient` writes to local SQLite, which cannot handle concurrent writers from multiple replicas. Analysis shows that `embed_article()` (the only write path) is already called exclusively from `worker.py`, which runs as a single ARQ process — making it inherently single-writer safe. `search()` is read-only and safe from any replica.

The `EmbeddingService` docstring now documents this single-writer contract. No code changes were needed because the architecture was already correct.

**Future:** When search volume justifies it, replace ChromaDB with a managed vector database (pgvector, Qdrant) that supports concurrent writes natively.

### 3. Budget tracking — Redis-backed dedup flags

The `_budget_warning_sent` and `_budget_exceeded_sent` flags now check and set Redis keys (with 35-day TTL) in addition to the per-process in-memory cache. This prevents duplicate budget alerts across replicas.

**Redis key pattern:** `wikimind:budget:{flag_name}:{year}:{month}`

**Fallback:** When Redis is unavailable, falls back to per-process flags — same behavior as before.

### 4. BackgroundCompiler — already safe

`BackgroundCompiler` already routes jobs through ARQ/Redis in production mode. The ARQ worker is a single process that dequeues and executes jobs sequentially, so no state conflicts arise regardless of how many gateway replicas are running.

## Alternatives Considered

- **Dedicated Redis Streams for WebSocket events** — provides replay and persistence. Overkill for real-time UI events where missed events are harmless (the client can always refresh state via REST).
- **Postgres LISTEN/NOTIFY for WebSocket pub/sub** — avoids adding Redis as a dependency. However, Redis is already required for ARQ, and LISTEN/NOTIFY has lower throughput and no built-in pattern matching.
- **Replace ChromaDB with pgvector** — would eliminate the single-writer constraint. Deferred because the current single-writer pattern is already safe and pgvector migration is a separate project.
- **Move budget flags to Postgres** — adds a DB write per LLM call. Redis is faster and the flags have no durability requirement (they reset monthly).

## Consequences

- The gateway can now run as 2+ replicas behind a load balancer when Redis is configured
- WebSocket events reach all connected clients regardless of which replica they're connected to
- Budget alerts fire exactly once per threshold crossing, not once per replica
- ChromaDB writes remain safe through the existing single-writer ARQ pattern
- No behavioral change in single-replica mode (no Redis required for dev)
- The `redis` package is now an explicit dependency (was already transitively required by `arq`)
