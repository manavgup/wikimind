#!/usr/bin/env bash
# start-combined.sh — combined-process startup for single-machine deployment.
#
# Runs three processes in one container:
#   1. redis-server  (localhost-only, persists to Fly volume)
#   2. arq worker    (background, supervised restart loop)
#   3. gunicorn      (foreground — container lifecycle follows gunicorn)
#
# Invoked via docker-entrypoint.sh, which handles root→wikimind user drop
# before exec'ing this script.  See docker/entrypoint.sh for details.
#
# Signal handling: SIGTERM/SIGINT are forwarded to gunicorn, the worker
# restart loop, and redis (SIGTERM triggers a final AOF flush on redis).
# Fly.io sends SIGTERM on auto-stop — redis persists before the container dies.
set -euo pipefail

TAG="[start-combined]"

# ---------------------------------------------------------------------------
# 1. Redis — localhost-only, AOF persistence to Fly volume
# ---------------------------------------------------------------------------
redis_data_dir="${WIKIMIND_DATA_DIR:-/home/wikimind/.wikimind}/redis"
mkdir -p "$redis_data_dir"

echo "$TAG starting redis-server (data dir: $redis_data_dir)"
redis-server \
    --bind 127.0.0.1 \
    --port 6379 \
    --maxmemory 128mb \
    --maxmemory-policy noeviction \
    --appendonly yes \
    --dir "$redis_data_dir" \
    &
redis_pid=$!

# Wait for redis to be ready (up to 15 s)
echo "$TAG waiting for redis to accept connections …"
redis_ready=0
for i in $(seq 1 15); do
    if redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q "PONG"; then
        redis_ready=1
        break
    fi
    sleep 1
done
if [ "$redis_ready" -eq 0 ]; then
    echo "$TAG ERROR: redis did not become ready within 15 s — aborting" >&2
    exit 1
fi
echo "$TAG redis is ready (attempt $i)"

# ---------------------------------------------------------------------------
# 2. ARQ worker — background supervised restart loop
#    The loop runs as a background job so gunicorn remains the foreground
#    process.  Non-zero exits from arq must NOT kill the container, so the
#    loop is in a subshell that does its own error handling (no set -e here).
# ---------------------------------------------------------------------------
worker_loop_pid=""

_run_worker_loop() {
    while true; do
        echo "$TAG starting arq worker"
        # Run arq; capture exit code without letting set -e abort the loop.
        set +e
        .venv/bin/arq wikimind.jobs.worker.WorkerSettings
        arq_exit=$?
        set -e
        echo "$TAG arq worker exited with code $arq_exit — restarting in 2 s"
        sleep 2
    done
}

_run_worker_loop &
worker_loop_pid=$!

# ---------------------------------------------------------------------------
# 3. Signal handling — forward TERM/INT to all children, then wait
# ---------------------------------------------------------------------------
_shutdown() {
    echo "$TAG received shutdown signal — stopping all processes"

    # Stop gunicorn gracefully (it handles its own graceful_timeout)
    if [ -n "${gunicorn_pid:-}" ] && kill -0 "$gunicorn_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to gunicorn (pid $gunicorn_pid)"
        kill -TERM "$gunicorn_pid" 2>/dev/null || true
    fi

    # Stop the worker restart loop
    if [ -n "$worker_loop_pid" ] && kill -0 "$worker_loop_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to worker loop (pid $worker_loop_pid)"
        kill -TERM "$worker_loop_pid" 2>/dev/null || true
    fi

    # Give redis SIGTERM so it flushes the AOF before dying
    if [ -n "$redis_pid" ] && kill -0 "$redis_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to redis (pid $redis_pid)"
        kill -TERM "$redis_pid" 2>/dev/null || true
        wait "$redis_pid" 2>/dev/null || true
    fi
}

trap '_shutdown' TERM INT

# ---------------------------------------------------------------------------
# 4. Gunicorn — foreground; container lifecycle follows its exit code
# ---------------------------------------------------------------------------
echo "$TAG starting gunicorn"
.venv/bin/gunicorn wikimind.main:app -c gunicorn.conf.py &
gunicorn_pid=$!

echo "$TAG gunicorn started (pid $gunicorn_pid)"

# Wait for gunicorn to exit; propagate its exit code
wait "$gunicorn_pid"
gunicorn_exit=$?
echo "$TAG gunicorn exited with code $gunicorn_exit — shutting down"

# Trigger cleanup in case gunicorn exited on its own (not via signal)
_shutdown

exit "$gunicorn_exit"
