"""Wiki article DTOs — dependency-light request/response schemas.

Covers articles, backlinks, concepts, graph, search, and relationships.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.dto.common import TagResponse
from wikimind.models.dto.ingest import ArticleSourceSummary, SourceResponse
from wikimind.models.dto.tags import SavedSearchResponse
from wikimind.models.enums import ConfidenceLevel, ContradictionStatus, LocatorKind, PageType, RelationType

# ---------------------------------------------------------------------------
# Backlink / relationship DTOs
# ---------------------------------------------------------------------------


class BacklinkEntry(BaseModel):
    """A backlink entry with human-readable metadata for the frontend."""

    id: str
    title: str
    slug: str
    relation_type: RelationType | None = None
    resolution: str | None = None


# ---------------------------------------------------------------------------
# Article DTOs
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Recompile / refresh / rebuild DTOs
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


# ---------------------------------------------------------------------------
# Contradiction DTOs
# ---------------------------------------------------------------------------


class ContradictionResolutionOption(BaseModel):
    """A valid resolution option for contradictions."""

    value: str
    label: str


class ResolveContradictionRequest(BaseModel):
    """Request to resolve a contradiction between two articles."""

    resolution: str
    resolution_note: str | None = None


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
# Concept DTOs
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
# Search DTOs
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


class FTSResultItem(BaseModel):
    """A single full-text search result from the FTS index (internal)."""

    article_id: str
    slug: str
    title: str
    snippet: str
    rank: float


# ---------------------------------------------------------------------------
# Graph DTOs
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
# Delete / common wiki DTOs
# ---------------------------------------------------------------------------


class DeleteConfirmation(BaseModel):
    """Confirmation of a resource deletion."""

    deleted: str


# ---------------------------------------------------------------------------
# Saved search execute (lives here to avoid tags→wiki circular import)
# ---------------------------------------------------------------------------


class SavedSearchExecuteResponse(BaseModel):
    """Response when executing a saved search."""

    saved_search: SavedSearchResponse
    articles: list[ArticleSummaryResponse]


# ---------------------------------------------------------------------------
# Span-level citation response models (issue #450)
# ---------------------------------------------------------------------------


class SourceSpanResponse(BaseModel):
    """API response for a single source span anchor."""

    id: str
    source_id: str
    locator_kind: LocatorKind
    locator: dict
    text: str
    fingerprint: str
    created_at: datetime


class ClaimCitationResponse(BaseModel):
    """A compiled claim with its linked source spans for citation display."""

    id: str
    text: str
    confidence_level: str
    confidence_score: float
    source_ids: list[str] = []
    source_spans: list[SourceSpanResponse] = []


class ArticleCitationsResponse(BaseModel):
    """All claims for an article with their source spans."""

    article_id: str
    article_title: str
    claims: list[ClaimCitationResponse] = []


# ---------------------------------------------------------------------------
# Per-claim confidence response models (issue #465)
# ---------------------------------------------------------------------------


class ClaimConfidenceResponse(BaseModel):
    """A compiled claim with its confidence score and source attribution."""

    id: str
    text: str
    confidence_level: str
    confidence_score: float
    source_ids: list[str] = []
    last_reinforced_at: datetime
    created_at: datetime


class ArticleClaimsResponse(BaseModel):
    """All persisted claims for an article with their confidence scores."""

    article_id: str
    article_title: str
    article_confidence_score: float
    claims: list[ClaimConfidenceResponse] = []
