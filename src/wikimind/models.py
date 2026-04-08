"""Domain models — SQLModel tables persisted to SQLite and Pydantic schemas for the pipeline.

Enums define the vocabulary (source types, statuses, providers). SQLModel tables
store sources, articles, concepts, backlinks, queries, jobs, and cost logs.
Pydantic models carry data through the ingest → compile → query pipeline.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlmodel import Field, Relationship, SQLModel

from wikimind._datetime import utcnow_naive

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceType(StrEnum):
    """Type of ingested source."""

    URL = "url"
    PDF = "pdf"
    YOUTUBE = "youtube"
    AUDIO = "audio"
    TEXT = "text"
    RSS = "rss"
    EMAIL = "email"
    OBSIDIAN = "obsidian"


class IngestStatus(StrEnum):
    """Status of source ingestion."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPILED = "compiled"
    FAILED = "failed"


class ConfidenceLevel(StrEnum):
    """Confidence level for claims."""

    SOURCED = "sourced"  # Claim directly from source
    MIXED = "mixed"  # Mix of source + inference
    INFERRED = "inferred"  # LLM synthesis
    OPINION = "opinion"  # Author's stated opinion


class JobType(StrEnum):
    """Type of async job."""

    COMPILE_SOURCE = "compile_source"
    LINT_WIKI = "lint_wiki"
    REINDEX = "reindex"
    EMBED_CHUNKS = "embed_chunks"
    SYNC_PUSH = "sync_push"
    SYNC_PULL = "sync_pull"


class JobStatus(StrEnum):
    """Status of an async job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class Provider(StrEnum):
    """LLM provider identifier."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    OLLAMA = "ollama"
    MOCK = "mock"


class TaskType(StrEnum):
    """Type of LLM task."""

    COMPILE = "compile"
    QA = "qa"
    LINT = "lint"
    INDEX = "index"


# ---------------------------------------------------------------------------
# SQLModel Tables (persisted to SQLite)
# ---------------------------------------------------------------------------


class Source(SQLModel, table=True):
    """Raw ingested source — before compilation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_type: SourceType
    source_url: str | None = None
    title: str | None = None
    author: str | None = None
    published_date: date | None = None
    status: IngestStatus = IngestStatus.PENDING
    ingested_at: datetime = Field(default_factory=utcnow_naive)
    compiled_at: datetime | None = None
    token_count: int | None = None
    error_message: str | None = None
    file_path: str | None = None  # Path in raw/ directory
    # SHA-256 hex digest of the raw payload (issue #67). Used by the ingest
    # layer to detect duplicates: re-ingesting the same content returns the
    # existing source instead of creating a second row.
    content_hash: str | None = Field(default=None, index=True)


class Article(SQLModel, table=True):
    """Compiled wiki article metadata. Content lives in .md file."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    slug: str = Field(unique=True, index=True)
    title: str
    file_path: str  # Path to .md file in wiki/
    concept_ids: str | None = None  # JSON array of concept IDs
    confidence: ConfidenceLevel | None = None
    linter_score: float | None = None
    summary: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    source_ids: str | None = None  # JSON array of source IDs
    # Which LLM provider compiled this article (issue #67). Recompiling the
    # same source with the same provider replaces this article in place;
    # different providers stack as separate articles for comparison.
    provider: Provider | None = None

    # ORM relationships — used for eager-loading backlinks
    backlinks_out: list["Backlink"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Backlink.source_article_id]", "lazy": "selectin"},
    )
    backlinks_in: list["Backlink"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Backlink.target_article_id]", "lazy": "selectin"},
    )


class Concept(SQLModel, table=True):
    """Auto-generated concept taxonomy node."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True, index=True)
    parent_id: str | None = Field(default=None, foreign_key="concept.id")
    article_count: int = 0
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class Backlink(SQLModel, table=True):
    """Directed link between two wiki articles."""

    source_article_id: str = Field(foreign_key="article.id", primary_key=True)
    target_article_id: str = Field(foreign_key="article.id", primary_key=True)
    context: str | None = None  # Sentence where link appears


class Conversation(SQLModel, table=True):
    """A conversation thread of one or more Q&A turns.

    Conversations group related Q&A turns that share LLM context. The
    first turn's question becomes the conversation's title (truncated).
    Filing a conversation back to the wiki is a per-conversation action,
    not per-turn — see ADR-011.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")


