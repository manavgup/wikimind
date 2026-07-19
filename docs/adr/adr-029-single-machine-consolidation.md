# ADR-029: Single-Machine Consolidation — Web, Worker, and Redis in One Scale-to-Zero Process

## Status

Accepted

**Date:** 2026-07-19

## Context

Through June 2026, the Fly.io production deployment ran three always-on pieces:

| Component | Machine | Monthly cost |
|-----------|---------|-------------|
| Web (gunicorn) | `web` — scale-to-zero | ~$1/mo |
| ARQ worker | dedicated `worker` machine (24/7) | ~$5/mo |
| Redis | self-hosted `wikimind-redis` Fly app (24/7) | ~$5/mo |

The worker and Redis machines could not scale to zero: the worker must be up to drain queued jobs, and Redis must persist the queue. Together they kept monthly infrastructure costs near $10/mo after an earlier phase that had already eliminated Upstash managed Redis and the staging environment.

The goal for this phase: reduce costs to ~$4-5/mo by eliminating the always-on worker and Redis Fly apps entirely, while keeping all existing functionality.

The key insight: WikiMind is a personal-scale deployment. Background jobs (compilation, linting, billing reconciliation, ambient ingest polling) are initiated by user actions or webhooks that wake the web machine anyway. Running the worker and Redis co-located with gunicorn on the same machine means the entire stack can scale to zero together and wake as a unit.

PostgreSQL (`wikimind-db`) deliberately remains a separate Fly Postgres app. It holds real billing and user data; migrating it is a separate decision with different risk and cost characteristics.

## Decision

Consolidate web, ARQ worker, and Redis into a single `web` Fly machine via `docker/start-combined.sh`. The startup sequence:

1. **Redis** starts first (`redis-server` with AOF and 128 MB maxmemory, no RDB), persisting its append-only-file data directory to the Fly volume. No restart loop — if it crashes, a machine restart self-heals.
2. **ARQ worker** starts in a `while true` restart loop. The worker is long-running (no burst mode); the loop is crash-recovery supervision so a worker crash cannot kill the container.
3. **Gunicorn** starts last and becomes the governing process. When gunicorn exits (SIGTERM from Fly), the script traps the signal, drains gunicorn and ARQ first, then sends TERM to Redis so its AOF flush covers all pending writes.

`fly.toml` changes:

- `kill_timeout = 60` — gives the ordered shutdown script 60 s before Fly sends SIGKILL.
- `WIKIMIND_REDIS_URL = "redis://localhost:6379/0"` moved from a Fly secret to `[env]` in `fly.toml`. **The deploy pipeline actively fails if a stale `WIKIMIND_REDIS_URL` secret exists**, because Fly secrets always override `[env]` values and the stale secret would point at the now-deleted external Redis app.
- VM sized to 2 GB (3 gunicorn workers + ARQ + Redis comfortably within the 2 GB budget; see ADR-024 for the gunicorn worker sizing formula).

Redis flags chosen:

| Flag | Value | Rationale |
|------|-------|-----------|
| `maxmemory` | 128 MB | Hard cap; Redis stays well within the 2 GB VM budget |
| `maxmemory-policy` | `noeviction` | Refuse new writes rather than evict queued jobs silently |
| `appendonly yes` | enabled | AOF durability: worst-case ~1 s of enqueues lost on hard kill |
| `--save ""` | disabled | No RDB snapshots — avoids double-persistence with AOF on the volume |

The docling-serve sidecar (ADR-025) remains a separate scale-to-zero Fly app (`wikimind-docling`). Its resource footprint (~4 GB image, GPU-adjacent ML workload) makes co-location impractical, and it is already stateless and independently scalable.

## Consequences

### Positive

- **Cost**: ~$10/mo → ~$4-5/mo; worker machine and Redis Fly app eliminated.
- **Unified lifecycle**: the entire application stack — HTTP, background jobs, and cache — scales to zero as a single unit and wakes together on the first request.
- **Simpler deploy pipeline**: no separate `fly deploy --config fly.redis.toml` step; no worker machine management. The `fly-setup.sh` script is 27 lines shorter.
- **Queue durability preserved**: AOF on the persistent volume survives machine restarts (not just process restarts). Jobs survive controlled stop/start cycles.
- **Operational coherence**: one `fly logs`, one `fly ssh console`, one machine to monitor.

### Negative

- **Cron jobs are opportunistic**: ARQ cron jobs (weekly lint, daily wikilink sweep, 6-hourly subscription and price reconciliation, 30-min ambient poll) only run while the machine is awake. Webhooks and user requests wake it; scheduled crons fire on the next wake cycle after their due time. Acceptable for personal-scale; not acceptable for a multi-user SLA.
- **Redis has no restart loop**: gunicorn and ARQ are restarted on crash; Redis is not. If Redis crashes mid-session, `/health` remains green (it does not ping Redis) while job enqueues fail silently; `/health/deep` does report Redis. The machine's next auto-stop/auto-start cycle self-heals. This is a known resilience regression relative to the dedicated Redis machine's native Fly restart policy.
- **Rollback requires matching pairs**: rolling back across this deploy boundary requires the matching `fly.toml` + image pair. Old images lack `/app/start-combined.sh` and will crash if deployed with the new `fly.toml` process commands.
- **Queue durability window**: AOF `everysec` means up to ~1 s of enqueues can be lost on a hard kill (SIGKILL before the 60 s kill_timeout elapses). Controlled shutdowns lose nothing.

## Supersedes

- The operational configuration described in [ADR-023](adr-023-production-container-architecture.md) (separate `worker` Fly machine) and the Redis Fly app established in a prior phase are superseded by this consolidation. ADR-023's Docker Compose production stack (separate `worker` and `redis` services) remains unchanged for self-hosted deployments; only the Fly.io runtime topology changes.
