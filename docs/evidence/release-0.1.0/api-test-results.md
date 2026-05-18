# WikiMind API Test Results

**Date:** 2026-05-18T21:44:06Z
**Target:** `http://localhost:7842`
**Script:** [api-test.sh](api-test.sh)

---


## 0. Health & Connectivity

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/health` | 200 |
| PASS | `GET` | `/health/deep` | 200 |

## 1. Authentication

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/auth/me` | 200 |
| PASS | `POST` | `/auth/magic-link` | 200 |
| PASS | `GET` | `/auth/tokens` | 200 |
| PASS | `GET` | `/auth/tokens.js` | 200 |
| SKIP | — | OAuth login redirect | *requires browser redirect* |
| SKIP | — | OAuth callback | *requires valid OAuth code* |
| SKIP | — | Magic link verify | *requires valid token* |
| SKIP | — | Create API token | *would create persistent token* |
| SKIP | — | Logout | *would end session* |
| SKIP | — | Delete account | *destructive* |

## 2. Content Ingestion

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/ingest/sources` | 200 |
| PASS | `GET` | `/api/ingest/sources/b1bd487a-ca9d-49b6-bebc-10a68b1125e9` | 200 |
| PASS | `GET` | `/api/ingest/sources/b1bd487a-ca9d-49b6-bebc-10a68b1125e9/detail` | 200 |
| PASS | `GET` | `/api/ingest/sources/b1bd487a-ca9d-49b6-bebc-10a68b1125e9/content` | 200 |
| PASS | `GET` | `/api/ingest/sources/b1bd487a-ca9d-49b6-bebc-10a68b1125e9/images` | 200 |
| PASS | `POST` | `/api/ingest/text` | 200 |
| PASS | `GET` | `/api/ingest/sources/0f2b2584-a66f-4c01-991e-f510d7374c03/images` | 200 |
| PASS | `GET` | `/api/ingest/sources/0f2b2584-a66f-4c01-991e-f510d7374c03/images/picture-1.png` | 200 |
| SKIP | — | Ingest URL | *would trigger LLM compilation (costly)* |
| SKIP | — | Ingest PDF | *would trigger LLM compilation (costly)* |
| SKIP | — | Get source original | *binary download; tested via browser* |
| SKIP | — | Delete source | *destructive; would remove data* |

## 3. Draft Review

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/ingest/sources/b1bd487a-ca9d-49b6-bebc-10a68b1125e9/draft` | 404 |
| SKIP | — | Approve draft | *requires pending draft* |
| SKIP | — | Reject draft | *requires pending draft* |

## 4. Wiki & Knowledge Base

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/articles` | 200 |
| PASS | `GET` | `/api/wiki/articles?page_type=source&limit=5` | 200 |
| PASS | `GET` | `/api/wiki/articles/mock-article` | 200 |
| PASS | `GET` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86` | 200 |
| PASS | `GET` | `/api/wiki/articles/mock-article/relationships` | 200 |
| PASS | `GET` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/tags` | 200 |
| PASS | `GET` | `/api/wiki/articles/random` | 200 |
| PASS | `GET` | `/api/wiki/search?q=transformer&limit=5` | 200 |
| PASS | `GET` | `/api/wiki/search/facets?q=transformer` | 200 |
| PASS | `GET` | `/api/wiki/wikilinks/resolve?q=attention&limit=5` | 200 |
| PASS | `GET` | `/api/wiki/graph` | 200 |
| SKIP | — | Get wiki health | *deprecated; use /lint/reports/latest* |
| SKIP | — | Create stub article | *would create persistent data* |
| SKIP | — | Edit article | *would modify existing article* |
| SKIP | — | Refresh article | *would reset staleness timer* |
| SKIP | — | Recompile article | *would trigger LLM compilation* |

## 5. Concept Taxonomy

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/concepts` | 200 |
| PASS | `GET` | `/api/wiki/concepts/testing` | 200 |
| PASS | `GET` | `/api/wiki/concepts/testing/articles` | 200 |
| SKIP | — | Rebuild taxonomy | *would trigger LLM call* |

