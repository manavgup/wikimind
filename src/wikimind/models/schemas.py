"""API request/response Pydantic schemas — all HTTP-facing data shapes.

This module contains every Pydantic model used as a FastAPI request body or
response body.  None of these are persisted directly; they define the API
contract between frontend and backend.
"""

from datetime import date, datetime
from typing import NamedTuple

from pydantic import AnyHttpUrl, BaseModel, Field

from wikimind.models.enums import (
    CaptureKind,
    CaptureStatus,
    ConfidenceLevel,
    ContradictionStatus,
    ExportFormat,
    IngestStatus,
    PageType,
    Provider,
    RelationType,
    SourceType,
    WikiExportFormat,
)
from wikimind.models.pipeline import LinterContradiction, WikiWorthinessScore
from wikimind.models.tables import ContradictionFinding, LintReport, OrphanFinding, StructuralFinding

# ---------------------------------------------------------------------------
# Lint report detail (depends on both tables and pipeline)
# ---------------------------------------------------------------------------


class LintReportDetail(BaseModel):
    """API response shape for a single report with all findings."""

    report: LintReport
    contradictions: list[ContradictionFinding]
    orphans: list[OrphanFinding]
    resolutions: dict[str, str] = {}  # "article_a_id|article_b_id" -> resolution
    structurals: list[StructuralFinding] = []


# ---------------------------------------------------------------------------
# Contradiction request/response models
# ---------------------------------------------------------------------------


class ResolveContradictionRequest(BaseModel):
    """Request to resolve a contradiction between two articles."""

    resolution: str
    resolution_note: str | None = None


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


class ContradictionResponse(BaseModel):
    """API response for a single persisted contradiction."""

    id: str
    claim_a: str
    claim_b: str
    article_a_id: str
    article_b_id: str
    article_a_title: str | None = None
    article_b_title: str | None = None
    detected_at: datetime
    status: str
    resolution: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class ResolveContradictionBody(BaseModel):
    """Request body for resolving or dismissing a persisted contradiction."""

    status: ContradictionStatus
    resolution: str | None = None


# ---------------------------------------------------------------------------
# Ingest request/response models
# ---------------------------------------------------------------------------


class IngestURLRequest(BaseModel):
    """Request to ingest a URL.

    Only ``http`` and ``https`` schemes are accepted (enforced by ``AnyHttpUrl``).
    """

    url: AnyHttpUrl
    auto_compile: bool = True


class IngestTextRequest(BaseModel):
    """Request to ingest raw text."""

    content: str = Field(max_length=500000)
    title: str | None = None
    auto_compile: bool = True


# ---------------------------------------------------------------------------
# Query request/response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Request to query the wiki."""

    question: str = Field(max_length=10000)
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


# ---------------------------------------------------------------------------
# Source response models
# ---------------------------------------------------------------------------


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


class PipelineStep(BaseModel):
    """A single step in the source processing pipeline."""

    name: str
    status: str  # "complete" | "active" | "pending" | "failed"
    description: str


class SourceImageEntry(BaseModel):
    """An extracted image entry for the source detail view."""

    filename: str
    kind: str  # "figure" | "table"
    label: str


class LinkedArticleSummary(BaseModel):
    """Minimal article info for the source detail view."""

    id: str
    slug: str
    title: str
    page_type: PageType = PageType.SOURCE


class SourceDetailResponse(BaseModel):
    """Full source detail with pipeline steps, images, and linked articles."""

    id: str
    source_type: SourceType
    source_url: str | None
    title: str | None
    author: str | None
    published_date: date | None
    status: IngestStatus
    ingested_at: datetime
    compiled_at: datetime | None
    token_count: int | None
    error_message: str | None
    has_original: bool
    pipeline_steps: list[PipelineStep]
    images: list[SourceImageEntry]
    linked_articles: list[LinkedArticleSummary]


class SourceContentResponse(BaseModel):
    """Raw text content of an ingested source for side-by-side reading."""

    content: str
    source_type: SourceType
    title: str | None
    truncated: bool = False


class ArticleSourceSummary(BaseModel):
    """Minimal source descriptor returned with listing/search endpoints.

    A lightweight summary used when the full :class:`SourceResponse` is
    overkill -- e.g. article list and search result payloads.
    """

    id: str
    source_type: SourceType
    title: str | None


# ---------------------------------------------------------------------------
# Article response models
# ---------------------------------------------------------------------------


