# ADR-014: Hybrid search with ChromaDB and sentence-transformers

## Status

Accepted

## Context

WikiMind's search was a naive substring match against article titles and
content. This approach fails for semantic queries — a search for "neural
networks" would not find an article titled "Deep Learning" unless those
exact words appeared in the body. Users expect modern semantic search where
conceptually related content surfaces even without exact keyword overlap.

At the same time, keyword search is still valuable for precise lookups
(e.g. searching for a specific person's name or an acronym). A hybrid
approach that blends both signals outperforms either method alone.

## Decision

We add **ChromaDB** as a local vector store and **sentence-transformers**
(`all-MiniLM-L6-v2` by default) for embedding generation. Both are
declared as optional dependencies under the existing `[search]` extra in
`pyproject.toml` so they are never required for core functionality.

### Architecture

1. **EmbeddingService** (`services/embedding.py`) manages the ChromaDB
   persistent client, article chunking, embedding, and vector search.
2. After each successful compilation, the worker embeds the article's
   chunks into ChromaDB. Embedding failures are logged but never fail
   the compilation.
3. **WikiService.search()** performs hybrid search when the extras are
   installed: it runs both keyword substring matching and semantic
   vector search, then merges the results using configurable weights
   (default: 0.4 keyword + 0.6 semantic). When the extras are absent,
   search behavior is unchanged.
4. ChromaDB storage lives under `{data_dir}/db/chroma/`, co-located
   with the SQLite database.
5. Embedding model and chunking parameters are configurable via
   `EmbeddingConfig` in Pydantic Settings.

### Availability guard

The `_SEARCH_AVAILABLE` boolean follows the same pattern as
`_DOCLING_AVAILABLE` in the ingest layer. All code paths that touch
chromadb or sentence-transformers check this flag first and fall back
gracefully.

## Consequences

- **Better search quality.** Semantic similarity surfaces conceptually
  related articles that keyword matching misses.
- **Optional heavyweight dependency.** chromadb and sentence-transformers
  add ~500 MB of downloads and require a one-time model load. Users who
  don't need semantic search can skip the `[search]` extra entirely.
- **Graceful degradation.** The system works identically to before when
  the extras are not installed — no code changes required, no error
  messages on startup.
- **Increased storage.** ChromaDB's vector index adds disk usage
  proportional to the number of article chunks.
