# Concepts & Knowledge Graph

WikiMind organizes articles into a hierarchical concept taxonomy and interconnects them via typed backlinks.

## Concepts

Every compiled article is tagged with one or more **concepts** -- topic labels that group related articles. The LLM suggests concepts during compilation, reusing existing concept names to avoid fragmentation.

### Browsing concepts

```bash
# List all concepts (tree structure)
curl http://localhost:7842/wiki/concepts

# Exclude empty concepts (no articles)
curl "http://localhost:7842/wiki/concepts?include_empty=false"

# Get a specific concept with linked articles
curl http://localhost:7842/wiki/concepts/{name}

# List articles for a concept
curl http://localhost:7842/wiki/concepts/{name}/articles
```

### Concept taxonomy

Concepts are organized in a parent-child hierarchy. The taxonomy is rebuilt by the LLM when enough new concepts accumulate (controlled by `WIKIMIND_TAXONOMY__REBUILD_THRESHOLD`, default: 5).

You can trigger a manual rebuild:

```bash
curl -X POST http://localhost:7842/wiki/concepts/rebuild
```

### Concept pages

When a concept has enough source articles (controlled by `WIKIMIND_TAXONOMY__CONCEPT_PAGE_MIN_SOURCES`, default: 2), WikiMind auto-generates a **concept page** -- a synthesis article that summarizes all sources tagged with that concept.

Concept pages have `page_type: concept` and are recompiled automatically when new source articles are tagged with the same concept.

## Backlinks

Articles are connected via typed backlinks. The LLM suggests backlinks during compilation, and WikiMind resolves them against existing articles.

### Backlink types

| Type | Meaning |
|---|---|
| `references` | Mentions a related topic |
| `extends` | Builds on or adds to claims in another article |
| `supersedes` | Newer source replaces older claims |
| `contradicts` | Claims conflict with another article (added by the linter) |

### Knowledge graph

The full knowledge graph (all articles as nodes, all backlinks as edges) is available at:

```bash
curl http://localhost:7842/wiki/graph
```

The response contains:

- **nodes** -- Article ID, title, concept tags, confidence, page type
- **edges** -- Source article, target article, relationship type, context

## Contradiction Detection

The wiki linter identifies contradicting claims across articles and creates `contradicts` backlinks. You can resolve contradictions:

```bash
curl -X POST http://localhost:7842/wiki/backlinks/{source_id}/{target_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "resolution": "keep_both",
    "resolution_note": "Both perspectives are valid in different contexts"
  }'
```

Resolution options include: `keep_both`, `keep_source`, `keep_target`, `merge`, and `dismiss`.
