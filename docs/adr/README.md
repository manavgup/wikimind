# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for WikiMind.
ADRs document key architecture decisions, explaining *why* choices were made
so future contributors do not re-debate settled questions.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adr-001-fastapi-async-sqlite.md) | FastAPI + async SQLite for local-first daemon | Accepted |
| [ADR-002](adr-002-arq-fakeredis.md) | ARQ + fakeredis for job queue | Accepted |
| [ADR-003](adr-003-multi-provider-llm-router.md) | Multi-provider LLM router with fallback | Accepted |
| [ADR-004](adr-004-markdown-files-sqlite-metadata.md) | Plain markdown files + SQLite metadata | Accepted |
| [ADR-005](adr-005-confidence-tagged-claims.md) | Confidence-tagged claims | Accepted |
| [ADR-006](adr-006-chunked-compilation.md) | Chunked compilation for large documents | Accepted |
| [ADR-007](adr-007-structured-json-prompt-contract.md) | Structured JSON prompt contract | Accepted |
| [ADR-008](adr-008-pydantic-basesettings.md) | Pydantic BaseSettings for configuration | Accepted |

## ADR Format

Each ADR follows a consistent structure:

- **Status** -- Accepted, Superseded, or Deprecated
- **Context** -- The problem or decision point
- **Decision** -- What was chosen and why
- **Alternatives Considered** -- What was evaluated and rejected
- **Consequences** -- What this enables, constrains, or risks
