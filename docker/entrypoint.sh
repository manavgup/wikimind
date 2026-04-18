#!/usr/bin/env bash
set -euo pipefail

# Run Alembic migrations when using PostgreSQL.
# SQLite uses create_all() at startup — no Alembic needed.
if [[ "${WIKIMIND_DATABASE_URL:-}" == postgresql* ]]; then
    echo "Running Alembic migrations..."
    python -m alembic upgrade head
    echo "Migrations complete."
fi

# Gunicorn crashes on empty WEB_CONCURRENCY (int("") fails at import time).
# Unset it so gunicorn falls through to gunicorn.conf.py auto-tuning.
if [[ -z "${WEB_CONCURRENCY:-}" ]]; then
    unset WEB_CONCURRENCY
fi

# Hand off to CMD (gunicorn in prod, or whatever compose overrides).
exec "$@"
