#!/usr/bin/env bash
set -euo pipefail

# Fix volume ownership — Fly.io volumes may retain root ownership across deploys
if [ "$(id -u)" = "0" ]; then
    chown -R wikimind:wikimind "${WIKIMIND_DATA_DIR:-/home/wikimind/.wikimind}"
    exec gosu wikimind "$0" "$@"
fi

# Run Alembic migrations when using PostgreSQL.
# SQLite uses create_all() at startup — no Alembic needed.
# Check both WIKIMIND_DATABASE_URL (explicit) and DATABASE_URL (Fly.io/Railway auto-set).
_db_url="${WIKIMIND_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ "$_db_url" == postgres* ]]; then
    echo "Running Alembic migrations..."
    .venv/bin/python -m alembic upgrade head
    echo "Migrations complete."
fi

# Gunicorn crashes on empty WEB_CONCURRENCY (int("") fails at import time).
# Unset it so gunicorn falls through to gunicorn.conf.py auto-tuning.
if [[ -z "${WEB_CONCURRENCY:-}" ]]; then
    unset WEB_CONCURRENCY
fi

# Run from the venv when the command exists there (gunicorn, python, etc.),
# otherwise fall back to PATH (system commands like sh, bash, find).
# This avoids `uv run` re-syncing the editable install on every start.
if [[ -x ".venv/bin/$1" ]]; then
    exec .venv/bin/"$@"
else
    exec "$@"
fi
