# WikiMind

> You never write the wiki. You feed it. Every question makes it smarter.

WikiMind is a hybrid local/cloud personal knowledge OS. Feed it anything you read — articles, PDFs, YouTube videos, podcasts, papers. It compiles them into a structured, interconnected wiki using LLMs. Ask questions. The answers file back in. Your knowledge compounds.

## What It Is

- **Not** a note-taking app (you never write)
- **Not** a chatbot (it builds something persistent)
- **Not** a RAG tool (the wiki is the product, not a retrieval layer)

It is the synthesis layer that sits above everything you consume.

## How It Works

```
Feed → Compile → Query → Answer files back → Wiki gets smarter → Repeat
```

## Architecture

```
apps/
  desktop/        Electron shell (Mac, Windows, Linux)
  web/            React UI (shared with desktop)
  extension/      Chrome/Firefox browser extension

packages/
  ui/             Shared component library
  types/          Shared TypeScript types

services/
  gateway/        Local FastAPI daemon (core engine)
  sync/           Cloud sync service
  llm_router/     LLM provider abstraction

docs/             Architecture docs, specs, diagrams
```

## Quick Start

```bash
# Install Python dependencies
cd services/gateway
pip install -r requirements.txt

# Start local gateway
uvicorn wikimind.main:app --port 7842 --reload

# Install frontend dependencies
cd apps/web
npm install
npm run dev
```

## Tech Stack

| Layer | Technology |
|---|---|
| Local daemon | Python 3.11 / FastAPI |
| Job queue | ARQ + fakeredis |
| Vector store | ChromaDB |
| Relational store | SQLite / SQLModel |
| File storage | Plain `.md` files |
| Desktop shell | Electron |
| Frontend | React + TypeScript |
| Graph viz | D3.js / react-force-graph |
| Cloud sync | FastAPI on Fly.io |
| Cloud storage | S3-compatible (R2) |
| Auth | Clerk |

## LLM Support

WikiMind is LLM-agnostic. Configure any provider in `settings.toml`:

- Anthropic Claude (default)
- OpenAI GPT-4o
- Google Gemini
- Local models via Ollama (free, fully private)

## Status

🚧 **Phase 1 — Active Development**

See [docs/ROADMAP.md](docs/ROADMAP.md) for build sequence.

## License

MIT
