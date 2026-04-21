# Features

WikiMind transforms raw information into a structured, interconnected knowledge base. Here is what it can do today.

## Source Ingestion

Feed WikiMind from multiple source types:

- **Web URLs** -- Articles, blog posts, documentation pages. Extracted via trafilatura with full HTML cleanup.
- **PDF documents** -- Research papers, reports, slide decks. Processed by [docling-serve](https://github.com/docling-project/docling-serve) for structured extraction (heading hierarchy, tables, OCR). Falls back to pymupdf when docling-serve is unavailable.
- **Raw text** -- Paste notes, meeting transcripts, or any plain text directly.
- **YouTube videos** -- Extracts the transcript automatically via youtube-transcript-api.

Sources are deduplicated by content hash, so re-ingesting the same document is a no-op.

## LLM Compilation

Every ingested source is compiled into a structured wiki article by an LLM. The compilation produces:

- **Title and summary** -- Concise, specific article title and a two-sentence summary
- **Key claims** -- Specific, falsifiable claims extracted from the source, each tagged with a confidence level (`sourced`, `inferred`, or `opinion`) and optional direct quote
- **Concepts** -- Topic tags that connect the article to the broader knowledge graph
- **Backlink suggestions** -- Related articles with typed relationships (`references`, `extends`, `supersedes`)
- **Open questions** -- Gaps the source raises but does not answer
- **Article body** -- Full markdown article (300+ words) with analysis

Large documents (over 80K tokens) are automatically chunked and compiled in parts, then merged into a single article.

## Multi-Provider LLM Router

WikiMind supports multiple LLM providers with automatic fallback:

| Provider | Default Model | Notes |
|---|---|---|
| Anthropic | claude-sonnet-4-5 | Default provider |
| OpenAI | gpt-4o | |
| Google | gemini-2.0-flash | |
| Ollama | llama3.2 | Local, no API key needed |

Providers are **auto-enabled** when their API key is detected -- no manual configuration flags needed. The router falls back to the next available provider when one fails.

Monthly budget tracking with WebSocket alerts prevents surprise bills.

## Conversational Q&A

Ask questions against your compiled wiki:

- **Multi-turn conversations** -- Follow-up questions carry context from prior turns
- **Source citations** -- Every answer cites the wiki articles it drew from
- **Confidence scoring** -- Answers are rated high/medium/low confidence
- **File-back** -- High-confidence answers are filed back into the wiki as new articles, making the wiki smarter over time
- **Conversation forking** -- Branch a conversation at any turn to explore a different line of reasoning
- **Streaming** -- Token-by-token streaming via Server-Sent Events for responsive UI

## Knowledge Graph

Articles are interconnected through:

- **Concepts** -- Hierarchical topic taxonomy, auto-generated and LLM-rebuilt
- **Backlinks** -- Typed relationships between articles (references, extends, supersedes, contradicts)
- **Concept pages** -- Auto-generated articles that synthesize all sources tagged with a concept

## Wiki Health & Linting

A built-in linter audits the wiki for quality issues:

- **Contradiction detection** -- Finds conflicting claims across articles using batched LLM analysis
- **Orphan detection** -- Identifies articles with no backlinks
- **Health reports** -- Scored reports with actionable findings
- **Contradiction resolution** -- Mark contradictions as resolved with a note

## Authentication

Optional multi-user mode with OAuth2:

- Google and GitHub OAuth2 sign-in
- JWT sessions via HttpOnly BFF cookies
- Per-user data isolation (each user sees only their own sources, articles, and conversations)
- When disabled (default), WikiMind runs in single-user mode with no login required

## Real-Time Updates

WebSocket events push live updates to the UI:

- Compilation progress and completion
- Budget warnings and alerts
- Linter findings
- Job status changes
