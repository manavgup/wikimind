"""Domain models — SQLModel tables persisted to SQLite and Pydantic schemas for the pipeline.

Enums define the vocabulary (source types, statuses, providers). SQLModel tables
store sources, articles, concepts, backlinks, queries, jobs, and cost logs.
Pydantic models carry data through the ingest → compile → query pipeline.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, computed_field
from sqlalchemy import Column, String, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from wikimind._datetime import utcnow_naive

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PageType(StrEnum):
    """Type of wiki page — determines compilation pipeline and validation rules."""

    SOURCE = "source"
    CONCEPT = "concept"
    ANSWER = "answer"
    INDEX = "index"
    META = "meta"


class RelationType(StrEnum):
    """Semantic relationship between two linked articles."""

    REFERENCES = "references"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    SUPERSEDES = "supersedes"
    SYNTHESIZES = "synthesizes"
    RELATED_TO = "related_to"


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
    SWEEP_WIKILINKS = "sweep_wikilinks"
    REINDEX = "reindex"
    EMBED_CHUNKS = "embed_chunks"
    RECOMPILE_ARTICLE = "recompile_article"
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
    OPENAI_COMPATIBLE = "openai_compatible"
    GOOGLE = "google"
    OLLAMA = "ollama"
    MOCK = "mock"


class TaskType(StrEnum):
    """Type of LLM task."""

    COMPILE = "compile"
    QA = "qa"
    LINT = "lint"
    INDEX = "index"
    INGEST = "ingest"
    EXPORT = "export"


# ---------------------------------------------------------------------------
# SQLModel Tables (persisted to SQLite)
# ---------------------------------------------------------------------------


class MigrationHistory(SQLModel, table=True):
    """Tracks which data migrations have been applied.

    Each row records a unique migration version string and when it ran.
    init_db() checks this table to skip already-applied migrations,
    turning O(n) startup scans into a constant-time version check.
    """

    version: str = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=utcnow_naive)


class User(SQLModel, table=True):
    """Authenticated user account."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str | None = None
    avatar_url: str | None = None
    auth_provider: str  # "google" | "github"
    auth_provider_id: str  # provider's unique user ID
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class Source(SQLModel, table=True):
    """Raw ingested source — before compilation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_original(self) -> bool:
        """Whether the original document (PDF, HTML) exists alongside the .txt."""
        if not self.file_path:
            return False
        from wikimind.storage import find_original_sibling, resolve_raw_path  # noqa: PLC0415

        txt_path = resolve_raw_path(self.file_path, user_id=self.user_id)  # type: ignore[arg-type]  # #393
        return find_original_sibling(txt_path) is not None


class Article(SQLModel, table=True):
    """Compiled wiki article metadata. Content lives in .md file."""

    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_article_user_slug"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    slug: str = Field(index=True)
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
    page_type: PageType = Field(
        default=PageType.SOURCE,
        sa_column=Column(String, default=PageType.SOURCE),
    )

    # ORM relationships — used for eager-loading backlinks
    backlinks_out: list["Backlink"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Backlink.source_article_id]", "lazy": "selectin"},
    )
    backlinks_in: list["Backlink"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Backlink.target_article_id]", "lazy": "selectin"},
    )


class ArticleConcept(SQLModel, table=True):
    """Join table linking articles to concept names.

    Replaces the JSON-array ``Article.concept_ids`` column with a proper
    many-to-many relationship so queries like "articles tagged with concept X"
    can use an indexed join instead of a full table scan + JSON parse.
    """

    article_id: str = Field(foreign_key="article.id", primary_key=True)
    concept_name: str = Field(primary_key=True, index=True)


class ArticleSource(SQLModel, table=True):
    """Join table linking articles to source IDs.

    Replaces the JSON-array ``Article.source_ids`` column with a proper
    many-to-many relationship so lookups like "which article was compiled
    from source X" can use an indexed join instead of a full table scan.
    """

    article_id: str = Field(foreign_key="article.id", primary_key=True)
    source_id: str = Field(foreign_key="source.id", primary_key=True, index=True)


class ConceptKindDef(SQLModel, table=True):
    """Registry of concept kinds (Type Object pattern)."""

    name: str = Field(primary_key=True)
    prompt_template_key: str
    required_sections: str  # JSON array
    linter_rules: str  # JSON array
    description: str | None = None


class Concept(SQLModel, table=True):
    """Auto-generated concept taxonomy node."""

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_concept_user_name"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    name: str = Field(index=True)
    parent_id: str | None = Field(default=None, foreign_key="concept.id")
    article_count: int = 0
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    concept_kind: str = "topic"


class Backlink(SQLModel, table=True):
    """Directed link between two wiki articles."""

    source_article_id: str = Field(foreign_key="article.id", primary_key=True)
    target_article_id: str = Field(foreign_key="article.id", primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    context: str | None = None  # Sentence where link appears
    relation_type: str = Field(default=RelationType.REFERENCES)
    resolution: str | None = None
    resolution_note: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class Conversation(SQLModel, table=True):
    """A conversation thread of one or more Q&A turns.

    Conversations group related Q&A turns that share LLM context. The
    first turn's question becomes the conversation's title (truncated).
    Filing a conversation back to the wiki is a per-conversation action,
    not per-turn — see ADR-011.

    Branching: when a user edits a prior turn, a new Conversation is
    created that shares turns 0..N-1 with the parent by reference.
    The original branch is preserved immutably.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")
    parent_conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    forked_at_turn_index: int | None = None