## 6. Contradictions & Quality

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/contradictions` | 200 |
| PASS | `GET` | `/api/wiki/contradiction-resolutions` | 200 |
| SKIP | — | Get contradiction | *no contradictions found* |
| SKIP | — | Resolve contradiction | *would modify state* |

## 7. Export & Download

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/export?format=markdown` | 200 |
| PASS | `GET` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/export?format=json` | 200 |
| PASS | `GET` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/export?format=csv` | 422 |
| SKIP | — | Export as PDF | *requires wkhtmltopdf* |
| SKIP | — | Export full wiki | *large download* |

## 8. Sharing & Public Access

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/share-links` | 200 |
| PASS | `POST` | `/api/wiki/share-links` | 201 |
| PASS | `GET` | `/public/articles/HfvnEJee3-PYlqqjm751wVXLbrVqgFX3kh2AyomSRw4` | 200 |
| PASS | `GET` | `/public/articles/HfvnEJee3-PYlqqjm751wVXLbrVqgFX3kh2AyomSRw4/json` | 200 |
| PASS | `GET` | `/api/wiki/share-links?article_id=3e38435d-e06f-453d-b344-0caf4433ac86` | 200 |
| PASS | `GET` | `/public/articles/nonexistent-token` | 404 |

## 9. Synthesis

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/wiki/synthesis` | 200 |
| PASS | `GET` | `/api/wiki/synthesis/suggestions` | 200 |
| PASS | `GET` | `/api/wiki/synthesis/suggestions?limit=3` | 200 |
| PASS | `POST` | `/api/wiki/synthesis/preview` | 200 |
| SKIP | — | Synthesis refine | *requires previous preview draft* |
| SKIP | — | Synthesis confirm | *would create persistent article* |
| SKIP | — | Create synthesis (direct) | *would trigger LLM call* |

## 10. Query & Conversations

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/query/conversations` | 200 |
| PASS | `GET` | `/api/query/history?limit=5` | 200 |
| PASS | `GET` | `/api/query/conversations/42542608-692e-436e-931d-0394f7e5779a` | 200 |
| PASS | `GET` | `/api/query/conversations/42542608-692e-436e-931d-0394f7e5779a/export` | 200 |
| SKIP | — | Ask question | *would trigger LLM call* |
| SKIP | — | Ask (streaming) | *would trigger LLM call* |
| SKIP | — | Fork conversation | *would trigger LLM call* |
| SKIP | — | File back | *would create article* |
| SKIP | — | Crystallize | *would trigger LLM call* |

## 11. Tags

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/tags` | 200 |
| PASS | `POST` | `/api/tags` | 201 |
| PASS | `POST` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/tags` | 201 |
| PASS | `GET` | `/api/tags/502dd00f-304a-47a0-8635-7c3ab2508a10/articles` | 200 |
| PASS | `DELETE` | `/api/wiki/articles/3e38435d-e06f-453d-b344-0caf4433ac86/tags/502dd00f-304a-47a0-8635-7c3ab2508a10` | 204 |

## 12. Saved Searches

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/saved-searches` | 200 |
| PASS | `POST` | `/api/saved-searches` | 201 |
| PASS | `POST` | `/api/saved-searches/f36496a1-fe90-4e63-9f36-ff8fc33e5760/execute` | 200 |

## 13. Compilation Schemas

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/compilation-schemas` | 200 |
| PASS | `POST` | `/api/compilation-schemas` | 201 |
| PASS | `GET` | `/api/compilation-schemas/048a5909-2066-42a7-84d2-498b1a86a4e3` | 200 |
| PASS | `PATCH` | `/api/compilation-schemas/048a5909-2066-42a7-84d2-498b1a86a4e3` | 200 |

## 14. Ambient Capture

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/capture` | 200 |
| PASS | `GET` | `/api/capture/rss/feeds` | 200 |
| PASS | `POST` | `/api/capture/clipboard` | 200 |
| SKIP | — | Ingest capture | *would trigger compilation* |
| SKIP | — | Subscribe RSS | *would create persistent subscription* |
| SKIP | — | Poll RSS | *would fetch external content* |

