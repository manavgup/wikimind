# Quick Start

Get WikiMind running locally in 5 minutes.

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Node.js 20+** (for the React frontend, optional)
- An LLM API key (Anthropic, OpenAI, Google, OpenAI-compatible, or a local Ollama instance)

## 1. Clone and set up

```bash
git clone https://github.com/manavgup/wikimind.git
cd wikimind

# Create virtual environment and install dependencies
make venv
make install-dev

# Verify everything is installed correctly
make check-env
```

## 2. Configure an LLM provider

Copy the example environment file and add at least one API key:

```bash
cp .env.example .env
```

Edit `.env` and set one of:

```bash
# Pick ONE -- the provider auto-enables when a key is detected
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
# or
GOOGLE_API_KEY=...
```

That is all you need. WikiMind auto-detects which providers have keys configured and enables them automatically.

!!! tip "Using OpenRouter or another OpenAI-compatible endpoint"
    Configure the separate `openai_compatible` provider:
    ```bash
    OPENAI_COMPATIBLE_API_KEY=sk-or-...
    WIKIMIND_LLM__OPENAI_COMPATIBLE__BASE_URL=https://openrouter.ai/api/v1
    WIKIMIND_LLM__OPENAI_COMPATIBLE__MODEL=openai/gpt-4o-mini
    WIKIMIND_LLM__DEFAULT_PROVIDER=openai_compatible
    ```

!!! tip "Using Ollama (no API key needed)"
    If you have [Ollama](https://ollama.ai) running locally, enable it explicitly:
    ```bash
    WIKIMIND_LLM__OLLAMA__ENABLED=true
    WIKIMIND_LLM__DEFAULT_PROVIDER=ollama
    ```

## 3. Start the gateway

```bash
make dev
```

The FastAPI server starts on `http://localhost:7842`. You can verify it is running:

```bash
curl http://localhost:7842/health
# {"status": "ok", "version": "0.1.0"}
```

## 4. (Optional) Start the React UI

In a separate terminal:

```bash
cd apps/web
npm install
npm run dev
# Opens http://localhost:5173
```

## 5. Ingest your first source

=== "Via the API"

    ```bash
    # Ingest a web article
    curl -X POST http://localhost:7842/ingest/url \
      -H "Content-Type: application/json" \
      -d '{"url": "https://example.com/interesting-article"}'

    # Ingest a PDF
    curl -X POST http://localhost:7842/ingest/pdf \
      -F "file=@paper.pdf"

    # Ingest raw text
    curl -X POST http://localhost:7842/ingest/text \
      -H "Content-Type: application/json" \
      -d '{"content": "Your text here...", "title": "My Notes"}'
    ```

=== "Via the UI"

    Open `http://localhost:5173` and use the Inbox view to paste URLs, upload PDFs, or enter text directly.

## 6. Ask a question

Once your source has been compiled (watch the terminal for "Article saved"):

```bash
curl -X POST http://localhost:7842/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the key claims from the article I just ingested?"}'
```

The response includes the answer, confidence level, cited sources, and follow-up questions.

## Next steps

- [Ingesting Sources](../using/ingestion.md) -- All source types and options
- [Configuration](../configuration/settings.md) -- Full settings reference
- [Docker deployment](../deployment/docker.md) -- Run with Docker Compose
- [Architecture overview](../architecture/index.md) -- How it all fits together