class Query(SQLModel, table=True):
    """Q&A history entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
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
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
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
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
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
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    direction: str  # push | pull
    articles_pushed: int = 0
    articles_pulled: int = 0
    conflicts: int = 0
    started_at: datetime = Field(default_factory=utcnow_naive)
    completed_at: datetime | None = None
    error: str | None = None


class UserApiKey(SQLModel, table=True):
    """Encrypted user-provided API key for an LLM provider (BYOK).

    Each row stores a Fernet-encrypted API key with a per-row salt.
    The encryption key is derived from ``JWT_SECRET_KEY + salt`` via
    PBKDF2-HMAC-SHA256.  See ADR-026.
    """

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_userapikey_user_provider"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: Provider
    encrypted_key: str  # Fernet-encrypted API key (base64)
    salt: str  # Per-row salt (hex-encoded)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class UserPreference(SQLModel, table=True):
    """Lightweight key-value store for runtime settings overrides.

    Precedence: DB row wins if it exists, otherwise falls back to .env defaults.
    """

    key: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    value: str
    updated_at: datetime = Field(default_factory=utcnow_naive)


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
    # System-controlled fields — overwritten by Python after LLM response
    page_type: PageType = PageType.SOURCE
    compiled: datetime | None = None
    provider: Provider | None = None


class TypedBacklinkSuggestion(BaseModel):
    """A backlink suggestion with semantic relationship type."""

    target: str
    relation_type: RelationType = RelationType.REFERENCES


class SourceCompilationResult(CompilationResult):
    """Compilation result for source pages."""

    page_type: PageType = PageType.SOURCE


class ConceptCompilationResult(BaseModel):
    """Compilation result for concept pages."""

    title: str
    overview: str
    key_themes: list[str]
    consensus_conflicts: str
    open_questions: list[str]
    timeline: str
    sources_summary: str
    article_body: str  # Full markdown
    related_concepts: list[str] = []
    page_type: PageType = PageType.CONCEPT


class AnswerCompilationResult(BaseModel):
    """Compilation result for answer pages."""

    title: str
    question: str
    answer: str
    sources_cited: list[str]
    concepts: list[str]
    article_body: str  # Full markdown
    page_type: PageType = PageType.ANSWER


class SourceFrontmatter(BaseModel):
    """Validates frontmatter for source-type wiki pages."""

    page_type: PageType = PageType.SOURCE
    title: str
    slug: str
    source_id: str
    source_type: SourceType
    source_url: str | None = None
    compiled: datetime
    concepts: list[str] = []
    confidence: ConfidenceLevel | None = None
    provider: Provider | None = None


class ConceptFrontmatter(BaseModel):
    """Validates frontmatter for concept-type wiki pages."""

    page_type: PageType = PageType.CONCEPT
    title: str
    slug: str
    concept_id: str
    concept_kind: str = "topic"
    synthesized_from: list[str] = []
    source_count: int = 0
    last_synthesized: datetime | None = None
    confidence: ConfidenceLevel | None = None
    provider: Provider | None = None


class AnswerFrontmatter(BaseModel):
    """Validates frontmatter for answer-type wiki pages."""

    page_type: PageType = PageType.ANSWER
    title: str
    slug: str
    conversation_id: str
    turn_indices: list[int] = []
    filed_at: datetime | None = None
    concepts: list[str] = []
    confidence: ConfidenceLevel | None = None


class IndexFrontmatter(BaseModel):
    """Validates frontmatter for index-type wiki pages."""

    page_type: PageType = PageType.INDEX
    title: str
    slug: str
    scope: str
    concept_id: str | None = None
    generated: datetime | None = None


class MetaFrontmatter(BaseModel):
    """Validates frontmatter for meta-type wiki pages."""

    page_type: PageType = PageType.META
    title: str
    slug: str
    generated: datetime | None = None


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
# Lint Report + Per-Kind Finding Tables
# ---------------------------------------------------------------------------


class LintSeverity(StrEnum):
    """Severity level for a lint finding."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LintFindingKind(StrEnum):
    """Kind of lint finding — maps 1:1 to a detection function AND a table.

    Used as the content_hash prefix (so dismiss state is keyed by kind + content)
    and as the discriminator field in the frontend API response union.
    """

    CONTRADICTION = "contradiction"
    ORPHAN = "orphan"
    STRUCTURAL = "structural"


