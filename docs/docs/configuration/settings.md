# Settings Reference

All WikiMind configuration is managed via environment variables, loaded by [Pydantic BaseSettings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). A `.env` file at the project root is loaded automatically.

## Environment Variable Format

WikiMind uses the `WIKIMIND_` prefix for all settings. Nested settings use the `__` delimiter:

```bash
WIKIMIND_LLM__OPENAI__ENABLED=true
# Sets: settings.llm.openai.enabled = True
```

## LLM API Keys

Set at least one API key. The provider auto-enables when a key is detected.

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google Gemini API key |

!!! tip
    API keys work both with and without the `WIKIMIND_` prefix (e.g., both `ANTHROPIC_API_KEY` and `WIKIMIND_ANTHROPIC_API_KEY` are accepted). Keys are also read from the OS keychain via `keyring`.

## LLM Provider Configuration

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_LLM__DEFAULT_PROVIDER` | `anthropic` | Default LLM provider (`anthropic`, `openai`, `google`, `ollama`, `mock`) |
| `WIKIMIND_LLM__FALLBACK_ENABLED` | `true` | Fall back to other providers when the default fails |
| `WIKIMIND_LLM__MONTHLY_BUDGET_USD` | `50.0` | Monthly spending ceiling across all providers (USD) |
| `WIKIMIND_LLM__BUDGET_WARNING_PCT` | `0.8` | Budget warning threshold (fraction 0.0-1.0) |
| `WIKIMIND_LLM__BUDGET_CHECK_CACHE_SECONDS` | `60` | How often the router re-queries cost logs |

### Per-Provider Settings

Each provider has `model` and `enabled` settings:

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_LLM__ANTHROPIC__MODEL` | `claude-sonnet-4-5` | Anthropic model name |
| `WIKIMIND_LLM__ANTHROPIC__ENABLED` | auto | Enabled when API key detected |
| `WIKIMIND_LLM__OPENAI__MODEL` | `gpt-4o` | OpenAI model name |
| `WIKIMIND_LLM__OPENAI__ENABLED` | auto | Enabled when API key detected |
| `WIKIMIND_LLM__GOOGLE__MODEL` | `gemini-2.0-flash` | Google Gemini model name |
| `WIKIMIND_LLM__GOOGLE__ENABLED` | auto | Enabled when API key detected |
| `WIKIMIND_LLM__OLLAMA__MODEL` | `llama3.2` | Ollama model name |
| `WIKIMIND_LLM__OLLAMA__ENABLED` | `false` | Must be explicitly enabled (no API key) |
| `WIKIMIND_LLM__OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `WIKIMIND_LLM__MOCK__ENABLED` | `false` | Enable mock provider (CI/testing only) |

## Server

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_SERVER__HOST` | `127.0.0.1` | Server bind address |
| `WIKIMIND_SERVER__PORT` | `7842` | Server port |
| `WIKIMIND_GATEWAY_PORT` | `7842` | Gateway port (used by lifespan logging) |

## Database

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_DATABASE_URL` | `sqlite+aiosqlite:///~/.wikimind/db/wikimind.db` | Database connection URL |
| `WIKIMIND_DATABASE__ECHO` | `false` | Verbose SQL query logging |
| `DATABASE_URL` | -- | Fallback for managed Postgres (Fly.io, Railway, etc.) |

The `DATABASE_URL` fallback auto-rewrites `postgres://` and `postgresql://` to `postgresql+asyncpg://` for SQLAlchemy async compatibility. On Fly.io, `sslmode` is converted for asyncpg.

## Data Directory

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_DATA_DIR` | `~/.wikimind` | Base data directory |
| `WIKIMIND_STORAGE_BACKEND` | `local` | Storage backend (`local` or `r2`) |

## Job Queue

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_REDIS_URL` | -- | Redis URL for ARQ job queue |
| `REDIS_URL` | -- | Fallback (unprefixed) Redis URL |

When unset, compilations run in-process (single-user dev mode). No Redis needed.

## PDF Extraction

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_DOCLING_SERVE_URL` | `http://localhost:5001` | docling-serve sidecar URL |
| `WIKIMIND_DOCLING_BATCH_PAGES` | `10` | Pages per Docling batch |

