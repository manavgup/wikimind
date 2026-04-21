# Architecture Decision Records

This section contains the architectural decisions for WikiMind. Each ADR documents a single significant decision, the alternatives considered, and the consequences.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [001](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-001-fastapi-async-sqlite.md) | FastAPI + async SQLite for local-first daemon | Accepted |
| [002](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-002-arq-fakeredis.md) | ARQ + fakeredis for job queue | Accepted |
| [003](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-003-multi-provider-llm-router.md) | Multi-provider LLM router with fallback | Accepted |
| [004](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-004-markdown-files-sqlite-metadata.md) | Plain markdown files + SQLite metadata | Accepted |
| [005](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-005-confidence-tagged-claims.md) | Confidence-tagged claims | Accepted |
| [006](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-006-chunked-compilation.md) | Chunked compilation for large documents | Accepted |
| [007](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-007-structured-json-prompt-contract.md) | Structured JSON prompt contract | Accepted |
| [008](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-008-pydantic-basesettings.md) | Pydantic BaseSettings for configuration | Accepted |
| [009](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-009-decoupled-ingest-compilation.md) | Decoupled ingest and compilation | Accepted |
| [010](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-010-llm-provider-auto-enable.md) | Auto-enable LLM providers when API key detected | Accepted |
| [011](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-011-conversational-qa-thread-model.md) | Conversational Q&A thread model | Accepted |
| [012](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-012-knowledge-graph-architecture.md) | Knowledge graph architecture | Accepted |
| [013](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-013-react-force-graph-2d.md) | react-force-graph-2d for knowledge graph | Proposed |
| [014](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-014-hybrid-search-architecture.md) | Hybrid search with ChromaDB and sentence-transformers | Accepted |
| [015](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-015-cpu-first-docker-packaging.md) | CPU-First Docker Packaging | Accepted |
| [016](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-016-article-recompilation.md) | Article recompilation as first-class action | Accepted |
| [017](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-017-backlink-enforcer-lint-phase.md) | Backlink enforcer as lint Phase 3 | Accepted |
| [018](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-018-batched-contradiction-detection.md) | Batched Contradiction Detection | Accepted |
| [019](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-019-runtime-user-preferences.md) | Runtime User Preferences via DB Override Table | Accepted |
| [021](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-021-postgres-compatibility.md) | PostgreSQL compatibility for production | Accepted |
| [022](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-022-multi-user-authentication.md) | Multi-User Authentication via OAuth2 | Accepted |
| [023](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-023-production-container-architecture.md) | Production Container Architecture | Accepted |
| [024](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-024-gunicorn-autoscaling-horizontal-readiness.md) | Gunicorn Auto-Scaling and Horizontal Readiness | Accepted |
| [025](https://github.com/manavgup/wikimind/blob/main/docs/adr/adr-025-docling-serve-sidecar.md) | Docling-Serve Sidecar for PDF Extraction | Accepted |

## ADR Format

Each ADR follows a consistent structure:

- **Status** -- Accepted, Proposed, Superseded, or Deprecated
- **Context** -- The problem or decision point
- **Decision** -- What was chosen and why
- **Alternatives Considered** -- What was evaluated and rejected
- **Consequences** -- What this enables, constrains, or risks

## Key Architectural Themes

### Local-First Design

WikiMind is designed as a local-first application (ADR-001, ADR-004). The database is SQLite, articles are plain markdown files, and the gateway runs as a local daemon. This means:

- Your data stays on your machine
- No internet required for browsing and searching
- Cloud deployment is optional (ADR-021)

### LLM Provider Abstraction

The LLM router (ADR-003) provides a unified interface across multiple providers. Auto-enable (ADR-010) means you just set an API key and the provider works. Fallback ensures resilience.

### Structured Prompts

The JSON prompt contract (ADR-007) ensures consistent, parseable output from any LLM provider. The compiler and Q&A agent both use structured JSON responses rather than free-form text.

### Decoupled Pipeline

Ingestion and compilation are decoupled (ADR-009). Sources are saved immediately and compiled asynchronously via the job queue. This allows the UI to be responsive while compilation happens in the background.