class LintReportStatus(StrEnum):
    """Lifecycle of a lint report."""

    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class LintReport(SQLModel, table=True):
    """One run of the linter. All findings from a run FK back to this row via report_id."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    generated_at: datetime = Field(default_factory=utcnow_naive, index=True)
    completed_at: datetime | None = None
    status: LintReportStatus = LintReportStatus.IN_PROGRESS
    article_count: int = 0
    total_findings: int = 0
    contradictions_count: int = 0
    orphans_count: int = 0
    structural_count: int = 0
    checked_articles: int | None = None
    missing_pages_count: int = 0
    dismissed_count: int = 0
    total_pairs: int = 0
    checked_pairs: int = 0
    error_message: str | None = None
    job_id: str | None = Field(default=None, foreign_key="job.id", index=True)


class _LintFindingBase(SQLModel):
    """Fields shared across every per-kind finding table. NOT a table itself."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    report_id: str = Field(foreign_key="lintreport.id", index=True)
    severity: LintSeverity = LintSeverity.WARN
    description: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    dismissed: bool = False
    dismissed_at: datetime | None = None
    content_hash: str = Field(index=True)


class ContradictionFinding(_LintFindingBase, table=True):
    """A contradiction between key claims of two articles that share a concept."""

    kind: LintFindingKind = Field(default=LintFindingKind.CONTRADICTION)
    article_a_id: str = Field(foreign_key="article.id", index=True)
    article_b_id: str = Field(foreign_key="article.id", index=True)
    article_a_claim: str
    article_b_claim: str
    llm_confidence: str  # "high" | "medium" | "low"
    shared_concept_id: str | None = Field(default=None, foreign_key="concept.id", index=True)


class OrphanFinding(_LintFindingBase, table=True):
    """An article with zero inbound AND zero outbound backlinks."""

    kind: LintFindingKind = Field(default=LintFindingKind.ORPHAN)
    article_id: str = Field(foreign_key="article.id", index=True)
    article_title: str


class StructuralFinding(_LintFindingBase, table=True):
    """A structural integrity violation detected by the backlink enforcer."""

    kind: LintFindingKind = Field(default=LintFindingKind.STRUCTURAL)
    article_id: str = Field(foreign_key="article.id", index=True)
    violation_type: str  # source_no_concepts | concept_insufficient_synthesizes | missing_inverse_link
    auto_repaired: bool = False
    detail: str = ""


class DismissedFinding(SQLModel, table=True):
    """Cross-run dismiss record — keyed by content hash."""

    content_hash: str = Field(primary_key=True)
    kind: LintFindingKind
    dismissed_at: datetime = Field(default_factory=utcnow_naive)
    reason: str | None = None


class LintReportDetail(BaseModel):
    """API response shape for a single report with all findings."""

    report: LintReport
    contradictions: list[ContradictionFinding]
    orphans: list[OrphanFinding]
    resolutions: dict[str, str] = {}  # "article_a_id|article_b_id" → resolution
    structurals: list[StructuralFinding] = []


