#!/usr/bin/env bash
set -euo pipefail

# Run Alembic migrations when using PostgreSQL.
# SQLite uses create_all() at startup — no Alembic needed.
# Check both WIKIMIND_DATABASE_URL (explicit) and DATABASE_URL (Fly.io/Railway auto-set).
_db_url="${WIKIMIND_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ "$_db_url" == postgres* ]]; then
    echo "Running Alembic migrations..."
    uv run python -m alembic upgrade head
    echo "Migrations complete."
fi

# Gunicorn crashes on empty WEB_CONCURRENCY (int("") fails at import time).
# Unset it so gunicorn falls through to gunicorn.conf.py auto-tuning.
if [[ -z "${WEB_CONCURRENCY:-}" ]]; then
    unset WEB_CONCURRENCY
fi

# Hand off to CMD (gunicorn in prod, or whatever compose overrides).
exec uv run "$@"