class BacklinkEntry(BaseModel):
    """A backlink entry with human-readable metadata for the frontend."""

    id: str
    title: str
    slug: str
    relation_type: RelationType | None = None
    resolution: str | None = None


class TagResponse(BaseModel):
    """API response for a user tag."""

    id: str
    name: str
    color: str
    created_at: datetime


class ArticleResponse(BaseModel):
    """Full article response with content, backlinks, and source provenance."""

    id: str
    slug: str
    title: str
    summary: str | None
    confidence: ConfidenceLevel | None
    linter_score: float | None
    confidence_score: float = 0.5
    effective_confidence: float = 0.5
    staleness_score: float | None = None
    concepts: list[str] = []
    tags: list[TagResponse] = []
    backlinks_in: list[BacklinkEntry] = []
    backlinks_out: list[BacklinkEntry] = []
    content: str  # Full .md content
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime
    page_type: PageType = PageType.SOURCE
    manually_edited: bool = False
    edited_at: datetime | None = None
    is_stub: bool = False


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
    confidence_score: float = 0.5
    effective_confidence: float = 0.5
    staleness_score: float | None = None
    sources: list[ArticleSourceSummary] = []
    source_count: int = 0
    backlink_count: int = 0
    created_at: datetime
    updated_at: datetime
    page_type: PageType = PageType.SOURCE
    concepts: list[str] = []
    tags: list[TagResponse] = []
    source_ids: list[str] = []
    user_id: str | None = None
    manually_edited: bool = False
    is_stub: bool = False


class CreateStubRequest(BaseModel):
    """Request to create a stub wiki article (issue #451)."""

    title: str = Field(min_length=1)
    body_markdown: str = ""


class CreateStubResponse(BaseModel):
    """Response after creating a stub article."""

    id: str
    slug: str
    title: str
    is_stub: bool = True


class WikilinkMatch(BaseModel):
    """A single article match for wikilink resolution autocomplete."""

    id: str
    slug: str
    title: str
    is_stub: bool = False


class ArticleEditRequest(BaseModel):
    """Request to manually edit an article's content or title."""

    content: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)


# ---------------------------------------------------------------------------
# Synthesis request/response models
# ---------------------------------------------------------------------------


class CreateSynthesisRequest(BaseModel):
    """Request to create a synthesis page from a topic/question."""

    query: str = Field(min_length=3)
    article_ids: list[str] | None = None  # Optional specific article IDs; None = auto-select


class SynthesisResponse(BaseModel):
    """Response after creating a synthesis page."""

    id: str
    slug: str
    title: str
    query: str
    summary: str
    themes: list[str]
    source_count: int
    source_article_ids: list[str]
    created_at: datetime
    page_type: PageType = PageType.SYNTHESIS


class SynthesisPreviewRequest(BaseModel):
    """Request to generate a synthesis draft without saving it."""

    article_ids: list[str] = Field(min_length=2)
    synthesis_type: str | None = None  # Optional synthesis style hint
    guidance: str | None = None  # Optional user direction for focus


class SynthesisPreviewResponse(BaseModel):
    """Draft synthesis content returned for preview (not yet persisted)."""

    draft_content: str  # Full markdown draft
    suggested_title: str
    summary: str
    themes: list[str]
    article_ids: list[str]
    source_count: int


class SynthesisRefineRequest(BaseModel):
    """Request to refine a previous synthesis draft with user feedback."""

    draft_content: str  # The previous draft to refine
    article_ids: list[str] = Field(min_length=2)
    guidance: str  # User feedback/direction for refinement


class SynthesisRefineResponse(BaseModel):
    """Refined draft synthesis content."""

    draft_content: str
    suggested_title: str
    summary: str
    themes: list[str]
    article_ids: list[str]
    source_count: int


class SynthesisConfirmRequest(BaseModel):
    """Request to save a confirmed synthesis draft as a real article."""

    title: str = Field(min_length=1)
    draft_content: str
    article_ids: list[str] = Field(min_length=2)


class SynthesisConfirmResponse(BaseModel):
    """Response after confirming and saving a synthesis article."""

    id: str
    slug: str
    title: str
    summary: str
    themes: list[str]
    source_count: int
    source_article_ids: list[str]
    created_at: datetime
    page_type: PageType = PageType.SYNTHESIS


class SynthesisSuggestion(BaseModel):
    """A suggestion for a synthesis opportunity across related articles."""

    article_ids: list[str]
    article_titles: list[str]
    reason: str
    suggested_type: str  # "shared_concepts" | "contradiction" | "same_topic_different_sources"


