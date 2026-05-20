"""Admin DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel

from wikimind.models.dto.lint import LinterContradiction

# ---------------------------------------------------------------------------
# Health / system stats
# ---------------------------------------------------------------------------


class HealthSummaryResponse(BaseModel):
    """Lightweight health summary from latest lint report."""

    generated_at: datetime | None = None
    total_articles: int = 0
    total_findings: int | None = None
    contradictions_count: int | None = None
    orphans_count: int | None = None
    status: str | None = None
    message: str | None = None


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


# ---------------------------------------------------------------------------
# Orphan / zombie / eligible concept
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


# ---------------------------------------------------------------------------
# Admin user detail
# ---------------------------------------------------------------------------


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
# Wiki health reports
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