## 15. Background Jobs

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/jobs` | 200 |
| SKIP | — | Trigger compile | *would trigger LLM call* |
| SKIP | — | Trigger lint | *would trigger LLM call* |
| SKIP | — | Trigger reindex | *modifies search index* |

## 16. Linting & Quality

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/lint/reports` | 200 |
| PASS | `GET` | `/api/lint/reports/latest` | 404 |
| SKIP | — | Run lint | *would trigger LLM call* |
| SKIP | — | Dismiss finding | *would modify state* |

## 17. Settings & Configuration

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/settings` | 200 |
| PASS | `GET` | `/api/settings/llm/cost` | 200 |
| PASS | `GET` | `/api/settings/llm/cost/breakdown` | 200 |
| PASS | `GET` | `/api/settings/onboarding-status` | 200 |
| SKIP | — | Set default provider | *would change config* |
| SKIP | — | Update settings | *would change config* |
| SKIP | — | Test LLM connection | *would make external call* |

## 18. API Keys (BYOK)

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/settings/api-keys` | 200 |
| SKIP | — | Set API key | *would store secret* |
| SKIP | — | Delete API key | *destructive* |

## 19. MCP Tokens

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/settings/mcp-tokens` | 200 |
| SKIP | — | Create MCP token | *would create persistent token* |
| SKIP | — | Revoke MCP token | *destructive* |

## 20. MCP OAuth

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/.well-known/oauth-authorization-server` | 200 |
| SKIP | — | MCP authorize | *requires browser interaction* |
| SKIP | — | MCP token exchange | *requires valid auth code* |
| SKIP | — | MCP revoke | *requires valid token* |

## 21. Admin Dashboard

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/admin/stats` | 200 |
| PASS | `GET` | `/api/admin/orphans` | 200 |
| PASS | `GET` | `/api/admin/concepts/eligible` | 200 |
| PASS | `GET` | `/api/admin/stuck-sources` | 200 |
| PASS | `GET` | `/api/admin/docling-status` | 200 |
| PASS | `GET` | `/api/admin/traces` | 200 |
| SKIP | — | Retry stuck source | *would re-queue compilation* |
| SKIP | — | Sweep wikilinks | *modifies graph* |
| SKIP | — | Reindex | *modifies search index* |

## 22. Rate Limiting

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `POST` | `/auth/magic-link` | 429 |

## 23. Error Handling

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `GET` | `/api/nonexistent` | 200 |
| PASS | `GET` | `/api/wiki/articles/nonexistent-slug-12345` | 404 |
| PASS | `POST` | `/api/ingest/text` | 422 |

## CLEANUP

| Status | Method | Path | Code |
|--------|--------|------|------|
| PASS | `DELETE` | `/api/wiki/share-links/6f170c93-0360-4bbd-9163-cc1c0cadcb01` | 204 |
| PASS | `DELETE` | `/api/tags/502dd00f-304a-47a0-8635-7c3ab2508a10` | 204 |
| PASS | `DELETE` | `/api/saved-searches/f36496a1-fe90-4e63-9f36-ff8fc33e5760` | 204 |
| PASS | `DELETE` | `/api/compilation-schemas/048a5909-2066-42a7-84d2-498b1a86a4e3` | 204 |
| PASS | `POST` | `/api/capture/cd92e62b-dc2f-41ed-a26a-50bbe41e5ead/discard` | 200 |
| PASS | `DELETE` | `/api/ingest/sources/000718b9-e9a3-4b91-af8b-75fb107d73ab` | 200 |

---

## Summary

| Metric | Count |
|--------|-------|
| Total  | 140 |
| Pass   | 89 |
| Fail   | 0 |
| Skip   | 51 |

**Skip reasons:** Endpoints that trigger LLM calls, create persistent data, require browser OAuth, or are destructive are intentionally skipped. The test script is idempotent — all test artifacts are cleaned up.