# ---------------------------------------------------------------------------
# Job and operational response models
# ---------------------------------------------------------------------------


class RecompileResponse(BaseModel):
    """Response after scheduling an article recompile."""

    status: str
    job_id: str


class RefreshArticleResponse(BaseModel):
    """Response after marking an article as manually refreshed (issue #425)."""

    status: str
    staleness_score: float


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


# ---------------------------------------------------------------------------
# Concept response models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Admin response models
# ---------------------------------------------------------------------------


class StuckSource(BaseModel):
    """Source stuck in processing for longer than the threshold."""

    id: str
    title: str | None
    source_type: str
    ingested_at: str
    minutes_stuck: int


class SystemStats(BaseModel):
    """Aggregate system-wide statistics (admin dashboard)."""

    total_users: int = 0
    total_sources: int = 0
    total_articles: int = 0
    total_compiled_claims: int = 0

    # Legacy aliases for backward compat
    article_count: int = 0
    source_count: int = 0
    concept_count: int = 0
    backlink_count: int = 0
    orphan_count: int = 0
    conversation_count: int = 0
    articles_by_type: dict[str, int] = {}

    # Content breakdown
    articles_by_page_type: dict[str, int] = {}
    articles_by_confidence: dict[str, int] = {}
    sources_by_type: dict[str, int] = {}
    sources_by_status: dict[str, int] = {}

    # Operational health
    sources_stuck_processing: list[StuckSource] = []
    stuck_sources: int = 0
    compilation_queue_depth: int = 0
    compilation_success_rate: float | None = None
    avg_compilation_time_ms: float | None = None
    last_compilation_at: str | None = None


class AdminUserSummary(BaseModel):
    """Summary metrics for a single user in the admin users list."""

    id: str
    email: str
    name: str | None
    avatar_url: str | None
    article_count: int = 0
    source_count: int = 0
    total_cost_usd: float = 0.0
    last_active_at: datetime | None = None


class RecentSourceEntry(BaseModel):
    """A recently ingested source entry for the admin user detail view."""

    id: str
    title: str | None
    source_type: str
    status: str
    ingested_at: datetime


class AdminUserDetail(BaseModel):
    """Full per-user detail for the admin user detail endpoint."""

    id: str
    email: str
    name: str | None
    avatar_url: str | None
    article_count: int = 0
    source_count: int = 0
    total_cost_usd: float = 0.0
    last_active_at: datetime | None = None
    articles_by_type: dict[str, int] = {}
    sources_by_status: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    recent_sources: list[RecentSourceEntry] = []


# ---------------------------------------------------------------------------
# LLM trace response models
# ---------------------------------------------------------------------------


class LLMTraceResponse(BaseModel):
    """API response for a single LLM trace entry."""

    id: str
    user_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    created_at: datetime
    prompt_text: str | None = None
    completion_text: str | None = None
    source_id: str | None = None
    operation: str


class LLMTraceListResponse(BaseModel):
    """Paginated list of LLM traces."""

    items: list[LLMTraceResponse]
    total: int


# ---------------------------------------------------------------------------
# Miscellaneous operational models
# ---------------------------------------------------------------------------


class OrphanArticle(BaseModel):
    """Article whose wiki file is missing from disk."""

    id: str
    slug: str
    title: str
    file_path: str


class ZombieSource(BaseModel):
    """Source stuck in processing with no content file (zombie)."""

    id: str
    title: str | None
    source_type: str
    ingested_at: datetime


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


class FileBackArticleRef(BaseModel):
    """Minimal article reference returned by file-back operations."""

    id: str
    slug: str
    title: str


class FileBackResult(BaseModel):
    """Result of filing a conversation or selection back to the wiki."""

    article: FileBackArticleRef
    was_update: bool = False


class CrystallizeResponse(BaseModel):
    """Response after crystallizing a conversation into a wiki article."""

    article_id: str
    article_slug: str
    title: str
    turns_distilled: int


class DeleteConfirmation(BaseModel):
    """Confirmation of a resource deletion."""

    deleted: str


