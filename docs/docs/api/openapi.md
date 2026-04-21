# API Reference

WikiMind exposes a REST API via the FastAPI gateway running on port 7842.

## Base URL

```
http://localhost:7842
```

## Authentication

When auth is disabled (default), all endpoints are accessible without authentication. When enabled (`WIKIMIND_AUTH__ENABLED=true`), a session cookie is required for protected endpoints.

## Endpoints Overview

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (returns version) |

### Ingest

| Method | Path | Description |
|---|---|---|
| POST | `/ingest/url` | Ingest a web URL or YouTube video |
| POST | `/ingest/pdf` | Upload and ingest a PDF |
| POST | `/ingest/text` | Ingest raw text or a note |
| GET | `/ingest/sources` | List all ingested sources |
| GET | `/ingest/sources/{source_id}` | Get source by ID |
| DELETE | `/ingest/sources/{source_id}` | Delete a source |
| GET | `/ingest/sources/{source_id}/original` | Stream the original source document |

### Wiki

| Method | Path | Description |
|---|---|---|
| GET | `/wiki/articles` | List wiki articles (filterable) |
| GET | `/wiki/articles/{id_or_slug}` | Get full article by ID or slug |
| POST | `/wiki/articles/{article_id}/recompile` | Schedule article recompilation |
| GET | `/wiki/graph` | Full knowledge graph (nodes + edges) |
| GET | `/wiki/search` | Full-text search across articles |
| GET | `/wiki/concepts` | Concept taxonomy tree |
| POST | `/wiki/concepts/rebuild` | Trigger LLM taxonomy rebuild |
| GET | `/wiki/concepts/{name}` | Concept detail with linked articles |
| GET | `/wiki/concepts/{name}/articles` | Articles tagged with a concept |
| GET | `/wiki/health` | Wiki health summary (deprecated) |
| POST | `/wiki/backlinks/{source_id}/{target_id}/resolve` | Resolve a contradiction |
| GET | `/wiki/contradiction-resolutions` | Valid resolution options |

### Query (Q&A)

| Method | Path | Description |
|---|---|---|
| POST | `/query` | Ask a question against the wiki |
| POST | `/query/stream` | Stream an answer via SSE |
| GET | `/query/history` | List past queries (legacy) |
| GET | `/query/conversations` | List conversations |
| GET | `/query/conversations/{id}` | Get conversation with all turns |
| GET | `/query/conversations/{id}/export` | Export conversation as markdown |
| POST | `/query/conversations/{id}/file-back` | File conversation to wiki |
| POST | `/query/conversations/file-back` | File selected turns to wiki |
| POST | `/query/conversations/{id}/fork` | Fork conversation at a turn |

### Jobs

| Method | Path | Description |
|---|---|---|
| GET | `/jobs` | List jobs |
| GET | `/jobs/{job_id}` | Get job status |

### Lint

| Method | Path | Description |
|---|---|---|
| POST | `/lint/run` | Run the wiki linter |
| GET | `/lint/reports` | List lint reports |
| GET | `/lint/reports/latest` | Latest lint report |
| GET | `/lint/reports/{report_id}` | Get a specific report |

### Settings

| Method | Path | Description |
|---|---|---|
| GET | `/settings/providers` | List LLM provider status |
| GET | `/settings/costs` | Cost tracking summary |
| GET | `/settings/preferences` | Get user preferences |
| PUT | `/settings/preferences` | Update user preferences |

### Auth

| Method | Path | Description |
|---|---|---|
| GET | `/auth/providers` | Available OAuth2 providers |
| GET | `/auth/login/{provider}` | Start OAuth2 flow |
| GET | `/auth/callback/{provider}` | OAuth2 callback |
| POST | `/auth/logout` | Logout (clear session cookie) |
| GET | `/auth/me` | Current user info |

### Admin

| Method | Path | Description |
|---|---|---|
| GET | `/admin/diagnostics` | System diagnostics |

### WebSocket

| Method | Path | Description |
|---|---|---|
| WS | `/ws` | Real-time event stream |

## Error Response Format

All errors follow a consistent format:

```json
{
  "error": {
    "code": "not_found",
    "message": "Article not found",
    "request_id": "abc-123"
  }
}
```

## OpenAPI Schema

The full OpenAPI specification is auto-generated from the FastAPI app and available at:

- **Interactive docs**: `http://localhost:7842/docs` (Swagger UI)
- **ReDoc**: `http://localhost:7842/redoc`
- **Raw schema**: `http://localhost:7842/openapi.json`

The schema is also exported to [`docs/openapi.yaml`](https://github.com/manavgup/wikimind/blob/main/docs/openapi.yaml) in the repository. Regenerate it with:

```bash
make export-openapi
```

## WebSocket Events

Connect to `ws://localhost:7842/ws` for real-time updates.

### Server -> Client

| Event | Payload | When |
|---|---|---|
| `connected` | `{message}` | On WebSocket connect |
| `job.progress` | `{job_id, pct, message}` | During any job |
| `compilation.complete` | `{article_slug, article_title}` | Source compiled |
| `compilation.failed` | `{source_id, error}` | Compilation error |
| `linter.alert` | `{type, articles}` | Linter finds issues |
| `budget.warning` | `{spend, budget, pct}` | Budget threshold reached |
| `budget.exceeded` | `{spend, budget}` | Monthly budget exceeded |
| `keepalive` | -- | Every 30s |

### Client -> Server

| Message | Payload | Purpose |
|---|---|---|
| `ping` | `{type: "ping"}` | Keepalive response |
