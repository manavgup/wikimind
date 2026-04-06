# Contributing to WikiMind

## Getting Started

```bash
make venv          # create virtual environment
make install-dev   # install all dependencies
make check-env     # verify tools are present
make dev           # start gateway on :7842
```

## Pre-submission Checklist

```bash
make verify        # must pass before pushing
```

This runs: `lint` → `format-check` → `typecheck` → `test`

## Python Style

- **Python 3.11+**
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- Line length: **100 characters** (enforced by ruff)
- **Double quotes** for strings
- All imports at **top of file** — no inline/lazy imports unless justified by circular dependency
- Import order: **stdlib → third-party → local** (enforced by ruff isort)
- **Type annotations** on all public function signatures
- **Google-style docstrings** for public APIs

## File Structure

```python
"""Module docstring — one-line purpose statement."""

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

- Route handlers are **thin** — delegate to service layer
- Use `Depends()` for dependency injection
- Pydantic models for all request/response bodies
- No hardcoded magic numbers — use Settings or module-level constants

## Git Conventions

- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- One logical change per commit
- PRs require passing CI (lint + test + coverage)

## Testing

- Tests live in `tests/unit/` and `tests/integration/`
- Use in-memory SQLite (no external dependencies)
- Mock LLM calls — never hit real APIs in tests
- Custom markers: `@pytest.mark.slow`, `@pytest.mark.e2e`, `@pytest.mark.external`

```bash
make test          # run all tests
make test-unit     # unit tests only
make coverage      # tests + HTML coverage report
```