class Query(SQLModel, table=True):
    """Q&A history entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    question: str
    answer: str
    confidence: str | None = None
    source_article_ids: str | None = None  # JSON array
    related_article_ids: str | None = None  # JSON array
    filed_back: bool = False
    filed_article_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    # Conversation grouping (ADR-011). Nullable in the schema because the
    # repo's lightweight migration helper cannot add NOT NULL columns to
    # existing tables, but ALWAYS populated by app code — every Query
    # belongs to exactly one Conversation. Read it as "non-null in practice".
    conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    turn_index: int = 0  # 0 for first turn, 1 for second, etc.


class Job(SQLModel, table=True):
    """Async job record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    job_type: JobType
    status: JobStatus = JobStatus.QUEUED
    source_id: str | None = None
    article_id: str | None = None
    priority: int = 5
    queued_at: datetime = Field(default_factory=utcnow_naive)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_summary: str | None = None


class CostLog(SQLModel, table=True):
    """LLM API cost tracking."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    provider: Provider
    model: str
    task_type: TaskType
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    job_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class SyncLog(SQLModel, table=True):
    """Cloud sync history."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    direction: str  # push | pull
    articles_pushed: int = 0
    articles_pulled: int = 0
    conflicts: int = 0
    started_at: datetime = Field(default_factory=utcnow_naive)
    completed_at: datetime | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Pydantic Models (not persisted — used for processing pipeline)
# ---------------------------------------------------------------------------


class DocumentChunk(BaseModel):
    """A chunk of a normalized document."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    content: str
    heading_path: list[str] = []  # e.g. ["Introduction", "Key Claims"]
    embedding_id: str | None = None
    token_count: int = 0
    chunk_index: int = 0


class NormalizedDocument(BaseModel):
    """Normalized document ready for compilation."""

    raw_source_id: str
    clean_text: str
    title: str
    author: str | None = None
    published_date: date | None = None
    estimated_tokens: int = 0
    language: str = "en"
    chunks: list[DocumentChunk] = []


class CompiledClaim(BaseModel):
    """A single compiled claim from a source."""

    claim: str
    confidence: ConfidenceLevel
    quote: str | None = None  # Direct quote < 15 words if critical


class CompilationResult(BaseModel):
    """Output from LLM compiler for a single source."""

    title: str
    summary: str
    key_claims: list[CompiledClaim]
    concepts: list[str]
    backlink_suggestions: list[str]
    open_questions: list[str]
    article_body: str  # Full markdown


class QueryResult(BaseModel):
    """Output from Q&A agent."""

    answer: str
    confidence: str  # high | medium | low
    sources: list[str]  # Article titles
    related_articles: list[str]
    new_article_suggested: str | None = None
    follow_up_questions: list[str] = []


class LinterContradiction(BaseModel):
    """A contradiction found by the linter."""

    claim_a: str
    claim_b: str
    articles: list[str]


class LinterResult(BaseModel):
    """Output from wiki linter."""

    contradictions: list[LinterContradiction] = []
    orphaned_articles: list[str] = []
    stale_articles: list[str] = []
    gap_suggestions: list[str] = []
    coverage_scores: dict[str, float] = {}  # concept → 0.0-1.0


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------


class IngestURLRequest(BaseModel):
    """Request to ingest a URL."""

    url: str
    auto_compile: bool = True


class IngestTextRequest(BaseModel):
    """Request to ingest raw text."""

    content: str
    title: str | None = None
    auto_compile: bool = True


class QueryRequest(BaseModel):
    """Request to query the wiki."""

    question: str
    file_back: bool = False  # Auto-save answer to wiki
    conversation_id: str | None = None  # None means start a new conversation


class SourceResponse(BaseModel):
    """Provenance view of a raw ingested source exposed via the API.

    Trimmed view of :class:`Source` suitable for embedding in article and
    Q&A responses so callers can trace claims back to their origin
    (URL, PDF filename, upload date, etc.).
    """

    id: str
    source_type: SourceType
    title: str | None
    source_url: str | None
    ingested_at: datetime


class ArticleSourceSummary(BaseModel):
    """Minimal source descriptor returned with listing/search endpoints.

    A lightweight summary used when the full :class:`SourceResponse` is
    overkill — e.g. article list and search result payloads.
    """

    id: str
    source_type: SourceType
    title: str | None


class ArticleResponse(BaseModel):
    """Full article response with content, backlinks, and source provenance."""

    id: str
    slug: str
    title: str
    summary: str | None
    confidence: ConfidenceLevel | None
    linter_score: float | None
    concepts: list[str] = []
    backlinks_in: list[str] = []
    backlinks_out: list[str] = []
    content: str  # Full .md content
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime


class ArticleSummaryResponse(BaseModel):
    """Summary article response for list and search endpoints.

    Includes a lightweight list of sources so that callers can surface
    provenance directly in search/listing views without fetching the full
    article content.
    """

    id: str
    slug: str
    title: str
    summary: str | None
    confidence: ConfidenceLevel | None
    linter_score: float | None
    sources: list[ArticleSourceSummary] = []
    created_at: datetime
    updated_at: datetime


class CitationArticleRef(BaseModel):
    """Minimal reference to an article used inside a :class:`CitationResponse`."""

    slug: str
    title: str


class CitationResponse(BaseModel):
    """A single Q&A citation: an article plus the sources it was compiled from."""

    article: CitationArticleRef
    sources: list[SourceResponse] = []


class QueryResponse(BaseModel):
    """Q&A response enriched with a full Answer → Article → Source citation chain.

    Mirrors the persisted :class:`Query` record fields while adding a
    resolved ``citations`` list so clients can see which articles were
    used and which original sources those articles came from.
    """

    id: str
    question: str
    answer: str
    confidence: str | None
    source_article_ids: str | None
    related_article_ids: str | None
    filed_back: bool
    filed_article_id: str | None
    created_at: datetime
    conversation_id: str | None = None
    turn_index: int = 0
    citations: list[CitationResponse] = []


class ConversationResponse(BaseModel):
    """Conversation metadata exposed via API."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    filed_article_id: str | None = None


