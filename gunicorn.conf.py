"""Gunicorn configuration — auto-tunes workers to available CPU.

Default: min(2 * CPU_CORES + 1, 8).  Each worker is lightweight (~50MB RSS)
since ML models run in the docling-serve sidecar container.

Override at runtime:  WEB_CONCURRENCY=2 make deploy-up
"""

import multiprocessing
import os

# WEB_CONCURRENCY takes precedence (operator override).
# Otherwise auto-tune to CPU, capped at 4.  On small Fly.io machines (1 CPU,
# 1 GB) fewer workers avoids memory pressure and startup timeout cascades.
_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
workers = int(_concurrency) if _concurrency else min(2 * multiprocessing.cpu_count() + 1, 4)

worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:7842"

# Request timeout — must be long enough for DB init + migrations on cold
# start (~15s) plus headroom for slow first requests.  PDF extraction is
# offloaded to docling-serve sidecar, so steady-state requests are fast.
timeout = 120
graceful_timeout = 30

# Recycle workers periodically to prevent memory bloat.
max_requests = 1000
max_requests_jitter = 50
