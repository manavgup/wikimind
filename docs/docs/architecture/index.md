# Architecture Overview

WikiMind is a personal LLM-powered knowledge OS. The backend is a local FastAPI daemon that ingests sources, compiles them into wiki articles via LLM, and answers questions against the wiki.

## System Diagram

```mermaid
graph TB
    subgraph Client["Client Layer"]
        Web["Web App<br/>(React + Vite)"]
        Desktop["Desktop App<br/>(Electron)"]
    end

    subgraph Gateway["Local Gateway (FastAPI)"]
        Ingest["Ingest<br/>Service"]
        Engine["LLM Engine<br/>Orchestrator"]
        Wiki["Wiki<br/>Service"]
        Query["Query<br/>Service"]
        Jobs["Job Queue<br/>(ARQ)"]
        WS["WebSocket<br/>Events"]
    end

    subgraph Providers["LLM Providers"]
        Claude["Anthropic<br/>Claude"]
        GPT["OpenAI<br/>GPT"]
        Gemini["Google<br/>Gemini"]
        Ollama["Ollama<br/>(Local)"]
    end

    subgraph Storage["Storage"]
        SQLite["SQLite /<br/>PostgreSQL"]
        Files["Markdown<br/>Files"]
        Raw["Raw Source<br/>Files"]
    end

    subgraph Sidecars["Sidecars"]
        Docling["docling-serve<br/>(PDF extraction)"]
        Redis["Redis<br/>(Job queue)"]
    end

    Web & Desktop -->|REST + WebSocket| Gateway
    Ingest --> Docling
    Engine --> Providers
    Jobs --> Redis
    Gateway --> Storage
```

## Request Flow

### Ingest -> Compile -> Query

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI Gateway
    participant Adapter as Source Adapter
    participant Queue as Job Queue
    participant Compiler as LLM Compiler
    participant Store as Storage

    User->>API: POST /ingest/url
    API->>Adapter: Extract text + metadata
    Adapter->>Store: Save raw source
    Adapter-->>API: Source (status: ingested)
    API->>Queue: Schedule compilation
    Queue->>Compiler: Compile document
    Compiler->>Store: Save wiki article
    Compiler-->>Queue: Article saved
    Queue-->>API: WebSocket: compilation.complete

    User->>API: POST /query
    API->>Store: Retrieve relevant articles
    API->>Compiler: LLM Q&A with context
    Compiler-->>API: Answer + citations
    API-->>User: QueryResult
```

## Module Structure

```
src/wikimind/
├── main.py              # FastAPI app + lifespan
├── config.py            # Pydantic BaseSettings
├── models.py            # SQLModel tables + Pydantic schemas
├── database.py          # Async session lifecycle
├── errors.py            # Domain error hierarchy
├── storage.py           # File storage abstraction
├── api/
│   ├── deps.py          # Shared dependencies (auth, session)
│   └── routes/
│       ├── ingest.py    # Source ingestion endpoints
│       ├── wiki.py      # Article browsing, graph, search
│       ├── query.py     # Q&A and conversations
│       ├── jobs.py      # Job management
│       ├── lint.py      # Wiki health audit
│       ├── settings.py  # LLM provider configuration
│       ├── auth.py      # OAuth2 authentication
│       ├── admin.py     # System diagnostics
│       └── ws.py        # WebSocket events
├── engine/
│   ├── compiler.py      # Source -> wiki article compiler
│   ├── qa_agent.py      # Q&A against the wiki
│   ├── llm_router.py    # Multi-provider LLM routing
│   ├── concept_compiler.py  # Concept page generation
│   ├── linter/          # Wiki health auditing
│   └── providers/       # Provider implementations
├── ingest/
│   ├── service.py       # Ingest orchestrator
│   └── adapters/        # URL, PDF, text, YouTube
├── services/            # Business logic layer
│   ├── ingest.py        # Ingest service (route handler delegate)
│   ├── compiler.py      # Background compilation
│   ├── query.py         # Q&A service
│   ├── wiki.py          # Wiki browsing
│   ├── taxonomy.py      # Concept taxonomy management
│   ├── linter.py        # Linter orchestration
│   └── embedding.py     # Semantic search (planned)
├── jobs/                # ARQ worker jobs
└── middleware/           # Request pipeline
    ├── auth.py          # JWT/cookie auth
    ├── correlation.py   # Request ID tracking
    ├── request_logging.py
    ├── security_headers.py
    └── error_handling.py
```

## Data Model

```mermaid
erDiagram
    Source {
        string id PK
        string source_type
        string source_url
        string title
        string status
        datetime ingested_at
        datetime compiled_at
        string user_id
    }

    Article {
        string id PK
        string slug UK
        string title
        string file_path
        string confidence
        string summary
        string source_ids
        string concept_ids
        string page_type
        string provider
        string user_id
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
        string relation_type
        string context
        string resolution
    }

    Conversation {
        string id PK
        string title
        string filed_article_id FK
        string parent_conversation_id FK
        string user_id
    }

    Query {
        string id PK
        string question
        string answer
        string confidence
        int turn_index
        string conversation_id FK
        string user_id
    }

    CostLog {
        string id PK
        string provider
        string model
        string task_type
        float cost_usd
        int input_tokens
        int output_tokens
    }

    Source ||--o{ Article : "compiled into"
    Article }o--o{ Backlink : "source/target"
    Concept ||--o{ Concept : "parent"
    Conversation ||--o{ Query : "contains"
    Conversation ||--o| Article : "filed as"
```

## Key Design Decisions

The [Architecture Decision Records](adr/index.md) document every significant design choice. Key ones include:

- **ADR-001**: FastAPI + async SQLite for local-first daemon
- **ADR-003**: Multi-provider LLM router with fallback
- **ADR-004**: Plain markdown files + SQLite metadata
- **ADR-007**: Structured JSON prompt contract between compiler and LLM
- **ADR-009**: Decoupled ingest and compilation
- **ADR-011**: Conversational Q&A thread model with file-back
- **ADR-021**: PostgreSQL compatibility for production
- **ADR-022**: Multi-user authentication via OAuth2

## Performance Targets

| Metric | Target |
|---|---|
| Compilation latency (single source) | < 30s p95 |
| Q&A response time | < 5s p95 |
| Search latency | < 200ms |
| App cold start to ready | < 8s |
| Gateway memory footprint | < 300MB resident |
