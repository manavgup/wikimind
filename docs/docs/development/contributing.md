# Contributing

This guide covers the development workflow and coding standards for WikiMind.

## Getting Started

```bash
git clone https://github.com/manavgup/wikimind.git
cd wikimind

make venv          # create virtual environment
make install-dev   # install all dependencies
make check-env     # verify tools are present
make dev           # start gateway on :7842
```

## Pre-Submission Checklist

Before pushing, run the full quality suite:

```bash
make verify
```

This runs: `lint` -> `format-check` -> `typecheck` -> `pyright` -> `docstyle` -> `coverage-check` -> `desktop-verify`

Pre-commit hooks (`make pre-commit`) enforce the same checks automatically.

## Python Style

- **Python 3.11+**
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- Line length: **100 characters** (enforced by ruff)
- **Double quotes** for strings
- All imports at **top of file** -- no inline/lazy imports unless justified by circular dependency
- Import order: **stdlib -> third-party -> local** (enforced by ruff isort)
- **Type annotations** on all public function signatures
- **Google-style docstrings** for public APIs

## File Structure

```python
"""Module docstring -- one-line purpose statement."""

import stdlib
import third_party
from wikimind import local

CONSTANTS = "here"


class MyClass:
    ...


def my_function():
    ...
```

## FastAPI Conventions

- Route handlers are **thin** -- delegate to the service layer
- Use `Depends()` for dependency injection
- Pydantic models for all request/response bodies
- Consistent error response format: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`
- No hardcoded magic numbers -- use `Settings` or module-level constants

## Architecture Layers

```
API routes (thin)  ->  Services (business logic)  ->  Engine (LLM calls)
                                                  ->  Database (queries)
                                                  ->  Storage (files)
```

- **Routes** accept HTTP requests, validate input, and delegate to services
- **Services** contain business logic, orchestrate multiple engine/database calls
- **Engine** handles LLM interactions (compiler, Q&A, linter, router)
- **Database** manages the SQLModel/SQLAlchemy session lifecycle
- **Storage** abstracts file system operations

## Git Conventions

- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- One logical change per commit
- PRs require passing CI (lint + test + coverage)

## Documentation Co-Change Rules

When you modify source code, the doc-sync system checks whether related documentation needs updating:

- **`src/wikimind/config.py`** -> Update `.env.example` if settings change
- **`src/wikimind/api/routes/`** -> Run `make export-openapi` to regenerate OpenAPI schema
- **Architecture decisions** -> Add or update ADRs in `docs/adr/`
- **Make targets** -> Run `make regenerate-readme-targets` if Makefile changes

Use `[skip-doc-check]` in commit messages or the `docs-skip` PR label to bypass when truly necessary.

## Adding a New Source Adapter

1. Create `src/wikimind/ingest/adapters/my_adapter.py`
2. Implement the adapter class with an `ingest()` method that returns `(Source, NormalizedDocument)`
3. Register the adapter in `IngestService` (`src/wikimind/ingest/service.py`)
4. Add a route in `src/wikimind/api/routes/ingest.py`
5. Write tests in `tests/unit/test_ingest_my_adapter.py`

## Adding a New LLM Provider

1. Create `src/wikimind/engine/providers/my_provider.py`
2. Implement the `ProviderProtocol` interface (`complete`, `stream`, `complete_multimodal`)
3. Add a config class in `config.py` and add it to `LLMConfig`
4. Register in `LLMRouter._get_provider_instance()`
5. Add pricing to `PRICING` in `llm_router.py`
