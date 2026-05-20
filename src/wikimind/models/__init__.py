"""Domain models — SQLModel tables persisted to SQLite and Pydantic schemas for the pipeline.

Enums define the vocabulary (source types, statuses, providers). SQLModel tables
store sources, articles, concepts, backlinks, queries, jobs, and cost logs.
Pydantic models carry data through the ingest -> compile -> query pipeline.

Pydantic DTOs (request/response schemas) are defined in ``wikimind.models.dto``
and re-exported here for backward compatibility.

This package re-exports all public names so that existing imports like
``from wikimind.models import Article`` continue to work unchanged.
"""

from typing import Any, NamedTuple

from pydantic import BaseModel

# Re-export DTO request/response schemas (replaces pipeline.py + schemas.py)
from wikimind.models.dto.admin import (
    AdminActionResult,
    AdminPlanResponse,
    AdminPlanUpdateRequest,
    AdminUserDetail,
    AdminUserSummary,
    EligibleConcept,
    HealthReport,
    HealthSummaryResponse,
    OrphanArticle,
    RecentSourceEntry,
    StuckSource,
    SystemStats,
    WikiHealthReport,
    ZombieSource,
)
from wikimind.models.dto.auth import (
    DeleteAccountResponse,
    MagicLinkRequest,
    MagicLinkResponse,
    MagicLinkVerifyRequest,
    MagicLinkVerifyResponse,
    OAuthTokenResponse,
    OAuthUserInfo,
    TokenCreateRequest,
    TokenCreateResponse,
    UserProfileResponse,
)
from wikimind.models.dto.capture import (
    AmbientAdapterConfigureRequest,
    AmbientAdapterListResponse,
    AmbientAdapterStatusResponse,
    AmbientPollResponse,
    CaptureDiscardResponse,
    CaptureIngestResponse,
    CaptureListResponse,
    CaptureRequest,
    CaptureResponse,
    DiscardCaptureRequest,
    RssFeedListResponse,
    RssFeedRequest,
    RssFeedResponse,
    RssFeedToggleRequest,
    RssPollResponse,
)
from wikimind.models.dto.common import TagResponse
from wikimind.models.dto.compilation import (
    AnswerCompilationResult,
    AnswerFrontmatter,
    ApproveDraftRequest,
    ApproveDraftResponse,
    CompilationDraftResponse,
    CompilationResult,
    CompilationSchemaResponse,
    CompiledClaimDTO,
    ConceptCompilationResult,
    ConceptFrontmatter,
    CreateCompilationSchemaRequest,
    IndexFrontmatter,
    MetaFrontmatter,
    RejectDraftResponse,
    SourceCompilationResult,
    SourceFrontmatter,
    SynthesisCompilationResult,
    SynthesisFrontmatter,
    TypedBacklinkSuggestion,
    UpdateCompilationSchemaRequest,
)
from wikimind.models.dto.ingest import (
    ArticleSourceSummary,
    DocumentChunk,
    IngestTextRequest,
    IngestURLRequest,
    LinkedArticleSummary,
    NormalizedDocument,
    PipelineStep,
    SourceContentResponse,
    SourceDetailResponse,
    SourceImageEntry,
    SourceResponse,
)
from wikimind.models.dto.lint import (
    DismissFindingResponse,
    JobTriggerResponse,
    LinterContradiction,
    LinterResult,
    LintRunResponse,
)
from wikimind.models.dto.llm import (
    CompletionRequest,
    CompletionResponse,
    LLMProviderStatus,
    LLMTraceListResponse,
    LLMTraceResponse,
)
from wikimind.models.dto.mcp import (
    MCPTokenCreateRequest,
    MCPTokenCreateResponse,
    MCPTokenResponse,
    MCPTokenRevokeResponse,
)
from wikimind.models.dto.query import (
    AskResponse,
    CitationArticleRef,
    CitationResponse,
    ConversationDetail,
    ConversationResponse,
    ConversationSummary,
    CrystallizeResponse,
    FileBackArticleRef,
    FileBackResult,
    FileBackSelectionRequest,
    ForkRequest,
    QueryRequest,
    QueryResponse,
    QueryResult,
    TurnSelection,
    WikiWorthinessScore,
)
from wikimind.models.dto.sharing import (
    CreateShareLinkRequest,
    ExportResponse,
    PublicArticleResponse,
    ShareLinkResponse,
    WikiExportResponse,
)
from wikimind.models.dto.synthesis import (
    CreateSynthesisRequest,
    SynthesisConfirmRequest,
    SynthesisConfirmResponse,
    SynthesisPreviewRequest,
    SynthesisPreviewResponse,
    SynthesisRefineRequest,
    SynthesisRefineResponse,
    SynthesisResponse,
    SynthesisSuggestion,
)
from wikimind.models.dto.tags import (
    ArticleTagResponse,
    CreateSavedSearchRequest,
    CreateTagRequest,
    SavedSearchResponse,
    TagArticleRequest,
)
from wikimind.models.dto.wiki import (
    ArticleCitationsResponse,
    ArticleDownloadResponse,
    ArticleEditRequest,
    ArticleRelationshipsResponse,
    ArticleResponse,
    ArticleSummaryResponse,
    BacklinkEntry,
    ClaimCitationResponse,
    ConceptDetailResponse,
    ConceptResponse,
    ContradictionResolutionOption,
    ContradictionResponse,
    CreateStubRequest,
    CreateStubResponse,
    DeleteConfirmation,
    EmbeddingStats,
    FacetBucket,
    FacetGroup,
    FacetResponse,
    FTSResultItem,
    GraphEdge,
    GraphNode,
    GraphResponse,
    RebuildConceptsResponse,
    RecompileResponse,
    RefreshArticleResponse,
    RelationshipEdge,
    ResolveContradictionBody,
    ResolveContradictionRequest,
    ResolveContradictionResponse,
    SavedSearchExecuteResponse,
    SearchResponse,
    SearchResult,
    SourceSpanResponse,
    WikilinkMatch,
)

