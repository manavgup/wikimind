# WikiMind — AI Assistant Guidelines

## Project Overview

WikiMind is a personal LLM-powered knowledge OS. The backend is a local FastAPI daemon (`src/wikimind/`) that ingests sources, compiles them into wiki articles via LLM, and answers questions against the wiki.

## Development Commands

```bash
make install-dev   # Install all dependencies
make dev           # Start gateway (port 7842)
make lint          # Run ruff linter
make format        # Run ruff formatter
make typecheck     # Run mypy
make test          # Run pytest
make coverage      # Run tests with coverage
make verify        # Run all quality checks (lint + format + typecheck + test)
```

## Coding Standards

### Python Style
- Python 3.11+
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- Line length: 100 characters (enforced by ruff)
- Double quotes for strings
- All imports at top of file — no inline/lazy imports unless there is a documented circular import reason
- Import order: stdlib, third-party, local (enforced by ruff isort)
- Type annotations on all public function signatures
- Google-style docstrings for public APIs

### FastAPI Conventions
- Route handlers are thin — delegate to service layer
- Use `Depends()` for dependency injection
- Pydantic models for all request/response bodies
- Consistent error response format: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`

### Git Conventions
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- One logical change per commit

## Project Structure

```
wikimind/
├── pyproject.toml          # Package definition + tool config
├── Makefile                # Developer workflow
├── src/wikimind/           # Source code
│   ├── main.py             # FastAPI app + lifespan
│   ├── config.py           # Pydantic BaseSettings
│   ├── models.py           # SQLModel tables + Pydantic schemas
│   ├── database.py         # SQLite + async session
│   ├── engine/             # LLM compiler, router, Q&A agent
│   ├── ingest/             # Source adapters (URL, PDF, text, YouTube)
│   ├── jobs/               # ARQ worker jobs
│   └── api/routes/         # FastAPI routers
├── tests/
│   ├── conftest.py         # Shared fixtures
│   ├── unit/
│   └── integration/
├── apps/web/               # React frontend (future)
└── docs/
```

## Rules

- NEVER create documentation files (*.md) or README files unless explicitly requested
- Prefer editing existing files over creating new ones
- Run `make verify` before considering work complete
- Do not add features, refactor code, or make improvements beyond what was asked
- Do not add error handling for scenarios that cannot happen
- Keep constants configurable via Settings, not hardcoded magic numbers
