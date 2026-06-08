# WikiMind

[![Full Verify](https://github.com/manavgup/wikimind/actions/workflows/full-verify.yml/badge.svg)](https://github.com/manavgup/wikimind/actions/workflows/full-verify.yml)
[![Deploy](https://github.com/manavgup/wikimind/actions/workflows/deploy.yml/badge.svg)](https://github.com/manavgup/wikimind/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-manavgup.github.io%2Fwikimind-blue)](https://manavgup.github.io/wikimind/)

> You never write the wiki. You **feed** it.

WikiMind is a personal LLM-powered knowledge OS. Feed it articles, papers, PDFs, or YouTube links -- it compiles them into a structured wiki with claims, concepts, and backlinks. Ask questions and get answers with source citations. The system detects contradictions, knowledge gaps, and staleness automatically.

<p align="center">
  <img src="docs/images/wikimind-demo.gif" alt="WikiMind — feed sources, compile wiki articles, ask questions, synthesize across papers" width="720">
</p>

<p align="center">
  <a href="https://manavgup.github.io/wikimind/">Documentation</a> &bull;
  <a href="https://manavgup.github.io/wikimind/evidence/release-0.1.0/">Feature Evidence</a> &bull;
  <a href="https://wikimind.fly.dev">Live Demo</a>
</p>

## Key features

| | Feature | What it does |
|---|---|---|
| **Feed** | Multi-source ingest | URLs, PDFs (with figure extraction), YouTube, plain text, RSS feeds |
| **Compile** | LLM compilation | Articles with key claims, confidence scores, and source citations |
| **Link** | Knowledge graph | Auto-extracted concepts, bidirectional backlinks, typed relationships |
| **Ask** | Q&A with citations | RAG-powered answers citing specific articles. Conversation threading. |
| **Synthesize** | Cross-cutting analysis | Comparative, chronological, thematic, and gap analysis across articles |
| **Lint** | Quality assurance | Detect contradictions, orphans, stale content. LLM-powered checks. |
| **Export** | Share & download | Markdown, JSON, PDF, LinkedIn drafts, Obsidian. Public share links with expiry. |
| **MCP** | AI agent integration | 13 tools, 3 resources, 4 prompts. Claude Desktop & Cursor access via stdio or HTTP. |
| **Secure** | Multi-user auth | OAuth (GitHub, Google), magic links, API keys, rate limiting, data isolation |

## Architecture

<p align="center">
  <img src="docs/evidence/release-0.1.0/architecture.svg" alt="WikiMind Architecture" width="900">
</p>

## Quick start

```bash
# Clone and install
git clone https://github.com/manavgup/wikimind.git
cd wikimind
make install-dev

# Configure one LLM provider
cp .env.example .env
# Edit .env: add OPENAI_API_KEY=sk-... (or ANTHROPIC_API_KEY, GOOGLE_API_KEY)

# Start the full stack (API + worker + Redis)
make dev

# Or just the API server (no Docker needed)
make dev-api
```

The frontend is built into the API server. Open **http://localhost:7842** after starting.

### Local development notes

- **Python version**: WikiMind requires Python 3.11+. If your system `python3` is older, create the venv with a managed runtime first:
  ```bash
  uv venv --python 3.12 .venv
  make install-dev
  ```
- **Frontend in a source checkout**: `make dev-api` serves the API. For UI development, either run Vite separately with `make frontend-dev`, or build the frontend and expose it to the API:
  ```bash
  make frontend-build
  ln -s apps/web/dist static
  ```
- **Saving API keys in the UI**: user-provided LLM keys are encrypted at rest. Set a local JWT secret before using Settings -> API Keys:
  ```bash
  WIKIMIND_AUTH__JWT_SECRET_KEY=$(openssl rand -hex 32)
  ```
- **Docling sidecar**: PDF ingestion falls back to pymupdf when Docling is unavailable. To test structured Docling extraction while running the API on the host:
  ```bash
  docker run -d --name wikimind-docling -p 5001:5001 --restart unless-stopped \
    quay.io/docling-project/docling-serve-cpu:latest
  ```
  New PDF ingests will use Docling once `/api/admin/docling-status` reports connected. Existing sources are not re-extracted automatically; delete and re-ingest a PDF to compare.
- **LLM tracing**: cost/latency traces are opt-in. To also store the exact prompt and completion text shown in Admin -> Traces:
  ```bash
  WIKIMIND_LLM__TRACE_ENABLED=true
  WIKIMIND_LLM__TRACE_STORE_CONTENT=true
  ```
  This stores source text, prompts, and model responses in the local database.

## Production deployment

### Docker Compose (self-hosted)

```bash
POSTGRES_PASSWORD=changeme make deploy-up
```

### Fly.io (cloud)

```bash
fly deploy
fly secrets set OPENAI_API_KEY=sk-...
```

CI deploys to staging first, runs smoke tests, then promotes to production. See `.github/workflows/deploy.yml`.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI / 138 API endpoints |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Database | PostgreSQL (SQLModel ORM, Alembic migrations) |
| Job queue | ARQ + Redis (in-process asyncio for dev) |
| LLM providers | Anthropic Claude, OpenAI GPT, Google Gemini, Ollama, OpenAI-compatible |
| PDF extraction | [docling-serve](https://github.com/docling-project/docling-serve) sidecar + pymupdf fallback |
| Real-time | WebSocket (compilation progress), SSE (streaming Q&A) |
| MCP server | stdio + HTTP transports, OAuth 2.1, JWT auth |
| Browser extension | Chrome + Firefox (Manifest V3) |
| Deployment | Docker + Fly.io (staging + production) |
| CI/CD | GitHub Actions (16 workflows) |
| Testing | pytest (1700+ tests), Playwright e2e |

## Configuration

All configuration lives in `.env`. The most common case: set one LLM API key.

```bash
# Minimal .env
OPENAI_API_KEY=sk-...

# Multi-user mode
WIKIMIND_AUTH__ENABLED=true
WIKIMIND_AUTH__JWT_SECRET_KEY=$(openssl rand -hex 32)
WIKIMIND_AUTH__GOOGLE_CLIENT_ID=...
WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET=...
```

Providers auto-enable when their API key is detected. See `.env.example` for all options.

## Make targets

<!-- BEGIN make-targets -->
<!-- (auto-generated by scripts/regenerate_readme_targets.py) -->

### General

| Target | Description |
|--------|-------------|
| `make help` | Show this help |

### 🌱 VIRTUAL ENVIRONMENT & INSTALLATION

| Target | Description |
|--------|-------------|
| `make venv` | Create Python virtual environment |
| `make install` | Install production dependencies (pinned by uv.lock) |
| `make install-dev` | Install all dev/test/lint dependencies (pinned by uv.lock) |
| `make setup-git-mergedrivers` | Configure custom git merge drivers (secrets baseline) |
| `make check-venv` | Verify the venv editable install points at this checkout's src/ |
| `make repair-venv` | Reinstall the editable package so it points at this checkout |
| `make check-env` | Verify Python version, venv hygiene, and required tools |

### ▶️  SERVE

| Target | Description |
|--------|-------------|
| `make dev` | Start full local stack: API server + ARQ worker + Redis (via honcho) |
| `make dev-api` | Run only the fast-reload API server on :7842 (uvicorn) |
| `make dev-token` | Generate a JWT API token for dev/testing (uses .env secret) |
| `make serve` | Run production server on :7842 (gunicorn) |
| `make pg-up` | Start local Postgres (docker-compose.dev.yml, port 5433) |
| `make pg-down` | Stop local Postgres |
| `make dev-postgres` | Run dev server against local Postgres (make pg-up first) |
| `make test-postgres` | Run tests against local Postgres (make pg-up first) |
| `make dump-fly-migration-fixtures` | Dump Fly Postgres schema + migration-table data for local replay |
| `make worker` | Start ARQ background job worker |

### 🔍 QUALITY

| Target | Description |
|--------|-------------|
| `make pre-commit` | Run all pre-commit hooks + mypy + tests (matches CI) |
| `make lint` | Run ruff linter on src/ and tests/ (includes pylint + pydocstyle rules) |
| `make lint-fix` | Auto-fix lint issues where possible |
| `make format` | Format source code with ruff |
| `make format-check` | Check formatting without modifying files |
| `make typecheck` | Run mypy type checking |
| `make pyright` | Run basedpyright type checking (requires `npm install` at repo root) |
| `make pylint` | Run pylint static analysis (fails under 9.0/10) |
| `make docstyle` | Run pydocstyle docstring checks |
| `make bandit` | Run bandit security scanner |
| `make vulture` | Detect dead code (80% confidence) |
| `make check-layers` | Detect cross-layer import violations (architecture guardrail) |
| `make deptry` | Detect unused/missing/transitive dependencies |
| `make dead-code` | Alias for vulture |
| `make doc-coverage` | Measure docstring coverage (fails if below fail-under threshold) |
| `make update-secrets-baseline` | Update detect-secrets baseline (keeps line numbers in sync) |
| `make verify` | Run the required full-verify suite (Python + desktop + extension + doc-sync) |
| `make coverage-ci` | Run backend CI tests with terminal, HTML, and XML coverage outputs |
| `make coverage-check` | Run non-E2E tests with coverage (policy is configured in pyproject.toml) |

### 🌐 FRONTEND (React + Vite)

| Target | Description |
|--------|-------------|
| `make frontend-install` | Install frontend dependencies |
| `make frontend-dev` | Start Vite dev server on :5173 |
| `make frontend-build` | Build frontend production bundle |
| `make generate-types` | Generate TypeScript types from OpenAPI schema |
| `make frontend-verify` | Run all frontend quality checks |

### 🖥️  DESKTOP (Electron shell)

| Target | Description |
|--------|-------------|
| `make desktop-install` | Install Electron shell dependencies |
| `make desktop` | Launch the Electron shell for local dev (requires apps/web/dist + .venv) |
| `make desktop-verify` | Run desktop typecheck + build (auto-installs deps if needed) |

### 🌐 BROWSER EXTENSION

| Target | Description |
|--------|-------------|
| `make extension-install` | Install browser extension dependencies |
| `make extension-dev` | Build extension with watch mode for development |
| `make extension-build` | Build browser extension for production |
| `make extension-verify` | Run extension quality checks (typecheck + build) |
| `make extension-package` | Build extension and create submission-ready zip |

### 🐳 DOCKER

| Target | Description |
|--------|-------------|
| `make docker-build` | Build the dev image used by docker-compose |
| `make docker-up` | Start the dev stack in the background (uses cached image) |
| `make docker-up-build` | Rebuild the image and start the dev stack in the background |
| `make docker-logs` | Tail logs from all dev stack services |
| `make docker-down` | Stop and remove the dev stack |

### 🔄 PRODUCTION PARITY

| Target | Description |
|--------|-------------|
| `make parity-up` | Start production-parity stack (Postgres + PgBouncer + Redis) |
| `make parity-down` | Stop production-parity stack |
| `make parity-reset` | Stop production-parity stack and wipe all data |
| `make dev-parity` | Run dev server against production-parity stack (PgBouncer + Redis) |
| `make test-parity` | Run tests against production-parity stack |

### 🚀 DEPLOY

| Target | Description |
|--------|-------------|
| `make deploy-up` | Build and start the production stack |
| `make deploy-stop` | Stop the production stack |
| `make deploy-logs` | Tail logs from the production stack |
| `make deploy-ps` | Show production service status |
| `make fly-setup` | Set up Fly.io infrastructure (app, volume, Postgres, secrets) |

### 🧪 TESTING

| Target | Description |
|--------|-------------|
| `make test` | Run unit + integration tests with pytest |
| `make test-unit` | Run unit tests only |
| `make test-integration` | Run integration tests only |
| `make test-postgres-ci` | Run Postgres-only integration tests (requires WIKIMIND_TEST_POSTGRES_URL) |
| `make test-schema-migration` | Replay schema migration scenarios on local Postgres (use ARGS='fly-replay --schema-sql ...') |
| `make test-fly-schema-migration` | Dump current Fly Postgres schema/data and replay migration locally |
| `make test-auth-multiuser` | Run auth + multi-user isolation regression tests |
| `make coverage` | Run tests with coverage report and HTML output |
| `make test-matrix` | Show how to run the LLM × document type benchmark |

### 📚 DOCUMENTATION

| Target | Description |
|--------|-------------|
| `make export-openapi` | Regenerate docs/openapi.yaml from the FastAPI app |
| `make check-openapi` | Verify docs/openapi.yaml matches the FastAPI app |
| `make regenerate-adr-index` | Regenerate docs/adr/README.md from ADR files |
| `make check-adr-index` | Verify docs/adr/README.md is in sync |
| `make regenerate-readme-targets` | Regenerate README make-targets section from Makefile |
| `make check-readme-targets` | Verify README make-targets section is in sync with Makefile |
| `make regenerate-docs` | Regenerate all auto-generated docs |
| `make check-docs` | Verify all auto-generated docs are in sync |
| `make check-doc-sync` | Run the co-change rule engine against the staged diff |
| `make check-alembic` | Verify Alembic has a single migration head (no branches) |
| `make check-lockfile` | Verify uv.lock is in sync with pyproject.toml |
| `make backfill-images` | Extract images from existing PDFs that were ingested before image extraction |
| `make backfill-images-dry-run` | Show which PDFs would be processed (no changes) |

### 🗄️  DATABASE

| Target | Description |
|--------|-------------|
| `make db-reset` | Reset local SQLite database (recreated on next startup) |

### 🧹 CLEANUP

| Target | Description |
|--------|-------------|
| `make clean` | Remove caches, build artefacts, coverage files |
| `make clean-all` | Remove everything including .venv |

<!-- END make-targets -->

## Documentation

- **[Full documentation](https://manavgup.github.io/wikimind/)** -- deployment, architecture, configuration, API reference
- **[Feature evidence](https://manavgup.github.io/wikimind/evidence/release-0.1.0/)** -- screenshots, API test results, architecture diagram
- **[Architecture Decision Records](docs/adr/README.md)** -- why the project is designed the way it is
- **[OpenAPI schema](docs/openapi.yaml)** -- auto-generated from the FastAPI app
- **[Blog post](https://manavgup.github.io/shipai/blog/2026/04/21/building-wikimind-personal-knowledge-os/)** -- architecture deep-dive and lessons learned

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Quality gates: `make verify` runs the full suite (ruff, mypy, pytest, frontend build, doc-sync).

## License

MIT
