#!/usr/bin/env bash
set -euo pipefail

# Run Alembic migrations when using PostgreSQL.
# SQLite uses create_all() at startup — no Alembic needed.
if [[ "${WIKIMIND_DATABASE_URL:-}" == postgresql* ]]; then
    echo "Running Alembic migrations..."
    python -m alembic upgrade head
    echo "Migrations complete."
fi

# Hand off to CMD (gunicorn in prod, or whatever compose overrides).
exec "$@"