# ---------------------------------------------------------------------------
# Search response models
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single full-text search result with snippet and relevance score."""

    article_id: str
    slug: str
    title: str
    snippet: str  # FTS5 snippet with <mark> highlights
    rank: float  # BM25 relevance score


class SearchResponse(BaseModel):
    """Paginated full-text search response."""

    results: list[SearchResult]
    total: int
    query: str


class FacetBucket(BaseModel):
    """A single bucket within a facet (e.g. source_kind=pdf, count=12)."""

    value: str
    count: int


class FacetGroup(BaseModel):
    """A named facet with its buckets."""

    name: str
    buckets: list[FacetBucket]


class FacetResponse(BaseModel):
    """All facet groups for a search query."""

    facets: list[FacetGroup]
    total: int
    query: str


class EmbeddingStats(BaseModel):
    """Basic statistics about the vector store."""

    total_chunks: int


# ---------------------------------------------------------------------------
# Citation and Q&A response models
# ---------------------------------------------------------------------------


class CitationArticleRef(BaseModel):
    """Minimal reference to an article used inside a :class:`CitationResponse`."""

    slug: str
    title: str


class CitationResponse(BaseModel):
    """A single Q&A citation: an article plus the sources it was compiled from."""

    article: CitationArticleRef
    sources: list[SourceResponse] = []
    confidence_score: float = 0.5
    effective_confidence: float = 0.5


class QueryResponse(BaseModel):
    """Q&A response enriched with a full Answer -> Article -> Source citation chain.

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
    wiki_worthiness: WikiWorthinessScore | None = None


