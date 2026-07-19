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
# PID placeholders — must exist before the trap fires (set -u safety).
# ---------------------------------------------------------------------------
redis_pid=""
worker_loop_pid=""
gunicorn_pid=""

# ---------------------------------------------------------------------------
# Shutdown — idempotent; safe to call from both trap and normal flow.
# Ordering: stop writers (gunicorn + worker) first, then redis dies last.
# ---------------------------------------------------------------------------
_shutting_down=0
_shutdown() {
    # Idempotency guard — handles EXIT trap + double-SIGTERM mid-shutdown.
    if [ "$_shutting_down" -eq 1 ]; then
        return
    fi
    _shutting_down=1

    echo "$TAG received shutdown signal — stopping all processes"

    # Stop gunicorn gracefully (it handles its own graceful_timeout)
    if [ -n "${gunicorn_pid}" ] && kill -0 "$gunicorn_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to gunicorn (pid $gunicorn_pid)"
        kill -TERM "$gunicorn_pid" 2>/dev/null || true
    fi

    # Stop the worker restart loop
    if [ -n "${worker_loop_pid}" ] && kill -0 "$worker_loop_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to worker loop (pid $worker_loop_pid)"
        kill -TERM "$worker_loop_pid" 2>/dev/null || true
    fi

    # Wait for both writers to finish before touching redis
    wait "${gunicorn_pid}" 2>/dev/null || true
    wait "${worker_loop_pid}" 2>/dev/null || true

    # Give redis SIGTERM so it flushes the AOF before dying — redis dies last
    if [ -n "${redis_pid}" ] && kill -0 "$redis_pid" 2>/dev/null; then
        echo "$TAG sending SIGTERM to redis (pid $redis_pid)"
        kill -TERM "$redis_pid" 2>/dev/null || true
        wait "$redis_pid" 2>/dev/null || true
    fi
}

# Register trap BEFORE starting any child process so that Fly.io SIGTERM
# during startup is handled rather than ignored by bash-as-PID-1.
# EXIT trap provides belt-and-braces coverage for any unexpected set -e exit.
# exit 143 (128+TERM) prevents the script resuming after cleanup.
trap '_shutdown; exit 143' TERM INT
trap '_shutdown' EXIT

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
    --save "" \
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
#    loop handles its own error recovery and traps SIGTERM to forward it to
#    the running arq process (killing the subshell alone does not kill arq).
#    The sleep backoff uses "sleep & wait" so a SIGTERM during the sleep is
#    still handled promptly.
# ---------------------------------------------------------------------------
_run_worker_loop() {
    trap 'kill -TERM "$arq_pid" 2>/dev/null; wait "$arq_pid" 2>/dev/null; exit 0' TERM
    while true; do
        echo "$TAG starting arq worker"
        .venv/bin/arq wikimind.jobs.worker.WorkerSettings & arq_pid=$!
        wait "$arq_pid" || true
        echo "$TAG arq exited — restarting in 2 s"
        sleep 2 & wait $! || true
    done
}

_run_worker_loop &
worker_loop_pid=$!

# ---------------------------------------------------------------------------
# 3. Gunicorn — foreground; container lifecycle follows its exit code
# ---------------------------------------------------------------------------
echo "$TAG starting gunicorn"
.venv/bin/gunicorn wikimind.main:app -c gunicorn.conf.py &
gunicorn_pid=$!

echo "$TAG gunicorn started (pid $gunicorn_pid)"

# Wait for gunicorn to exit; capture exit code without letting set -e abort
# here and skip _shutdown (which redis needs for its AOF flush).
gunicorn_exit=0
wait "$gunicorn_pid" || gunicorn_exit=$?
echo "$TAG gunicorn exited with code $gunicorn_exit — shutting down"

# Trigger cleanup in case gunicorn exited on its own (not via signal).
# _shutdown is idempotent — safe to call even if the trap already ran.
_shutdown

exit "$gunicorn_exit"
