# WikiMind — Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                             │
│         Desktop App (Electron) + Web App (React)                │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST + WebSocket (localhost:7842)
┌────────────────────────▼────────────────────────────────────────┐
│                      LOCAL GATEWAY                              │
│                  FastAPI (Python) daemon                        │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ Ingest      │  │ LLM Engine  │  │ Knowledge Store      │   │
│  │ Service     │  │ Orchestrator│  │ Manager              │   │
│  └─────────────┘  └─────────────┘  └──────────────────────┘   │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ Job Queue   │  │ Event Bus   │  │ Sync Engine          │   │
│  │ (ARQ)       │  │ (WebSocket) │  │                      │   │
│  └─────────────┘  └─────────────┘  └──────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
┌─────────▼──────┐ ┌─────▼──────┐ ┌───▼──────────────┐
│ Local Storage  │ │ LLM        │ │ Cloud Sync       │
│ .md files      │ │ Providers  │ │ (Fly.io + R2)    │
│ SQLite         │ │ Claude     │ │                  │
│ ChromaDB       │ │ OpenAI     │ │                  │
│                │ │ Gemini     │ │                  │
│                │ │ Ollama     │ │                  │
└────────────────┘ └────────────┘ └──────────────────┘
```

## Data Model

```mermaid
erDiagram
    Source {
        string id PK
        string source_type
        string source_url
        string title
        string author
        string status
        datetime ingested_at
        datetime compiled_at
        int token_count
        string file_path
    }

    Article {
        string id PK
        string slug UK
        string title
        string file_path
        string concept_ids
        string confidence
        float linter_score
        string summary
        string source_ids
        datetime created_at
        datetime updated_at
    }

    Concept {
        string id PK
        string name UK
        string parent_id FK
        int article_count
        string description
    }

    Backlink {
        string source_article_id FK
        string target_article_id FK
        string context
    }

    Query {
        string id PK
        string question
        string answer
        string confidence
        string source_article_ids
        bool filed_back
        string filed_article_id
        datetime created_at
    }

    Job {
        string id PK
        string job_type
        string status
        string source_id FK
        int priority
        datetime queued_at
        datetime started_at
        datetime completed_at
        string error
    }

    CostLog {
        string id PK
        string provider
        string model
        string task_type
        int input_tokens
        int output_tokens
        float cost_usd
        int latency_ms
        string job_id FK
        datetime created_at
    }

    Source ||--o{ Article : "compiled into"
    Article }o--o{ Backlink : "source"
    Article }o--o{ Backlink : "target"
    Concept ||--o{ Concept : "parent"
    Job ||--o{ CostLog : "generates"
```

## Ingest Pipeline

```mermaid
flowchart LR
    A["Raw Source\n(URL/PDF/Text/YouTube)"] --> B["Source Adapter"]
    B --> C["Normalizer\nStrip formatting\nExtract metadata"]
    C --> D["Chunker\nSemantic splitting\nPreserve headings"]
    D --> E["Embedder\nChromaDB vectors"]
    E --> F["Job Queue\nARQ"]
    F --> G["LLM Compiler"]
    G --> H["Wiki Article\n.md file"]
    H --> I["SQLite\nMetadata"]
    H --> J["Backlink\nExtraction"]
    J --> K["Knowledge\nGraph update"]
```

## LLM Provider Selection

```mermaid
flowchart TD
    A["LLM Request"] --> B{Preferred\nprovider?}
    B -- Yes --> C{Available\n& configured?}
    B -- No --> D["Use default\nfrom settings"]
    C -- Yes --> E["Call provider"]
    C -- No --> D
    D --> F{Available\n& configured?}
    F -- Yes --> E
    F -- No --> G{Fallback\nenabled?}
    G -- Yes --> H["Try next\nprovider"]
    G -- No --> I["Raise error"]
    H --> F
    E --> J{Success?}
    J -- Yes --> K["Log cost\nReturn response"]
    J -- No --> G
```

## Compilation Prompt Contract

Input: Raw source text + metadata
Output: Structured JSON →

```json
{
  "title": "Concise article title",
  "summary": "Two sentences. What and why it matters.",
  "key_claims": [
    {
      "claim": "Specific falsifiable claim",
      "confidence": "sourced | inferred | opinion",
      "quote": "Optional direct quote under 15 words"
    }
  ],
  "concepts": ["concept-a", "concept-b"],
  "backlink_suggestions": ["Related article title"],
  "open_questions": ["Gap this source raises"],
  "article_body": "Full markdown article 300+ words"
}
```

## File System Layout

```
~/.wikimind/
├── config/
│   └── settings.toml         # Non-sensitive settings
├── raw/                       # Original source files (immutable)
│   ├── {uuid}.pdf
│   ├── {uuid}.html
│   └── {uuid}.txt
├── wiki/                      # Compiled articles
│   ├── index.md               # Auto-maintained master index
│   ├── {concept}/
│   │   └── {slug}.md
│   └── _meta/
│       ├── backlinks.json
│       ├── concepts.json
│       └── health.json        # Latest linter report
└── db/
    ├── wikimind.db            # SQLite metadata
    └── chroma/                # ChromaDB embeddings
```

## WebSocket Event Reference

All events pushed from gateway → UI:

| Event | Payload | When |
|---|---|---|
| `connected` | `{message}` | On WebSocket connect |
| `job.progress` | `{job_id, pct, message}` | During any job |
| `compilation.complete` | `{article_slug, article_title}` | Source compiled |
| `compilation.failed` | `{source_id, error}` | Compilation error |
| `sync.complete` | `{pushed, pulled, conflicts}` | After cloud sync |
| `linter.alert` | `{type, articles}` | Linter finds issues |
| `keepalive` | — | Every 30s |

Client sends:

| Message | Payload | Purpose |
|---|---|---|
| `ping` | `{type: "ping"}` | Keepalive response |

## Performance Targets

| Metric | Target |
|---|---|
| Compilation latency (single source) | < 30s p95 |
| Q&A response time | < 5s p95 |
| Search latency | < 200ms |
| App cold start to ready | < 8s |
| Sync push (100 articles) | < 60s |
| Linter run (500 article wiki) | < 5 min |
| Gateway memory footprint | < 300MB resident |