### Vision Processing

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_VISION_ENABLED` | `true` | Enable vision-enhanced slide deck ingestion |
| `WIKIMIND_VISION_TEXT_THRESHOLD` | `300` | Characters below which a page is treated as image-heavy |
| `WIKIMIND_VISION_DPI` | `150` | DPI for rendering pages as images |
| `WIKIMIND_VISION_MAX_PAGES_PER_BATCH` | `20` | Max pages per vision batch |

### Image Extraction

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_IMAGE_EXTRACTION_ENABLED` | `true` | Extract figures/tables from PDFs |
| `WIKIMIND_IMAGE_MAX_PER_PDF` | `30` | Maximum images to extract per PDF |
| `WIKIMIND_IMAGE_BASE_URL` | `/images` | Base URL for serving extracted images |

## Q&A Agent

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_QA__MAX_PRIOR_TURNS_IN_CONTEXT` | `5` | Prior conversation turns included in context |
| `WIKIMIND_QA__PRIOR_ANSWER_TRUNCATE_CHARS` | `500` | Max characters per prior answer in context |
| `WIKIMIND_QA__CONVERSATION_TITLE_MAX_CHARS` | `120` | Max characters for auto-generated conversation titles |

## Concept Taxonomy

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_TAXONOMY__REBUILD_THRESHOLD` | `5` | New concepts before auto-triggering taxonomy rebuild |
| `WIKIMIND_TAXONOMY__MAX_HIERARCHY_DEPTH` | `3` | Maximum depth of concept hierarchy |
| `WIKIMIND_TAXONOMY__CONCEPT_PAGE_MIN_SOURCES` | `2` | Minimum sources before generating a concept page |

## Wiki Linter

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_LINTER__ENABLE_ORPHAN_DETECTION` | `true` | Enable orphan article detection |
| `WIKIMIND_LINTER__MAX_CONCEPTS_PER_RUN` | `25` | Max concepts to check per lint run |
| `WIKIMIND_LINTER__MAX_CONTRADICTION_PAIRS_PER_CONCEPT` | `10` | Max article pairs per concept for contradiction detection |
| `WIKIMIND_LINTER__CONTRADICTION_LLM_MAX_TOKENS` | `1024` | Max tokens for contradiction LLM calls |
| `WIKIMIND_LINTER__CONTRADICTION_LLM_TEMPERATURE` | `0.2` | Temperature for contradiction detection |
| `WIKIMIND_LINTER__ENABLE_PAIR_CACHE` | `true` | Skip re-evaluating unchanged article pairs |
| `WIKIMIND_LINTER__CONTRADICTION_BATCH_ENABLED` | `true` | Batch multiple pairs into single LLM calls |
| `WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE` | `10` | Pairs per batch |
| `WIKIMIND_LINTER__MAX_CONCEPT_CONCURRENCY` | `5` | Concurrent concept checks |

## Embedding / Semantic Search

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_EMBEDDING__MODEL_NAME` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `WIKIMIND_EMBEDDING__CHUNK_SIZE_TOKENS` | `500` | Chunk size for embedding |
| `WIKIMIND_EMBEDDING__CHUNK_OVERLAP_TOKENS` | `50` | Overlap between chunks |
| `WIKIMIND_EMBEDDING__MIN_SIMILARITY_SCORE` | `0.65` | Minimum similarity for search results |

## Authentication

See the [Authentication](auth.md) page for detailed setup.

| Variable | Default | Description |
|---|---|---|
| `WIKIMIND_AUTH__ENABLED` | `false` | Enable multi-user authentication |
| `WIKIMIND_AUTH__JWT_SECRET_KEY` | -- | Secret key for JWT signing (required when auth enabled) |
| `WIKIMIND_AUTH__JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `WIKIMIND_AUTH__JWT_EXPIRY_MINUTES` | `1440` | JWT expiry (24 hours) |
| `WIKIMIND_AUTH__COOKIE_NAME` | `wikimind_session` | Session cookie name |
| `WIKIMIND_AUTH__COOKIE_SECURE` | `true` | Require HTTPS for cookies |
| `WIKIMIND_AUTH__COOKIE_DOMAIN` | -- | Cookie domain (None = current host) |

## Production Deployment

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `wikimind` | PostgreSQL username (docker-compose.prod.yml) |
| `POSTGRES_PASSWORD` | -- | PostgreSQL password (required) |
| `POSTGRES_DB` | `wikimind` | PostgreSQL database name |
| `WIKIMIND_PORT` | `7842` | Host port for the gateway |
| `WIKIMIND_IMAGE` | `wikimind:latest` | Docker image tag |
| `WEB_CONCURRENCY` | auto | Gunicorn worker count (auto-tunes to CPU) |
| `LOG_LEVEL` | `INFO` | Logging level |
