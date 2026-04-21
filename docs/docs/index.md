# WikiMind

> You never write the wiki. You feed it. Every question makes it smarter.

WikiMind is a personal LLM-powered knowledge OS. Feed it articles, PDFs, YouTube videos, podcasts, or papers -- it compiles them into a structured wiki and answers questions with full source attribution.

## What WikiMind is

- **Not** a note-taking app -- you never write
- **Not** a chatbot -- it builds something persistent
- **Not** a RAG tool -- the wiki is the product, not a retrieval layer

It is the **synthesis layer** that sits above everything you consume.

## How it works

```
Feed --> Compile --> Query --> Answer files back --> Wiki gets smarter --> Repeat
```

1. **Feed** -- Ingest URLs, PDFs, raw text, or YouTube videos
2. **Compile** -- An LLM transforms each source into a structured wiki article with key claims, concepts, and backlinks
3. **Query** -- Ask questions against your wiki; the Q&A agent cites specific articles
4. **File back** -- High-confidence answers are filed back into the wiki, making it smarter over time

## Quick links

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Quick Start**

    ---

    Get WikiMind running locally in 5 minutes.

    [:octicons-arrow-right-24: Quick Start](overview/quick-start.md)

-   :material-file-document-multiple:{ .lg .middle } **Ingesting Sources**

    ---

    Learn how to feed URLs, PDFs, text, and YouTube videos.

    [:octicons-arrow-right-24: Ingestion Guide](using/ingestion.md)

-   :material-chat-question:{ .lg .middle } **Q&A Agent**

    ---

    Ask questions and get cited answers from your wiki.

    [:octicons-arrow-right-24: Q&A Guide](using/ask.md)

-   :material-cog:{ .lg .middle } **Configuration**

    ---

    All environment variables and settings documented.

    [:octicons-arrow-right-24: Settings Reference](configuration/settings.md)

</div>

## Tech stack

| Layer | Technology |
|---|---|
| Backend gateway | Python 3.11+ / FastAPI |
| Job queue | ARQ + asyncio (in-process for dev, ARQ + Redis for prod) |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLModel |
| LLM providers | Anthropic Claude, OpenAI GPT, Google Gemini, Ollama |
| PDF extraction | [docling-serve](https://github.com/docling-project/docling-serve) sidecar; pymupdf fallback |
| Document ingest | trafilatura (URLs), youtube-transcript-api (YouTube) |
| Frontend | React 18 + TypeScript + Vite + TanStack Query + Zustand + Tailwind CSS |
| Testing | pytest + pytest-asyncio + httpx |

## Status

**Phase 1 (Working Core)** -- Done

- [x] Backend pipeline: ingest -> compile -> query -> file-back
- [x] React UI: Inbox + Wiki Explorer
- [x] LLM provider abstraction with auto-enable
- [x] Multi-format ingest (URL, PDF, text, YouTube)
- [x] Source provenance and citation chains

**Phase 2 (Query Loop)** -- In progress

- [x] Conversational Q&A agent with thread file-back
- [x] React UI: Ask view with conversation threads
- [ ] Semantic search (ChromaDB + embeddings)
- [ ] Knowledge graph view
- [ ] Wiki linter and health dashboard