class ConversationResponse(BaseModel):
    """Conversation metadata exposed via API."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    filed_article_id: str | None = None
    crystallized_article_id: str | None = None
    parent_conversation_id: str | None = None
    forked_at_turn_index: int | None = None
    fork_count: int = 0


class ConversationSummary(ConversationResponse):
    """Conversation summary for the history sidebar -- adds turn count."""

    turn_count: int


class ConversationDetail(BaseModel):
    """Full conversation thread with all queries ordered by turn_index."""

    conversation: ConversationResponse
    queries: list[QueryResponse]


class AskResponse(BaseModel):
    """Response shape for POST /query -- wraps both the new query and its parent conversation."""

    query: QueryResponse
    conversation: ConversationResponse


# ---------------------------------------------------------------------------
# Graph response models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    """A node in the knowledge graph."""

    id: str
    label: str
    concept_cluster: str | None
    concepts: list[str] = []
    connection_count: int
    confidence: ConfidenceLevel | None
    confidence_score: float = 0.5
    effective_confidence: float = 0.5


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


class RelationshipEdge(BaseModel):
    """One end of a typed relationship to another article.

    Used by ``GET /wiki/articles/{id_or_slug}/relationships`` to describe
    the article on the *other* side of a backlink, plus any context or
    resolution metadata recorded on the edge.
    """

    article_id: str
    slug: str
    title: str
    relation_type: RelationType = RelationType.REFERENCES
    context: str | None = None
    resolution: str | None = None


class ArticleRelationshipsResponse(BaseModel):
    """Typed relationships for one article, grouped by direction and relation_type.

    ``incoming`` are edges where this article is the *target*.
    ``outgoing`` are edges where this article is the *source*.
    Each direction maps a :class:`RelationType` value (string) to the list
    of edges of that type.
    """

    incoming: dict[str, list[RelationshipEdge]] = {}
    outgoing: dict[str, list[RelationshipEdge]] = {}


# ---------------------------------------------------------------------------
# Health report models
# ---------------------------------------------------------------------------


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


class WikiHealthReport(BaseModel):
    """Health report returned by WikiService.get_health.

    Uses ``extra="allow"`` because the on-disk ``health.json`` may contain
    additional fields written by different linter versions.
    """

    model_config = {"extra": "allow"}

    generated_at: datetime | None = None
    total_articles: int = 0
    total_sources: int = 0
    total_findings: int | None = None
    contradictions_count: int | None = None
    orphans_count: int | None = None
    status: str | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# LLM provider status
# ---------------------------------------------------------------------------


class LLMProviderStatus(BaseModel):
    """Status of an LLM provider."""

    provider: Provider
    enabled: bool
    configured: bool  # API key present
    model: str
    cost_this_month_usd: float


# ---------------------------------------------------------------------------
# Export response models
# ---------------------------------------------------------------------------


class ExportResponse(BaseModel):
    """Response for text-based exports (LinkedIn, slides)."""

    format: ExportFormat
    content: str
    article_id: str
    article_title: str


class ArticleDownloadResponse(BaseModel):
    """Structured JSON export of a single article with metadata."""

    id: str
    slug: str
    title: str
    summary: str | None
    content: str
    page_type: PageType
    concepts: list[str] = []
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime


class WikiExportResponse(BaseModel):
    """Response metadata for wiki export (actual file is streamed)."""

    format: WikiExportFormat
    article_count: int
    filename: str


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


# ---------------------------------------------------------------------------
# API token (long-lived) request/response models
# ---------------------------------------------------------------------------


class TokenCreateRequest(BaseModel):
    """Request to create a long-lived API token."""

    name: str
    expires_in_days: int = Field(default=30, ge=1, le=365)


class TokenCreateResponse(BaseModel):
    """Response after creating a long-lived API token (shown only once)."""

    access_token: str
    token_type: str = "bearer"
    expires_at: str
    name: str


# ---------------------------------------------------------------------------
# Tag + Saved Search request/response models
# ---------------------------------------------------------------------------


class CreateTagRequest(BaseModel):
    """Request to create a new tag."""

    name: str = Field(min_length=1, max_length=100)
    color: str = "#6366f1"


class TagArticleRequest(BaseModel):
    """Request to tag an article."""

    tag_id: str


class ArticleTagResponse(BaseModel):
    """Confirmation that a tag was applied to an article."""

    article_id: str
    tag_id: str


class SavedSearchResponse(BaseModel):
    """API response for a saved search."""

    id: str
    name: str
    query: str
    filters_json: str
    created_at: datetime


class CreateSavedSearchRequest(BaseModel):
    """Request to create a saved search."""

    name: str = Field(min_length=1, max_length=200)
    query: str = ""
    filters_json: str = "{}"


class SavedSearchExecuteResponse(BaseModel):
    """Response when executing a saved search."""

    saved_search: SavedSearchResponse
    articles: list[ArticleSummaryResponse]


# ---------------------------------------------------------------------------
# Compilation draft request/response models
# ---------------------------------------------------------------------------


class CompilationDraftResponse(BaseModel):
    """API response for a compilation draft awaiting review."""

    id: str
    source_id: str
    title: str
    summary: str
    key_takeaways: list[str]
    draft_body: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None


class ApproveDraftRequest(BaseModel):
    """Request to approve a draft, optionally with user guidance."""

    guidance: str | None = None


class ApproveDraftResponse(BaseModel):
    """Response after approving a compilation draft."""

    status: str
    article_slug: str
    article_title: str


class RejectDraftResponse(BaseModel):
    """Response after rejecting a compilation draft."""

    status: str
    source_id: str


# ---------------------------------------------------------------------------
# OAuth response models
# ---------------------------------------------------------------------------


class OAuthTokenResponse(BaseModel):
    """OAuth token exchange response from an external provider.

    Contains at minimum an ``access_token`` field. Additional fields
    vary by provider (e.g. ``token_type``, ``scope``, ``id_token``).
    """

    model_config = {"extra": "allow"}

    access_token: str
    token_type: str | None = None
    scope: str | None = None


class OAuthUserInfo(BaseModel):
    """User profile from an OAuth provider (Google or GitHub).

    Only ``id`` is guaranteed; other fields may be absent depending
    on the provider and scopes.
    """

    model_config = {"extra": "allow"}

    id: int | str
    email: str | None = None
    name: str | None = None
    login: str | None = None
    picture: str | None = None
    avatar_url: str | None = None


class UserProfileResponse(BaseModel):
    """Public user profile returned by GET /auth/me."""

    id: str
    email: str | None = None
    name: str | None = None
    avatar_url: str | None = None


class DeleteAccountResponse(BaseModel):
    """Confirmation of account deletion."""

    deleted: str


# ---------------------------------------------------------------------------
# Full-text search internal models
# ---------------------------------------------------------------------------


class FTSResultItem(BaseModel):
    """A single full-text search result from the FTS index (internal)."""

    article_id: str
    slug: str
    title: str
    snippet: str
    rank: float


class FTSResponse(NamedTuple):
    """Result of a full-text search query: paginated results and total count."""

    results: list[FTSResultItem]
    total: int


# ---------------------------------------------------------------------------
# Capture (ambient capture) request/response models (issue #442)
# ---------------------------------------------------------------------------


class CaptureRequest(BaseModel):
    """Request to capture content from an ambient adapter."""

    title: str | None = None
    content: str = Field(max_length=500000)
    source_url: str | None = None
    external_id: str | None = None


class CaptureResponse(BaseModel):
    """API response for a captured item."""

    id: str
    kind: CaptureKind
    title: str | None
    source_url: str | None
    status: CaptureStatus
    external_id: str | None = None
    received_at: datetime
    triaged_at: datetime | None = None
    ingested_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    source_id: str | None = None


class CaptureListResponse(BaseModel):
    """Paginated list of captures."""

    items: list[CaptureResponse]
    total: int


class CaptureIngestResponse(BaseModel):
    """Response after promoting a capture to a full source."""

    capture_id: str
    source_id: str
    status: str = "ingested"


class CaptureDiscardResponse(BaseModel):
    """Response after discarding a capture."""

    capture_id: str
    status: str = "discarded"


class DiscardCaptureRequest(BaseModel):
    """Optional request body when discarding a capture."""

    reason: str | None = None


class RssFeedRequest(BaseModel):
    """Request to subscribe to an RSS feed."""

    feed_url: str
    title: str | None = None


class RssFeedResponse(BaseModel):
    """API response for an RSS feed subscription."""

    id: str
    feed_url: str
    title: str | None
    enabled: bool
    last_polled_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime


class RssFeedListResponse(BaseModel):
    """List of RSS feed subscriptions."""

    feeds: list[RssFeedResponse]


class RssFeedToggleRequest(BaseModel):
    """Request to enable or disable an RSS feed."""

    enabled: bool


class RssPollResponse(BaseModel):
    """Response after triggering an RSS poll."""

    feed_id: str
    new_captures: int
    status: str = "polled"


# ---------------------------------------------------------------------------
# Compilation Schema request/response models (issue #420)
# ---------------------------------------------------------------------------


class CreateCompilationSchemaRequest(BaseModel):
    """Request to create a user-defined compilation schema."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_active: bool = False
    article_max_length: int | None = Field(default=None, ge=100, le=50000)
    required_sections: list[str] | None = None
    style: str | None = Field(default=None, max_length=500)
    focus: str | None = Field(default=None, max_length=500)
    concept_max_depth: int | None = Field(default=None, ge=1, le=10)
    concept_naming: str | None = Field(default=None, max_length=200)
    extraction_always_note: list[str] | None = None
    extraction_ignore: list[str] | None = None
    custom_directives: str | None = Field(default=None, max_length=2000)


