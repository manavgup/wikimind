# WikiMind

[![Tests & Coverage](https://github.com/manavgup/wikimind/actions/workflows/test.yml/badge.svg)](https://github.com/manavgup/wikimind/actions/workflows/test.yml)
[![Lint & Static Analysis](https://github.com/manavgup/wikimind/actions/workflows/lint.yml/badge.svg)](https://github.com/manavgup/wikimind/actions/workflows/lint.yml)
[![Deploy](https://github.com/manavgup/wikimind/actions/workflows/deploy.yml/badge.svg)](https://github.com/manavgup/wikimind/actions/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> I feed it everything I read. It writes my wiki for me. When I ask questions, it cites its sources.

WikiMind is a personal LLM-powered knowledge OS. Feed it articles, PDFs, YouTube videos, or papers — it compiles them into a structured wiki and answers questions with full source attribution.

<p align="center">
  <img src="docs/images/wikimind-demo.gif" alt="WikiMind demo — ingest sources, compile wiki, ask questions" width="720">
</p>

## What it is

- **Not** a note-taking app — you never write
- **Not** a chatbot — it builds something persistent
- **Not** a RAG tool — the wiki is the product, not a retrieval layer

It is the synthesis layer that sits above everything you consume.

## How it works

```
Feed → Compile → Query → Answer files back → Wiki gets smarter → Repeat
```

| Feature | Description |
|---------|-------------|
| **Multi-source ingest** | URLs, PDFs, YouTube transcripts, plain text |
| **LLM compilation** | Articles compiled by Claude, GPT-4, Gemini, or Ollama |
| **Knowledge graph** | Auto-generated concepts, backlinks, and taxonomy |
| **Ask with citations** | Q&A against your wiki with source attribution |
| **Export** | PDF, LinkedIn draft, Marp slides |
| **Browser extension** | Chrome + Firefox clipper — save any page in one click |
| **Self-hosted** | Your data, your API keys, your models |

## Compare

| | WikiMind | Obsidian | Notion | ChatGPT |
|---|:---:|:---:|:---:|:---:|
| You write the content | | Yes | Yes | |
| LLM compiles for you | Yes | | | |
| Persistent wiki output | Yes | Yes | Yes | |
| Source attribution | Yes | | | |
| Knowledge graph | Yes | Yes | | |
| Self-hosted | Yes | | | |
| Multi-provider LLM | Yes | | | Yes |

## Read more

[**Building a Personal Knowledge OS with LLMs**](https://manavgup.github.io/shipai/blog/2026/04/21/building-wikimind-personal-knowledge-os/) — architecture deep-dive, design decisions, and lessons learned.

## Quick start

WikiMind needs Python 3.11+ and (for the React frontend) Node.js 20+.

```bash
# 1. Set up the dev environment
make venv
make install-dev
make check-env

# 2. Configure at least one LLM provider — copy .env.example and edit
cp .env.example .env
# Add: OPENAI_API_KEY=sk-... (or ANTHROPIC_API_KEY, GOOGLE_API_KEY)
# For OpenRouter/other OpenAI-compatible gateways, see .env.example.
# Providers auto-enable when their key is detected.

# 3. Start the local gateway (FastAPI on :7842)
make dev

# 4. (optional) Start the React UI in another terminal
cd apps/web
npm install
npm run dev
# Opens http://localhost:5173
```

### Authentication UI

When multi-user mode is enabled (`WIKIMIND_AUTH__ENABLED=true`), the frontend shows:

- **Login page** (`/login`) — Google and GitHub OAuth2 sign-in buttons
- **Protected routes** — unauthenticated users are redirected to `/login`
- **User menu** — avatar, name, and logout button in the sidebar

When auth is disabled (default), no login page is shown and all routes are accessible.

## Production deployment

### Docker Compose (self-hosted)

```bash
# Start the full stack: gateway + worker + Postgres + Redis
POSTGRES_PASSWORD=changeme make deploy-up

# Tail logs / check status / stop
make deploy-logs
make deploy-ps
make deploy-stop
```

Gunicorn workers auto-tune to available CPU cores (see `gunicorn.conf.py`).
Override with `WEB_CONCURRENCY`:

```bash
WEB_CONCURRENCY=4 POSTGRES_PASSWORD=changeme make deploy-up
```

### PDF Processing (docling-serve)

PDF extraction runs in a separate container ([docling-serve](https://github.com/docling-project/docling-serve)).
It starts automatically with `docker compose up` or `make dev-docker`.

To run without Docker (local dev):

```bash
# Pull and run docling-serve separately:
docker run -p 5001:5001 quay.io/docling-project/docling-serve-cpu:latest
```

Set `WIKIMIND_DOCLING_SERVE_URL=http://localhost:5001` in your `.env`.
Without docling-serve running, PDF ingestion falls back to basic text extraction (pymupdf).

### Fly.io (cloud)

```bash
fly deploy
fly secrets set ANTHROPIC_API_KEY=sk-...
```

Fly.io auto-scales machines based on connection count (see `fly.toml`).

#### Staging environment

CI deploys to a staging app (`wikimind-staging`) before production. Smoke tests
run against staging; production is only promoted when they pass. See
`.github/workflows/deploy.yml` for the full pipeline.

First-time staging setup:

```bash
fly apps create wikimind-staging
fly volumes create wikimind_staging_data --region ord --size 1 --app wikimind-staging
fly postgres attach wikimind-db --app wikimind-staging
fly secrets set --app wikimind-staging ANTHROPIC_API_KEY=... WIKIMIND_AUTH__JWT_SECRET_KEY=$(openssl rand -hex 32)
```

Manual deploy: `fly deploy --config fly.staging.toml --remote-only`

### PostgreSQL without Docker

For shared access across multiple devices without the full Docker stack:

```bash
# 1. Set the database URL in .env
echo 'WIKIMIND_DATABASE_URL=postgresql+asyncpg://localhost:5432/wikimind' >> .env

# 2. Run Alembic migrations (first time only, and after upgrades)
alembic upgrade head

# 3. Start the server
make dev
```

All features work identically on both backends. SQLite is recommended for
single-device development. PostgreSQL is required for cloud deployments where
multiple devices share the same database.

## Multi-User Mode

WikiMind supports optional multi-user mode with OAuth2 authentication (Google, GitHub).

### Enable Authentication

Set these in your `.env`:

```env
WIKIMIND_AUTH__ENABLED=true
WIKIMIND_AUTH__JWT_SECRET_KEY=your-random-secret-here
WIKIMIND_AUTH__GOOGLE_CLIENT_ID=...
WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET=...
# and/or GitHub credentials
```

When disabled (default), WikiMind runs in single-user mode with no login required.
Keep `WIKIMIND_AUTH__JWT_SECRET_KEY` set if users store API keys through the
Settings UI, because BYOK encryption derives from that secret.

## Architecture

```
wikimind/
├── src/wikimind/          # Python backend (FastAPI gateway)
│   ├── main.py            # App entry point
│   ├── config.py          # Pydantic BaseSettings
│   ├── models.py          # SQLModel tables + Pydantic schemas
│   ├── database.py        # Async SQLite session lifecycle
│   ├── api/routes/        # FastAPI route handlers (thin)
│   ├── services/          # Business logic (ingest, compiler, query, wiki)
│   ├── engine/            # LLM router, compiler, Q&A agent
│   ├── ingest/            # Source adapters (URL, PDF, text, YouTube)
│   ├── jobs/              # Background compilation worker
│   └── middleware/        # Correlation ID, logging, security headers
├── apps/web/              # React + Vite + TypeScript frontend
├── apps/web-extension/    # Chrome + Firefox browser extension (MV3)
├── tests/                 # pytest unit + integration tests
├── docs/                  # ADRs, OpenAPI schema, design specs
└── scripts/               # Operational scripts (test matrix, doc sync)
```

## Configuration

All configuration lives in `.env` (gitignored). See `.env.example` for the full list of options.

The most common case: just set ONE LLM API key and the provider will auto-enable.
If you save API keys through the Settings UI instead of environment variables,
also set `WIKIMIND_AUTH__JWT_SECRET_KEY`; it is used to encrypt stored keys.

```bash
# In .env:
OPENAI_API_KEY=sk-...
WIKIMIND_AUTH__JWT_SECRET_KEY=<random-hex-or-token>
```

For more advanced configuration (model selection, fallback chain, monthly budget), see `.env.example`.

OpenAI-compatible gateways such as OpenRouter can be used through a separate configurable provider:

```bash
OPENAI_COMPATIBLE_API_KEY=sk-or-...
WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL=https://openrouter.ai/api/v1
WIKIMIND_LLM__OPENAI_COMPATIBLE__MODEL=openai/gpt-4o-mini
WIKIMIND_LLM__DEFAULT_PROVIDER=openai_compatible
```

## Tech stack

| Layer | Technology |
|---|---|
| Backend gateway | Python 3.11+ / FastAPI |
| Job queue | ARQ + asyncio (in-process for dev, ARQ + Redis for prod) |
| Database | SQLite via SQLModel + aiosqlite |
| LLM providers | Anthropic Claude, OpenAI GPT, OpenAI-compatible endpoints, Google Gemini, Ollama |
| PDF extraction | [docling-serve](https://github.com/docling-project/docling-serve) sidecar; pymupdf (fitz) fallback |
| Document ingest | trafilatura (URLs), youtube-transcript-api (YouTube) |
| Logging | structlog (JSON in prod, console in dev) |
| Type checking | mypy + basedpyright |
| Linting | ruff (with pylint and pydocstyle rules) |
| Frontend | React 18 + TypeScript + Vite + TanStack Query + Zustand + Tailwind CSS |
| Browser extension | Preact + TypeScript + Vite, Manifest V3 (Chrome + Firefox) |
| Testing | pytest + pytest-asyncio + httpx |

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
| `make dev` | Run fast-reload dev server on :7842 (uvicorn) |
| `make dev-token` | Generate a JWT API token for dev/testing (uses .env secret) |
| `make serve` | Run production server on :7842 (gunicorn) |
| `make pg-up` | Start local Postgres (docker-compose.dev.yml, port 5433) |
| `make pg-down` | Stop local Postgres |
| `make dev-postgres` | Run dev server against local Postgres (make pg-up first) |
| `make test-postgres` | Run tests against local Postgres (make pg-up first) |
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
| `make deptry` | Detect unused/missing/transitive dependencies |
| `make dead-code` | Alias for vulture — find unused functions, imports, variables |
| `make doc-coverage` | Measure docstring coverage (fails if below fail-under threshold) |
| `make security` | Run security and dead-code checks |
| `make update-secrets-baseline` | Update detect-secrets baseline (keeps line numbers in sync) |
| `make verify` | Run the required full-verify suite (Python + desktop + extension; excludes frontend/doc-sync) |
| `make coverage-ci` | Run backend CI tests with terminal, HTML, and XML coverage outputs |
| `make coverage-check` | Run non-E2E tests with coverage (policy is configured in pyproject.toml) |
| `make security-check` | Run the scheduled CI security scan set |
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
| `make coverage` | Run tests with coverage report and HTML output |
| `make test-matrix` | Show how to run the LLM × document type benchmark |

### 📚 DOCUMENTATION

| Target | Description |
|--------|-------------|
| `make export-openapi` | Regenerate docs/openapi.yaml from the FastAPI app |
| `make check-openapi` | Verify docs/openapi.yaml matches the FastAPI app |
| `make regenerate-adr-index` | Regenerate docs/adr/README.md from ADR files |
| `make check-adr-index` | Verify docs/adr/README.md is in sync with ADR files |
| `make regenerate-readme-targets` | Regenerate README make-targets section from Makefile |
| `make check-readme-targets` | Verify README make-targets section is in sync with Makefile |
| `make regenerate-docs` | Regenerate all auto-generated docs |
| `make check-docs` | Verify all auto-generated docs are in sync |
| `make check-doc-sync` | Run the co-change rule engine against the staged diff |
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

- **[Architecture Decision Records](docs/adr/README.md)** — why the project is designed the way it is
- **[Vision](docs/VISION.md)** — product spec and product vision
- **[Architecture](docs/ARCHITECTURE.md)** — system design overview
- **[Roadmap](docs/ROADMAP.md)** — phase-by-phase build plan
- **[OpenAPI schema](docs/openapi.yaml)** — auto-generated from the FastAPI app

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and coding standards.

Quality gates: `make verify` runs the full suite (ruff, format check, mypy, basedpyright, pydocstyle, pytest). Pre-commit hooks (`make pre-commit`) enforce the same checks before each commit.

## Status

**Phase 1 (Working Core)** — Done
- [x] Backend pipeline: ingest → compile → query → file-back
- [x] React UI: Inbox + Wiki Explorer
- [x] LLM provider abstraction with auto-enable
- [x] Multi-format ingest (URL, PDF, text, YouTube)
- [x] Source provenance and citation chains

**Phase 2 (Query Loop)** — In progress
- [x] Conversational Q&A agent with thread file-back (ADR-011)
- [x] React UI: Ask view with conversation threads
- [ ] Semantic search (ChromaDB + embeddings)
- [ ] Knowledge graph view
- [ ] Wiki linter and health dashboard

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

## License

MIT