class ConversationSummary(ConversationResponse):
    """Conversation summary for the history sidebar — adds turn count."""

    turn_count: int


class ConversationDetail(BaseModel):
    """Full conversation thread with all queries ordered by turn_index."""

    conversation: ConversationResponse
    queries: list[QueryResponse]


class AskResponse(BaseModel):
    """Response shape for POST /query — wraps both the new query and its parent conversation."""

    query: QueryResponse
    conversation: ConversationResponse


class GraphNode(BaseModel):
    """A node in the knowledge graph."""

    id: str
    label: str
    concept_cluster: str | None
    connection_count: int
    confidence: ConfidenceLevel | None


class GraphEdge(BaseModel):
    """An edge in the knowledge graph."""

    source: str
    target: str
    context: str | None


class GraphResponse(BaseModel):
    """Full knowledge graph response."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HealthReport(BaseModel):
    """Wiki health report from linter."""

    generated_at: datetime
    total_articles: int
    total_sources: int
    coverage_scores: dict[str, float]
    contradictions: list[LinterContradiction]
    orphaned_articles: list[str]
    stale_articles: list[str]
    gap_suggestions: list[str]
    cost_this_month_usd: float


class LLMProviderStatus(BaseModel):
    """Status of an LLM provider."""

    provider: Provider
    enabled: bool
    configured: bool  # API key present
    model: str
    cost_this_month_usd: float


class CompletionRequest(BaseModel):
    """Request for LLM completion."""

    system: str
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    temperature: float = 0.3
    response_format: str = "json"  # text | json
    task_type: TaskType = TaskType.COMPILE
    preferred_provider: Provider | None = None


class CompletionResponse(BaseModel):
    """Response from LLM completion."""

    content: str
    provider_used: Provider
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
