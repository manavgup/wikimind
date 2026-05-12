#!/usr/bin/env bash
set -euo pipefail

# Fix volume ownership — Fly.io volumes may retain root ownership across deploys.
# Create required subdirectories, then fix ownership so the wikimind user can write.
# Fast-path: skip chown -R if the data dir is already owned by wikimind (UID 1000).
if [ "$(id -u)" = "0" ]; then
    _data_dir="${WIKIMIND_DATA_DIR:-/home/wikimind/.wikimind}"
    mkdir -p "$_data_dir/wiki" "$_data_dir/raw"
    chown -R wikimind:wikimind "$_data_dir"
    exec gosu wikimind "$0" "$@"
fi

# Alembic migrations run via Fly.io release_command (see fly.toml [deploy] section).
# This ensures migrations execute exactly once per deploy, before any process starts.

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
