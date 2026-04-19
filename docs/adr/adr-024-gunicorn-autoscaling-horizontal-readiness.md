# ADR-024: Gunicorn Auto-Scaling and Horizontal Scaling Readiness

**Status:** Accepted  
**Date:** 2026-04-18  
**Issue:** [#203](https://github.com/manavgup/wikimind/pull/203)

## Context

The initial production Dockerfile (ADR-023) hardcoded `gunicorn -w 2`, which doesn't adapt to the container's CPU allocation. A 4-CPU host wastes cores; a 1-CPU Fly.io machine runs more workers than it can sustain. We also had no infrastructure-level auto-scaling — Fly.io machines didn't know when to spin up additional instances.

## Decision

### 1. Process-level auto-tuning via `gunicorn.conf.py`

Workers are calculated as `min(2 * CPU_CORES + 1, 4)`:

| Container CPU | Workers |
|--------------|---------|
| 1 (Fly.io shared) | 3 |
| 2+ (compose default) | 4 (cap) |

Capped at 4 because each worker loads Docling/PyTorch ML models (~250-400 MB RSS). With the default 2 GB container memory limit, 4 workers × ~400 MB ≈ 1.6 GB — the safe maximum. Each uvicorn async worker handles many concurrent connections, so 4 workers is sufficient for high throughput. Increase the cap only if you also raise `deploy.resources.limits.memory`.

Operators override at runtime via the `WEB_CONCURRENCY` environment variable (read natively by gunicorn, no custom code):

```bash
WEB_CONCURRENCY=4 make deploy-up
```

### 2. Machine-level auto-scaling via Fly.io concurrency limits

```toml
[http_service.concurrency]
  type = "connections"
  hard_limit = 100
  soft_limit = 80
```

When connections exceed `soft_limit` on a machine, Fly automatically starts another. Combined with `auto_stop_machines = "stop"`, idle machines shut down — pay only for what you use.

### 3. Docker Compose horizontal scaling prep

Removed `container_name` from the gateway service. Docker Compose refuses `--scale` when `container_name` is set. This unblocks future `docker compose up --scale gateway=3` (requires a reverse proxy in front).

### Scaling tiers

| Tier | Mechanism | Approximate capacity |
|------|-----------|---------------------|
| Single container, auto-tuned workers | `gunicorn.conf.py` adapts to CPU | 30-50 concurrent users |
| Fly.io multi-machine | Concurrency-based auto-scaling | 100+ connections per machine |
| Docker Compose multi-replica | `--scale gateway=N` + reverse proxy | Requires resolving blockers below |

### Known blockers for multi-replica gateway

These must be resolved before running multiple gateway containers behind a load balancer:

1. **WebSocket `ConnectionManager`** — in-process `set[WebSocket]` means broadcasts only reach clients on the same replica. Fix: Redis Pub/Sub for cross-replica event distribution.
2. **ChromaDB `PersistentClient`** — writes to a local SQLite file, unsafe for concurrent writers across replicas. Fix: managed vector database (Qdrant, Weaviate) or route embedding writes through the worker.
3. **LLM budget tracking** — `_budget_warning_sent` flags in `LLMRouter` are per-process, causing duplicate alerts. Fix: move budget state to Redis or Postgres.
4. **Frontend `VITE_API_URL`** — baked in at build time, cannot redirect to a different backend without rebuilding. Fix: runtime configuration via `window.__CONFIG__` or relative URLs.

## Alternatives Considered

- **Keep hardcoded `-w 2`** — simple but wastes resources on larger machines and over-provisions on smaller ones.
- **Kubernetes HPA** — auto-scales pods based on CPU/memory metrics. Over-engineered for this project's scale; adds significant operational complexity.
- **Docker Swarm mode** — built-in service scaling and load balancing. Adds operational overhead; Fly.io handles this natively for cloud deployments.

## Consequences

- Gunicorn workers auto-scale to available CPU without image rebuilds
- `WEB_CONCURRENCY` env var provides a simple operator override
- Fly.io deployments auto-scale across machines based on connection load
- Docker Compose deployments can scale gateway replicas (once blockers are resolved)
- The four multi-replica blockers are documented for future work