class UpdateCompilationSchemaRequest(BaseModel):
    """Request to update a compilation schema."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_active: bool | None = None
    article_max_length: int | None = Field(default=None, ge=100, le=50000)
    required_sections: list[str] | None = None
    style: str | None = Field(default=None, max_length=500)
    focus: str | None = Field(default=None, max_length=500)
    concept_max_depth: int | None = Field(default=None, ge=1, le=10)
    concept_naming: str | None = Field(default=None, max_length=200)
    extraction_always_note: list[str] | None = None
    extraction_ignore: list[str] | None = None
    custom_directives: str | None = Field(default=None, max_length=2000)


class CompilationSchemaResponse(BaseModel):
    """API response for a compilation schema."""

    id: str
    name: str
    description: str | None
    is_active: bool
    article_max_length: int | None
    required_sections: list[str] | None
    style: str | None
    focus: str | None
    concept_max_depth: int | None
    concept_naming: str | None
    extraction_always_note: list[str] | None
    extraction_ignore: list[str] | None
    custom_directives: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Share Link request/response models
# ---------------------------------------------------------------------------


class CreateShareLinkRequest(BaseModel):
    """Request to create a share link for an article."""

    article_id: str
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareLinkResponse(BaseModel):
    """API response for a share link."""

    id: str
    article_id: str
    token: str
    created_at: datetime
    expires_at: datetime | None
    revoked: bool
    view_count: int
    last_viewed_at: datetime | None
    article_title: str | None = None


class PublicArticleResponse(BaseModel):
    """Read-only public article content for share links."""

    title: str
    content_html: str
    summary: str | None
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# MCP Personal Access Token request/response models (ADR-027)
# ---------------------------------------------------------------------------


class MCPTokenCreateRequest(BaseModel):
    """Request to generate a new MCP personal access token."""

    name: str = Field(min_length=1, max_length=100)


class MCPTokenCreateResponse(BaseModel):
    """Response after creating an MCP token (plaintext shown ONCE)."""

    id: str
    token: str  # Plaintext -- shown only at creation, never stored
    name: str
    created_at: datetime


class MCPTokenResponse(BaseModel):
    """API response for an existing MCP token (never includes plaintext)."""

    id: str
    name: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class MCPTokenRevokeResponse(BaseModel):
    """Response after revoking an MCP token."""

    status: str
