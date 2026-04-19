"""Gunicorn configuration — auto-tunes workers to available CPU.

Default: min(2 * CPU_CORES + 1, 4).  Capped at 4 because each worker
loads Docling ML models (~250 MB RSS); 4 workers x 400 MB fits within
the 2 GB container memory limit.

Override at runtime:  WEB_CONCURRENCY=2 make deploy-up
"""

import multiprocessing
import os

# WEB_CONCURRENCY takes precedence (operator override).
# Otherwise auto-tune to CPU, capped at 4 for memory safety.
# Increase the cap only if you also raise deploy.resources.limits.memory.
_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
workers = int(_concurrency) if _concurrency else min(2 * multiprocessing.cpu_count() + 1, 4)

worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:7842"