class LintPairCache(SQLModel, table=True):
    """Cache of LLM contradiction check results for article pairs.

    Keyed by sorted article pair IDs. Invalidated when either article's
    updated_at changes.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_a_id: str = Field(index=True)
    article_b_id: str = Field(index=True)
    article_a_updated_at: str
    article_b_updated_at: str
    result_json: str  # JSON list of contradiction dicts
    checked_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------


class ContradictionResolution(StrEnum):
    """Valid resolution values for a contradiction between two articles."""

    SOURCE_A_WINS = "source_a_wins"
    SOURCE_B_WINS = "source_b_wins"
    BOTH_VALID = "both_valid"
    SUPERSEDED = "superseded"


class ResolveContradictionRequest(BaseModel):
    """Request to resolve a contradiction between two articles."""

    resolution: str
    resolution_note: str | None = None


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


class ForkRequest(BaseModel):
    """Request to fork a conversation at a specific turn with a new question."""

    turn_index: int
    new_question: str


class TurnSelection(BaseModel):
    """A selection of specific turns from a single conversation."""

    conversation_id: str
    turn_indices: list[int]


class FileBackSelectionRequest(BaseModel):
    """Request to file back selected turns from one or more conversations."""

    selections: list[TurnSelection]
    title: str | None = None


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


class BacklinkEntry(BaseModel):
    """A backlink entry with human-readable metadata for the frontend."""

    id: str
    title: str
    slug: str
    relation_type: RelationType | None = None
    resolution: str | None = None


class ArticleResponse(BaseModel):
    """Full article response with content, backlinks, and source provenance."""

    id: str
    slug: str
    title: str
    summary: str | None
    confidence: ConfidenceLevel | None
    linter_score: float | None
    concepts: list[str] = []
    backlinks_in: list[BacklinkEntry] = []
    backlinks_out: list[BacklinkEntry] = []
    content: str  # Full .md content
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime
    page_type: PageType = PageType.SOURCE


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
    source_count: int = 0
    backlink_count: int = 0
    created_at: datetime
    updated_at: datetime
    page_type: PageType = PageType.SOURCE
    concepts: list[str] = []
    source_ids: list[str] = []
    user_id: str | None = None


class ContradictionResolutionOption(BaseModel):
    """A valid resolution option for contradictions."""

    value: str
    label: str


class ResolveContradictionResponse(BaseModel):
    """Response after resolving a contradiction."""

    resolved: bool
    source_id: str
    target_id: str
    resolution: str


class RecompileResponse(BaseModel):
    """Response after scheduling an article recompile."""

    status: str
    job_id: str


class RebuildConceptsResponse(BaseModel):
    """Response after triggering taxonomy rebuild."""

    status: str


class HealthSummaryResponse(BaseModel):
    """Lightweight health summary from latest lint report."""

    generated_at: datetime | None = None
    total_articles: int = 0
    total_findings: int | None = None
    contradictions_count: int | None = None
    orphans_count: int | None = None
    status: str | None = None
    message: str | None = None


class JobTriggerResponse(BaseModel):
    """Response after triggering an async job."""

    status: str
    job_id: str | None = None
    message: str | None = None


class LintRunResponse(BaseModel):
    """Response after triggering a lint run."""

    status: str


class DismissFindingResponse(BaseModel):
    """Response after dismissing a lint finding."""

    dismissed: bool
    kind: str
    finding_id: str


class ConceptResponse(BaseModel):
    """Concept summary for list views."""

    id: str
    name: str
    description: str | None = None
    article_count: int = 0
    parent_id: str | None = None
    concept_kind: str = "topic"
    created_at: datetime


class ConceptDetailResponse(BaseModel):
    """Full concept with linked articles."""

    id: str
    name: str
    description: str | None = None
    article_count: int = 0
    parent_id: str | None = None
    concept_kind: str = "topic"
    created_at: datetime
    articles: list[ArticleSummaryResponse] = []


class SystemStats(BaseModel):
    """Aggregate system statistics."""

    article_count: int = 0
    source_count: int = 0
    concept_count: int = 0
    backlink_count: int = 0
    orphan_count: int = 0
    conversation_count: int = 0
    articles_by_type: dict[str, int] = {}


class OrphanArticle(BaseModel):
    """Article whose wiki file is missing from disk."""

    id: str
    slug: str
    title: str
    file_path: str


class EligibleConcept(BaseModel):
    """Concept eligible for concept-page generation."""

    id: str
    name: str
    article_count: int
    has_existing_page: bool = False


class AdminActionResult(BaseModel):
    """Result of an admin action."""

    action: str
    status: str
    job_id: str | None = None


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
    parent_conversation_id: str | None = None
    forked_at_turn_index: int | None = None
    fork_count: int = 0


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
    relation_type: RelationType = RelationType.REFERENCES
    resolution: str | None = None


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
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None


class CompletionResponse(BaseModel):
    """Response from LLM completion."""

    content: str
    provider_used: Provider
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class ExportFormat(StrEnum):
    """Supported article export formats."""

    PDF = "pdf"
    LINKEDIN = "linkedin"
    SLIDES = "slides"


class ExportResponse(BaseModel):
    """Response for text-based exports (LinkedIn, slides)."""

    format: ExportFormat
    content: str
    article_id: str
    article_title: str


# ---------------------------------------------------------------------------
# Magic Link (passwordless email) request/response models
# ---------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    """Request to send a magic link login email."""

    email: str


class MagicLinkResponse(BaseModel):
    """Response after requesting a magic link."""

    status: str
    message: str
    dev_token: str | None = None


class MagicLinkVerifyRequest(BaseModel):
    """Request to verify a magic link token."""

    token: str


class MagicLinkVerifyResponse(BaseModel):
    """Response after successfully verifying a magic link token."""

    access_token: str
    token_type: str = "bearer"
    user: dict
