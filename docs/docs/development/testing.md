# Testing

WikiMind uses pytest with pytest-asyncio for all testing. Tests are organized into unit and integration tests.

## Running Tests

```bash
# Run all tests
make test

# Unit tests only
make test-unit

# Integration tests only
make test-integration

# Tests with coverage report
make coverage

# Tests with coverage, failing under 60%
make coverage-check
```

## Test Organization

```
tests/
├── conftest.py         # Shared fixtures (async session, mock settings)
├── unit/               # Fast, isolated tests
│   ├── test_compiler.py
│   ├── test_qa_agent.py
│   ├── test_llm_router.py
│   ├── test_ingest_*.py
│   └── ...
└── integration/        # Tests that hit the database
    └── ...
```

## Key Principles

### In-Memory Database

All tests use an in-memory SQLite database. The `conftest.py` provides a session fixture that creates and tears down the database for each test.

### Mock LLM Calls

Never hit real LLM APIs in tests. WikiMind provides a `MockProvider` that returns deterministic canned responses for compilation, Q&A, and linting. Enable it with:

```python
WIKIMIND_LLM__MOCK__ENABLED=true
WIKIMIND_LLM__DEFAULT_PROVIDER=mock
```

The mock provider is also used in CI to run the full pipeline without API keys.

### Async Tests

All tests are async (the entire backend is async). Use the `pytest.mark.asyncio` marker (configured project-wide) and async fixtures.

## Custom Markers

| Marker | Purpose |
|---|---|
| `@pytest.mark.slow` | Long-running tests (excluded from quick runs) |
| `@pytest.mark.e2e` | End-to-end tests |
| `@pytest.mark.external` | Tests that require external services |

## Writing a New Test

```python
"""Tests for the new feature."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import Source


@pytest.mark.asyncio
async def test_my_feature(session: AsyncSession):
    """Test that the feature works correctly."""
    # Arrange
    source = Source(title="Test", source_type="text")
    session.add(source)
    await session.commit()

    # Act
    result = await my_function(session)

    # Assert
    assert result is not None
    assert result.title == "Test"
```

## Test Matrix

WikiMind has an LLM test matrix for benchmarking compilation quality across providers and document types:

```bash
make test-matrix
# Shows usage:
# python scripts/run_test_matrix.py --doc PATH --doc-type LABEL --question TEXT --provider PROVIDER
```

Results are documented in `docs/test-matrix-results.md`.

## Coverage

The coverage threshold is 60%. Run with:

```bash
make coverage-check
```

Coverage reports are generated in HTML format at `htmlcov/index.html`.
