# Local Development

This guide covers running WikiMind locally for development.

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Node.js 20+** (for the React frontend and basedpyright)
- **uv** (Python package installer, used by the Makefile)

## Setup

```bash
# Clone the repository
git clone https://github.com/manavgup/wikimind.git
cd wikimind

# Create virtual environment
make venv

# Install all dev/test/lint dependencies
make install-dev

# Verify tools are present
make check-env
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

At minimum, set one LLM API key:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

See the [Settings reference](../configuration/settings.md) for all available options.

## Running the Backend

### Development server

```bash
make dev
```

This starts uvicorn with hot-reload on `http://localhost:7842`. Code changes in `src/` are picked up automatically.

### Production server (local)

```bash
make serve
```

Runs gunicorn with 2 workers.

### Background worker

If you want background compilation via ARQ (requires Redis):

```bash
# Start Redis (e.g., via Docker)
docker run -d -p 6379:6379 redis:7-alpine

# Set Redis URL
echo 'WIKIMIND_REDIS_URL=redis://localhost:6379/0' >> .env

# Start the worker
make worker
```

Without Redis, compilations run in-process (single-user dev mode) -- no separate worker needed.

## Running the Frontend

```bash
cd apps/web
npm install
npm run dev
```

The Vite dev server starts on `http://localhost:5173` and proxies API requests to the backend on `:7842`.

## PDF Processing

PDF extraction uses [docling-serve](https://github.com/docling-project/docling-serve) running as a sidecar. For local development:

```bash
docker run -p 5001:5001 quay.io/docling-project/docling-serve-cpu:latest
```

Set in your `.env`:

```bash
WIKIMIND_DOCLING_SERVE_URL=http://localhost:5001
```

Without docling-serve running, PDF ingestion falls back to basic text extraction via pymupdf (fitz). You get text but lose heading hierarchy, table structure, and OCR.

## Database

### SQLite (default)

By default, WikiMind uses SQLite stored at `~/.wikimind/db/wikimind.db`. No setup needed -- the database is created automatically on first startup.

Reset the database:

```bash
make db-reset
```

### PostgreSQL (optional)

For multi-device access or to match production:

```bash
# Set the database URL
echo 'WIKIMIND_DATABASE_URL=postgresql+asyncpg://localhost:5432/wikimind' >> .env

# Run Alembic migrations
alembic upgrade head

# Start the server
make dev
```

Or use the convenience target:

```bash
make dev-postgres
```

## Quality Checks

Run the full quality suite before pushing:

```bash
make verify
```

This runs: `lint` -> `format-check` -> `typecheck` -> `pyright` -> `docstyle` -> `coverage-check` -> `desktop-verify`

Individual checks:

```bash
make lint          # ruff linter
make format        # ruff formatter
make typecheck     # mypy
make pyright       # basedpyright (requires Node.js)
make test          # pytest
make coverage      # tests with coverage report
```

## Data Directory

All WikiMind data lives under `~/.wikimind/` by default:

```
~/.wikimind/
├── config/           # Non-sensitive settings
├── raw/              # Original source files (immutable)
│   ├── {uuid}.pdf
│   ├── {uuid}.html
│   └── {uuid}.txt
├── wiki/             # Compiled articles
│   ├── index.md      # Auto-maintained master index
│   └── {concept}/
│       └── {slug}.md
└── db/
    └── wikimind.db   # SQLite metadata
```

Override with `WIKIMIND_DATA_DIR=/custom/path`.

## Electron Desktop App

WikiMind also has an Electron shell:

```bash
# Install dependencies
make desktop-install

# Build the frontend first
cd apps/web && npm run build && cd ../..

# Launch the Electron app
make desktop
```