# Re-export enums
from wikimind.models.enums import (
    ArticleDownloadFormat,
    CaptureKind,
    CaptureStatus,
    ClaimConceptRole,
    ClusterStatus,
    ConfidenceLevel,
    ContradictionResolution,
    ContradictionStatus,
    ExportFormat,
    IngestStatus,
    JobStatus,
    JobType,
    LintFindingKind,
    LintReportStatus,
    LintSeverity,
    LocatorKind,
    PageType,
    Provider,
    RelationType,
    SourceType,
    TaskType,
    WikiExportFormat,
)

# Re-export SQLModel tables from domain-specific sub-modules
from wikimind.models.tables import (  # noqa: F401
    AmbientAdapterSetting,
    Article,
    ArticleConcept,
    ArticleSource,
    ArticleTag,
    Backlink,
    CaptureSource,
    ClaimConcept,
    CompilationDraft,
    CompilationSchema,
    CompiledClaim,
    Concept,
    ConceptCluster,
    ConceptKindDef,
    Contradiction,
    ContradictionFinding,
    Conversation,
    CostLog,
    DismissedFinding,
    Job,
    LintPairCache,
    LintReport,
    LLMTrace,
    MCPAccessToken,
    MigrationHistory,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OrphanFinding,
    Plan,
    Query,
    QueryCount,
    ReinforcementEvent,
    RssFeed,
    SavedSearch,
    ShareLink,
    Source,
    SourceImage,
    SourceSpan,
    StorageUsage,
    StructuralFinding,
    Subscription,
    SyncLog,
    Tag,
    User,
    UserApiKey,
    UserPreference,
    WebhookEvent,
    _LintFindingBase,
)

# ---------------------------------------------------------------------------
# Pydantic models that reference SQLModel tables (kept here to avoid
# circular imports between dto/ and tables/).
# ---------------------------------------------------------------------------


class LintReportDetail(BaseModel):
    """API response shape for a single report with all findings."""

    report: LintReport
    contradictions: list[ContradictionFinding]
    orphans: list[OrphanFinding]
    resolutions: dict[str, str] = {}  # "article_a_id|article_b_id" -> resolution
    structurals: list[StructuralFinding] = []


