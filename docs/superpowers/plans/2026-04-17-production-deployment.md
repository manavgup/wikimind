# Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the full WikiMind stack (gateway + frontend + Postgres + Redis + worker) for production deployment, closing Epic 5.

**Architecture:** The existing Dockerfile gets a frontend build stage. The prod image serves the React frontend via FastAPI's `StaticFiles` — no separate nginx container. A `docker-compose.prod.yml` orchestrates gateway, Postgres 16, Redis 7, and an ARQ worker, all sharing a persistent data volume. Alembic migrations run automatically on startup via an entrypoint script. Deployment docs cover Fly.io and generic Docker.

**Tech Stack:** Docker multi-stage builds, PostgreSQL 16, Redis 7, Alembic, Gunicorn, FastAPI StaticFiles

**Closes:** #199 (production docker-compose), Epic 5 (Sync + Multi-provider)

**Prerequisites on main (already merged):**
- FileStorage abstraction (PR 1/3, #170)
- PostgreSQL compatibility (PR 2/3, #174) — `database.py`, `db_compat.py`, `alembic/`
- Multi-provider LLM + Settings UI + Cost tracking

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `docker/entrypoint.sh` | Run alembic + start gunicorn |
| Modify | `Dockerfile` | Add frontend build stage, copy dist + alembic to prod |
| Modify | `src/wikimind/main.py` | Mount frontend dist via StaticFiles (conditional) |
| Create | `docker-compose.prod.yml` | Full production stack |
| Modify | `Makefile` | `deploy-local`, `deploy-stop`, `deploy-logs` targets |
| Modify | `.env.example` | Document production config (DATABASE_URL, REDIS_URL) |
| Create | `fly.toml` | Fly.io deployment config |
| Modify | `README.md` | Deployment section |

---

### Task 1: Docker Entrypoint Script

**Files:**
- Create: `docker/entrypoint.sh`

- [ ] **Step 1: Create the entrypoint script**

```bash
#!/bin/sh
set -e

# Run Alembic migrations if using Postgres.
# SQLite uses create_all() on startup — no Alembic needed.
if echo "$WIKIMIND_DATABASE_URL" | grep -q "^postgresql"; then
  echo "Running Alembic migrations..."
  python -m alembic upgrade head
  echo "Migrations complete."
fi

exec "$@"
```

Write to `docker/entrypoint.sh` and make executable.

- [ ] **Step 2: Verify the script is executable**

Run: `ls -la docker/entrypoint.sh`
Expected: `-rwxr-xr-x` permissions

- [ ] **Step 3: Commit**

```bash
git add docker/entrypoint.sh
git commit -m "feat: add Docker entrypoint with auto-migration for Postgres"
```

---

### Task 2: Update Dockerfile for Production

**Files:**
- Modify: `Dockerfile`

The Dockerfile needs two additions:
1. A `frontend` stage that builds the React app with Node.js
2. The `prod` stage copies the frontend build + alembic files and uses the entrypoint

- [ ] **Step 1: Add the frontend build stage**

Insert between the `base` and `dev` stages in `Dockerfile`:

```dockerfile
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/web/ ./
RUN npm run build
```

- [ ] **Step 2: Update the prod stage**

Modify the `prod` stage to:
- Copy alembic config and migrations
- Copy the frontend build from the `frontend` stage
- Use the entrypoint script

Replace the existing prod stage (from `FROM base AS prod` to end of file) with:

```dockerfile
# ---------------------------------------------------------------------------
FROM base AS prod

ARG TORCH_INDEX
COPY pyproject.toml README.md ./
COPY src ./src
# Same CVE upgrade as the dev stage — see comment above.
# Install with [pdf] extra for structured PDF extraction via docling.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url ${TORCH_INDEX} ".[pdf]"

# Alembic migrations for Postgres deployments
COPY alembic.ini ./
COPY alembic ./alembic

# Built frontend — served by FastAPI StaticFiles at /
COPY --from=frontend /app/dist ./frontend

# Entrypoint: run alembic migrations (Postgres only), then exec CMD
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Run as a non-root user in production.
RUN useradd --create-home --uid 1000 wikimind \
    && mkdir -p /home/wikimind/.wikimind \
    && chown -R wikimind:wikimind /home/wikimind /app
USER wikimind

ENV WIKIMIND_DATA_DIR=/home/wikimind/.wikimind \
    WIKIMIND_SERVER__HOST=0.0.0.0

EXPOSE 7842

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7842/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "wikimind.main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:7842"]
```

- [ ] **Step 3: Verify Dockerfile builds**

Run: `docker build --target prod -t wikimind-prod:test . 2>&1 | tail -10`
Expected: Successfully built image

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: add frontend build stage and entrypoint to Dockerfile prod target"
```

---

### Task 3: Serve Frontend from FastAPI

**Files:**
- Modify: `src/wikimind/main.py`
- Test: verify with `make test`

The frontend dist is at `/app/frontend/` inside the prod container. Mount it via StaticFiles only when it exists (so dev mode with `--reload` is unaffected).

- [ ] **Step 1: Add conditional frontend mount to main.py**

After the existing `/images` mount and router includes, add:

```python
# Serve the built frontend in production.
# The dist is copied into the Docker prod image at /app/frontend/.
# In dev mode this directory does not exist — Vite serves the frontend.
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
```

The `html=True` parameter enables SPA fallback: requests for paths like `/settings` that don't match a static file return `index.html`, allowing React Router to handle client-side routing.

**Important:** This mount MUST be the last `app.mount()` call because `"/"` is a catch-all. All API routers are registered with `include_router` (which uses `APIRouter` prefix matching, not `mount`), so they take priority.

- [ ] **Step 2: Run tests to verify no regression**

Run: `make test`
Expected: All tests pass — the frontend dir doesn't exist locally, so the mount is skipped.

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/main.py
git commit -m "feat: serve built frontend via StaticFiles in production"
```

---

### Task 4: Production Docker Compose

**Files:**
- Create: `docker-compose.prod.yml`

- [ ] **Step 1: Create docker-compose.prod.yml**

```yaml
# Production stack for WikiMind.
#
# Services:
#   gateway  — FastAPI app (gunicorn) serving both API and frontend
#   worker   — ARQ background job worker (compilation, sweep)
#   postgres — PostgreSQL 16 for metadata
#   redis    — Broker/result store for ARQ background jobs
#
# Bring up:   make deploy-local
# Tear down:  make deploy-stop
# Logs:       make deploy-logs

services:
  gateway:
    build:
      context: .
      dockerfile: Dockerfile
      target: prod
    image: wikimind-prod:latest
    container_name: wikimind-gateway-prod
    environment:
      WIKIMIND_DATABASE_URL: postgresql+asyncpg://wikimind:${POSTGRES_PASSWORD:-wikimind}@postgres:5432/wikimind
      WIKIMIND_REDIS_URL: redis://redis:6379/0
      WIKIMIND_DATA_DIR: /home/wikimind/.wikimind
      WIKIMIND_SERVER__HOST: "0.0.0.0"
      WIKIMIND_SERVER__PORT: "7842"
    env_file:
      - path: .env
        required: false
    ports:
      - "${WIKIMIND_PORT:-7842}:7842"
    volumes:
      - wikimind-data:/home/wikimind/.wikimind
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: prod
    image: wikimind-prod:latest
    container_name: wikimind-worker-prod
    command: ["python", "-m", "arq", "wikimind.jobs.worker.WorkerSettings"]
    environment:
      WIKIMIND_DATABASE_URL: postgresql+asyncpg://wikimind:${POSTGRES_PASSWORD:-wikimind}@postgres:5432/wikimind
      WIKIMIND_REDIS_URL: redis://redis:6379/0
      WIKIMIND_DATA_DIR: /home/wikimind/.wikimind
    env_file:
      - path: .env
        required: false
    volumes:
      - wikimind-data:/home/wikimind/.wikimind
    depends_on:
      gateway:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: wikimind-postgres-prod
    environment:
      POSTGRES_DB: wikimind
      POSTGRES_USER: wikimind
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-wikimind}
    volumes:
      - wikimind-pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wikimind"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: wikimind-redis-prod
    volumes:
      - wikimind-redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

volumes:
  wikimind-data:
  wikimind-pgdata:
  wikimind-redis:
```

- [ ] **Step 2: Verify compose config is valid**

Run: `docker compose -f docker-compose.prod.yml config --quiet`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat: add production docker-compose with Postgres + Redis"
```

---

### Task 5: Makefile Deploy Targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add deploy targets**

Add a new section to the Makefile after the Docker section:

```makefile
##@ 🚀 DEPLOY

.PHONY: deploy-local
deploy-local: ## Build and run the full production stack locally
	docker compose -f docker-compose.prod.yml up -d --build

.PHONY: deploy-stop
deploy-stop: ## Stop the production stack
	docker compose -f docker-compose.prod.yml down

.PHONY: deploy-logs
deploy-logs: ## Tail logs from the production stack
	docker compose -f docker-compose.prod.yml logs -f
```

- [ ] **Step 2: Verify targets appear in help**

Run: `make help | grep deploy`
Expected: Three deploy targets listed

- [ ] **Step 3: Run auto-generated docs**

Run: `make regenerate-docs`
Expected: README make-targets section updated

- [ ] **Step 4: Commit**

```bash
git add Makefile README.md
git commit -m "feat: add make deploy-local/stop/logs targets"
```

---

### Task 6: Fly.io Configuration

**Files:**
- Create: `fly.toml`

Fly.io is the simplest cloud deployment for WikiMind: one command deploys the entire stack. Fly provides managed Postgres and Redis as add-ons.

- [ ] **Step 1: Create fly.toml**

```toml
# Fly.io deployment configuration for WikiMind.
#
# Prerequisites:
#   fly auth login
#   fly apps create wikimind
#   fly postgres create --name wikimind-db
#   fly postgres attach wikimind-db
#   fly redis create --name wikimind-redis
#
# Deploy:
#   fly deploy
#
# Set LLM API key:
#   fly secrets set ANTHROPIC_API_KEY=sk-ant-...

app = "wikimind"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"
  [build.args]
    TORCH_INDEX = "https://download.pytorch.org/whl/cpu"

[env]
  WIKIMIND_SERVER__HOST = "0.0.0.0"
  WIKIMIND_SERVER__PORT = "7842"

[http_service]
  internal_port = 7842
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [http_service.concurrency]
    type = "requests"
    hard_limit = 100
    soft_limit = 80

[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 1

[checks]
  [checks.health]
    type = "http"
    port = 7842
    path = "/health"
    interval = "30s"
    timeout = "5s"
```

- [ ] **Step 2: Commit**

```bash
git add fly.toml
git commit -m "feat: add Fly.io deployment config"
```

---

### Task 7: Update .env.example and Docs

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add production config section to .env.example**

Add after the existing Database section:

```env
# ----------------------------------------------------------------------------
# Production Database (required for Postgres deployments)
# ----------------------------------------------------------------------------
# Override the default SQLite with a PostgreSQL URL for production.
# See ADR-021 for design. Run `alembic upgrade head` to create tables.
# WIKIMIND_DATABASE_URL=postgresql+asyncpg://wikimind:PASSWORD@localhost:5432/wikimind  # pragma: allowlist secret
```

- [ ] **Step 2: Add deployment section to README.md**

Add a "Deployment" section with:
- `make deploy-local` quick start
- Fly.io instructions (3 commands: create app, attach postgres, deploy)
- Environment variables reference table

- [ ] **Step 3: Run auto-generated docs**

Run: `make regenerate-docs && make check-docs`
Expected: All docs in sync

- [ ] **Step 4: Commit**

```bash
git add .env.example README.md docs/
git commit -m "docs: add production deployment guide and config documentation"
```

---

### Task 8: Smoke Test the Production Stack

- [ ] **Step 1: Build and start the production stack**

Run: `make deploy-local`
Expected: All 4 containers start (gateway, worker, postgres, redis)

- [ ] **Step 2: Wait for health check**

Run: `curl -sf http://localhost:7842/health`
Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 3: Verify frontend is served**

Run: `curl -sf http://localhost:7842/ | head -5`
Expected: HTML page with React root div

- [ ] **Step 4: Test ingest + compile cycle**

```bash
curl -sf -X POST http://localhost:7842/ingest/text \
  -H "Content-Type: application/json" \
  -d '{"content":"Test article for production deployment verification.","title":"Deploy Test"}'
```

Expected: Source created, compilation triggers

- [ ] **Step 5: Tear down**

Run: `make deploy-stop`
Expected: All containers stopped

- [ ] **Step 6: Run make verify**

Run: `make verify`
Expected: All quality checks pass

---

### Task 9: Epic 5 Cleanup

- [ ] **Step 1: Close PR #171 (R2 storage backend)**

```bash
gh pr close 171 --comment "Closing in favor of the simpler production deployment approach (#199). R2 storage can be revisited when sync is implemented."
```

- [ ] **Step 2: Close issue #199**

The PR for this plan will reference and close #199.

- [ ] **Step 3: Update epic #5 body**

Update the checklist to reflect reality:
- [x] Multi-provider LLM (Anthropic, OpenAI, Google, Ollama)
- [x] Settings UI with cost tracking
- [x] Production deployment with Postgres
- Deferred: #74 (offline-first sync), #28 (cloud sync service)

```bash
gh issue comment 5 --body "Epic 5 substantially complete:
- ✅ Multi-provider LLM support (Anthropic, OpenAI, Google, Ollama)
- ✅ Settings UI with provider config, cost dashboard, budget warnings
- ✅ Cost tracking per provider per month
- ✅ Production deployment: docker-compose.prod.yml with Postgres + Redis
- ✅ Fly.io deployment config
- ⏸️ Deferred to future epic: #74 (offline-first sync engine), #28 (cloud sync service)

Multi-device access works via shared Postgres deployment — no sync protocol needed for the current use case."
```

- [ ] **Step 4: Create follow-up issue for sync (optional)**

If you want to track sync separately from Epic 5:
```bash
gh issue create --title "[EPIC]: Offline-first sync engine" --body "Extracted from Epic 5. See #74 and #28 for specs." --label "epic"
```
