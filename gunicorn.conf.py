"""Gunicorn configuration — auto-tunes workers to available CPU.

Default: min(2 * CPU_CORES + 1, 8).  Each worker is lightweight (~50MB RSS)
since ML models run in the docling-serve sidecar container.

Override at runtime:  WEB_CONCURRENCY=2 make deploy-up
"""

import multiprocessing
import os

# WEB_CONCURRENCY takes precedence (operator override).
# Otherwise auto-tune to CPU, capped at 8 — workers are lightweight now that
# PDF extraction is offloaded to docling-serve.
_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
workers = int(_concurrency) if _concurrency else min(2 * multiprocessing.cpu_count() + 1, 8)

worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:7842"

# Request timeout — PDF extraction offloaded to docling-serve sidecar,
# so no single request should block for more than 30s.
timeout = 30
graceful_timeout = 30

# Recycle workers periodically to prevent memory bloat.
max_requests = 1000
max_requests_jitter = 50
