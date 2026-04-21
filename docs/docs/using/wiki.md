# Navigating the Wiki

Once sources are compiled, WikiMind maintains a structured wiki of interconnected articles. This page covers how to browse, search, and understand the wiki structure.

![Wiki Explorer — browse articles by concept, search, and filter](../assets/screenshots/wiki-explorer.svg)

## Article Types

WikiMind has several page types:

| Type | Description |
|---|---|
| `source` | Compiled from an ingested source (URL, PDF, text, YouTube) |
| `concept` | Auto-generated synthesis of all sources tagged with a concept |
| `answer` | Filed-back Q&A conversation |
| `index` | Auto-maintained master index |
| `meta` | System-generated metadata pages |

## Browsing Articles

### List all articles

```bash
curl http://localhost:7842/wiki/articles
```

### Filter articles

```bash
# By concept
curl "http://localhost:7842/wiki/articles?concept=machine-learning"

# By confidence level
curl "http://localhost:7842/wiki/articles?confidence=sourced"

# By page type
curl "http://localhost:7842/wiki/articles?page_type=source"

# Pagination
curl "http://localhost:7842/wiki/articles?limit=20&offset=40"
```

### Get a single article

Articles can be retrieved by ID or slug:

```bash
curl http://localhost:7842/wiki/articles/{id_or_slug}
```

The response includes:

- Full article content (markdown)
- Key claims with confidence tags
- Backlinks to related articles
- Source provenance (which original source produced this article)
- Concept tags

## Article Structure

Every compiled article follows a consistent structure:

```markdown
---
title: "Article Title"
slug: article-slug
page_type: source
source_id: uuid-of-original-source
source_url: https://original-url.com
compiled: 2025-01-15T10:30:00
concepts: [concept-a, concept-b]
confidence: sourced
provider: anthropic
---

## Summary

Two-sentence summary of what this is and why it matters.

## Key Claims

- **Specific claim** *(sourced)* -- "Optional direct quote"
- **Inferred claim** *(inferred)*

## Analysis

Full markdown article body with detailed analysis...

## Open Questions

- Question this source raises but does not answer

## Related

- [Related Article Title](/wiki/article-id)
- [[Unresolved Backlink]]

## Sources

- Original Source Title (ingested 2025-01-15)
```

## Confidence Levels

Articles are assigned an overall confidence based on their key claims:

| Level | Meaning | Criteria |
|---|---|---|
| `sourced` | Claims directly from the source | 80%+ of claims are sourced |
| `mixed` | Mix of sourced and inferred | 40-80% of claims are sourced |
| `inferred` | Mostly LLM inferences | Less than 40% of claims are sourced |

## Search

Full-text search across all articles:

```bash
curl "http://localhost:7842/wiki/search?q=neural+networks&limit=10"
```

Returns a ranked list of matching articles with title, summary, and confidence.

## Recompilation

Articles can be recompiled to generate a fresh version (useful if you change LLM providers or want a second opinion):

```bash
curl -X POST http://localhost:7842/wiki/articles/{article_id}/recompile
```

Recompilation replaces the existing article in place, preserving the same slug and URL.

## Wiki Health

The wiki health endpoint provides a summary of linter findings:

```bash
curl http://localhost:7842/wiki/health
```

Returns counts of total articles, contradictions, orphans, and overall status. For detailed findings, use the linter API at `/lint/reports/latest`.
