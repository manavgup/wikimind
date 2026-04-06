# WikiMind — Roadmap

## Phase 1 — Working Core (Target: 6 weeks)

**Goal:** User ingests 10 sources, wiki articles appear, can read them.

- [x] FastAPI gateway skeleton
- [x] SQLite schema (SQLModel)
- [x] Core data models
- [x] LLM router (multi-provider)
- [x] Compiler (source → wiki article)
- [x] Q&A agent with file-back
- [x] URL ingest adapter (trafilatura)
- [x] PDF ingest adapter (pymupdf)
- [x] YouTube ingest adapter
- [x] Text ingest adapter
- [x] Job queue (ARQ + fakeredis)
- [x] WebSocket event streaming
- [x] All API routes
- [x] OpenAPI spec
- [ ] React UI — Inbox view
- [ ] React UI — Wiki Explorer
- [ ] React UI — Ask view
- [ ] Electron shell
- [ ] End-to-end test: ingest → compile → read

## Phase 2 — Query Loop (Target: +3 weeks)

**Goal:** User asks a question, gets an answer with sources, saves it as a wiki article.

- [ ] Semantic search via ChromaDB
- [ ] Embedder (sentence-transformers)
- [ ] Ask view with conversation thread
- [ ] File-back UI button
- [ ] Query history view

## Phase 3 — Knowledge Graph (Target: +3 weeks)

**Goal:** User sees their knowledge as a connected graph.

- [ ] Backlink extraction from compiled articles
- [ ] Concept taxonomy auto-generation
- [ ] Graph view (react-force-graph)
- [ ] Concept tree in Wiki Explorer sidebar
- [ ] Orphan detection overlay

## Phase 4 — Health + Linter (Target: +2 weeks)

**Goal:** Wiki self-reports its own weaknesses.

- [ ] Linter prompt + scheduled ARQ job
- [ ] Health dashboard view
- [ ] Contradiction alert cards
- [ ] Gap suggestion list
- [ ] Coverage score gauges

## Phase 5 — Multi-provider + Sync (Target: +3 weeks)

**Goal:** Switch LLM providers without changing anything. Wiki syncs to second device.

- [ ] OpenAI adapter (complete)
- [ ] Gemini adapter
- [ ] Ollama adapter (local, free)
- [ ] Cloud sync service (Fly.io)
- [ ] S3-compatible sync engine (Cloudflare R2)
- [ ] Settings UI (providers, sync, cost)
- [ ] Cross-device test

## Phase 6 — Polish + Extension (Target: +2 weeks)

**Goal:** Ship something people actually use daily.

- [ ] Browser extension (Chrome + Firefox)
- [ ] RSS auto-ingest
- [ ] Output layer: PDF export, LinkedIn draft, slide deck
- [ ] Electron auto-update
- [ ] Mac/Windows/Linux installers
- [ ] Onboarding flow (first-run wizard)

## Future (Post-v1)

- Audio/podcast transcription (Whisper local)
- Email forwarding address for newsletters
- Obsidian vault sync
- Public wiki publishing (share topic clusters)
- Team wikis (collaborative ingest, shared knowledge)
- Enterprise: private deployment, SSO, audit trails, on-prem LLM