# ---------------------------------------------------------------------------
# Typed return models that reference SQLModel tables (issue #394)
# ---------------------------------------------------------------------------


class FTSResponse(NamedTuple):
    """Result of a full-text search query: paginated results and total count."""

    results: list[FTSResultItem]
    total: int


class QAResult(NamedTuple):
    """Result of a Q&A answer call: query row, conversation, and optional score."""

    query: "Query"
    conversation: "Conversation"
    wiki_worthiness_score: WikiWorthinessScore | None


class FileBackArticlePair(NamedTuple):
    """Result of filing a conversation back to the wiki."""

    article: "Article"
    is_update: bool


class ResolvedBacklinks(NamedTuple):
    """Result of resolving wikilink candidates against the article table."""

    resolved: list[Any]  # list[ResolvedBacklink] -- avoids circular import
    unresolved: list[str]


# Resolve forward references now that all DTO modules are imported.
# SavedSearchExecuteResponse.saved_search uses forward-ref to SavedSearchResponse
SavedSearchExecuteResponse.model_rebuild()


__all__ = [
    # API schemas
    "AdminActionResult",
    "AdminPlanResponse",
    "AdminPlanUpdateRequest",
    "AdminUserDetail",
    "AdminUserSummary",
    "AmbientAdapterConfigureRequest",
    "AmbientAdapterListResponse",
    "AmbientAdapterSetting",
    "AmbientAdapterStatusResponse",
    "AmbientPollResponse",
    # Pipeline models
    "AnswerCompilationResult",
    # Frontmatter
    "AnswerFrontmatter",
    "ApproveDraftRequest",
    "ApproveDraftResponse",
    # Tables
    "Article",
    "ArticleCitationsResponse",
    "ArticleConcept",
    # Enums
    "ArticleDownloadFormat",
    "ArticleDownloadResponse",
    "ArticleEditRequest",
    "ArticleRelationshipsResponse",
    "ArticleResponse",
    "ArticleSource",
    "ArticleSourceSummary",
    "ArticleSummaryResponse",
    "ArticleTag",
    "ArticleTagResponse",
    "AskResponse",
    "Backlink",
    "BacklinkEntry",
    "CaptureDiscardResponse",
    "CaptureIngestResponse",
    "CaptureKind",
    "CaptureListResponse",
    "CaptureRequest",
    "CaptureResponse",
    "CaptureSource",
    "CaptureStatus",
    "CitationArticleRef",
    "CitationResponse",
    "ClaimCitationResponse",
    "ClaimConcept",
    "ClaimConceptRole",
    "ClusterStatus",
    "CompilationDraft",
    "CompilationDraftResponse",
    "CompilationResult",
    "CompilationSchema",
    "CompilationSchemaResponse",
    "CompiledClaim",
    "CompiledClaimDTO",
    "CompletionRequest",
    "CompletionResponse",
    "Concept",
    "ConceptCluster",
    "ConceptCompilationResult",
    "ConceptDetailResponse",
    "ConceptFrontmatter",
    "ConceptKindDef",
    "ConceptResponse",
    "ConfidenceLevel",
    "Contradiction",
    "ContradictionFinding",
    "ContradictionResolution",
    "ContradictionResolutionOption",
    "ContradictionResponse",
    "ContradictionStatus",
    "Conversation",
    "ConversationDetail",
    "ConversationResponse",
    "ConversationSummary",
    "CostLog",
    "CreateCompilationSchemaRequest",
    "CreateSavedSearchRequest",
    "CreateShareLinkRequest",
    "CreateStubRequest",
    "CreateStubResponse",
    "CreateSynthesisRequest",
    "CreateTagRequest",
    "CrystallizeResponse",
    "DeleteAccountResponse",
    "DeleteConfirmation",
    "DiscardCaptureRequest",
    "DismissFindingResponse",
    "DismissedFinding",
    "DocumentChunk",
    "EligibleConcept",
    "EmbeddingStats",
    "ExportFormat",
    "ExportResponse",
    "FTSResponse",
    "FTSResultItem",
    "FacetBucket",
    "FacetGroup",
    "FacetResponse",
    "FileBackArticlePair",
    "FileBackArticleRef",
    "FileBackResult",
    "FileBackSelectionRequest",
    "ForkRequest",
    "GraphEdge",
    "GraphNode",
    "GraphResponse",
    "HealthReport",
    "HealthSummaryResponse",
    "IndexFrontmatter",
    "IngestStatus",
    "IngestTextRequest",
    "IngestURLRequest",
    "Job",
    "JobStatus",
    "JobTriggerResponse",
    "JobType",
    "LLMProviderStatus",
    "LLMTrace",
    "LLMTraceListResponse",
    "LLMTraceResponse",
    "LinkedArticleSummary",
    "LintFindingKind",
    "LintPairCache",
    "LintReport",
    "LintReportDetail",
    "LintReportStatus",
    "LintRunResponse",
    "LintSeverity",
    "LinterContradiction",
    "LinterResult",
    "LocatorKind",
    "MCPAccessToken",
    "MCPTokenCreateRequest",
    "MCPTokenCreateResponse",
    "MCPTokenResponse",
    "MCPTokenRevokeResponse",
    "MagicLinkRequest",
    "MagicLinkResponse",
    "MagicLinkVerifyRequest",
    "MagicLinkVerifyResponse",
    "MetaFrontmatter",
    "MigrationHistory",
    "NormalizedDocument",
    "OAuthAccessToken",
    "OAuthAuthorizationCode",
    "OAuthTokenResponse",
    "OAuthUserInfo",
    "OrphanArticle",
    "OrphanFinding",
    "PageType",
    "PipelineStep",
    "Plan",
    "Provider",
    "PublicArticleResponse",
    "QAResult",
    "Query",
    "QueryCount",
    "QueryRequest",
    "QueryResponse",
    "QueryResult",
    "RebuildConceptsResponse",
    "RecentSourceEntry",
    "RecompileResponse",
    "RefreshArticleResponse",
    "ReinforcementEvent",
    "RejectDraftResponse",
    "RelationType",
    "RelationshipEdge",
    "ResolveContradictionBody",
    "ResolveContradictionRequest",
    "ResolveContradictionResponse",
    "ResolvedBacklinks",
    "RssFeed",
    "RssFeedListResponse",
    "RssFeedRequest",
    "RssFeedResponse",
    "RssFeedToggleRequest",
    "RssPollResponse",
    "SavedSearch",
    "SavedSearchExecuteResponse",
    "SavedSearchResponse",
    "SearchResponse",
    "SearchResult",
    "ShareLink",
    "ShareLinkResponse",
    "Source",
    "SourceCompilationResult",
    "SourceContentResponse",
    "SourceDetailResponse",
    "SourceFrontmatter",
    "SourceImage",
    "SourceImageEntry",
    "SourceResponse",
    "SourceSpan",
    "SourceSpanResponse",
    "SourceType",
    "StorageUsage",
    "StructuralFinding",
    "StuckSource",
    "Subscription",
    "SyncLog",
    "SynthesisCompilationResult",
    "SynthesisConfirmRequest",
    "SynthesisConfirmResponse",
    "SynthesisFrontmatter",
    "SynthesisPreviewRequest",
    "SynthesisPreviewResponse",
    "SynthesisRefineRequest",
    "SynthesisRefineResponse",
    "SynthesisResponse",
    "SynthesisSuggestion",
    "SystemStats",
    "Tag",
    "TagArticleRequest",
    "TagResponse",
    "TaskType",
    "TokenCreateRequest",
    "TokenCreateResponse",
    "TurnSelection",
    "TypedBacklinkSuggestion",
    "UpdateCompilationSchemaRequest",
    "User",
    "UserApiKey",
    "UserPreference",
    "UserProfileResponse",
    "WebhookEvent",
    "WikiExportFormat",
    "WikiExportResponse",
    "WikiHealthReport",
    "WikiWorthinessScore",
    "WikilinkMatch",
    "ZombieSource",
]
