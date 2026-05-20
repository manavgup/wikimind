"""SQLModel table definitions — all persisted database models.

This module contains every ``SQLModel`` class with ``table=True``, organized
by domain: core entities, wiki content, conversations, jobs, billing, lint,
and supporting tables.
"""

import datetime as dt
import uuid
from datetime import date, datetime

from pydantic import computed_field
from sqlalchemy import JSON, BigInteger, Column, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import (
    CaptureKind,
    CaptureStatus,
    ClusterStatus,
    ConfidenceLevel,
    ContradictionStatus,
    IngestStatus,
    JobStatus,
    JobType,
    LintFindingKind,
    LintReportStatus,
    LintSeverity,
    PageType,
    Provider,
    RelationType,
    SourceType,
    TaskType,
)
from wikimind.storage import find_original_sibling, get_raw_storage

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class MigrationHistory(SQLModel, table=True):
    """Tracks which data migrations have been applied.

    Each row records a unique migration version string and when it ran.
    init_db() checks this table to skip already-applied migrations,
    turning O(n) startup scans into a constant-time version check.
    """

    version: str = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# User & Auth
# ---------------------------------------------------------------------------


class User(SQLModel, table=True):
    """Authenticated user account."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str | None = None
    avatar_url: str | None = None
    auth_provider: str  # "google" | "github"
    auth_provider_id: str  # provider's unique user ID
    is_admin: bool = Field(default=False)
    plan_id: str | None = None
    plan_effective_until: datetime | None = None
    lemon_squeezy_customer_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


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
    user_id: str = Field(foreign_key="user.id", index=True)
    value: str
    updated_at: datetime = Field(default_factory=utcnow_naive)


class MCPAccessToken(SQLModel, table=True):
    """Personal access token for MCP API authentication.

    Tokens use the ``wmk_`` prefix for easy identification. Only the
    SHA-256 hash is stored; the plaintext is shown once at creation and
    never persisted. See ADR-027.
    """

    __tablename__ = "mcp_access_token"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str = Field(max_length=100)
    token_hash: str  # SHA-256 hash (never store plaintext)
    token_prefix: str = Field(max_length=12)  # "wmk_ab12..." for display
    created_at: datetime = Field(default_factory=utcnow_naive)
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked: bool = False


class OAuthAuthorizationCode(SQLModel, table=True):
    """Short-lived OAuth 2.1 authorization code for MCP client flows.

    Created when a user approves an MCP client's authorization request.
    Exchanged for an access token at the token endpoint. Codes expire
    after 5 minutes and can only be used once (``used`` flag).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    code: str = Field(index=True)
    user_id: str = Field(foreign_key="user.id")
    client_id: str
    redirect_uri: str
    code_challenge: str  # S256 hash
    state: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime
    used: bool = False


class OAuthAccessToken(SQLModel, table=True):
    """OAuth 2.1 access token issued to MCP clients.

    Created during the token exchange (authorization_code grant).
    Tokens use the ``wmk_`` prefix and are validated by the MCP auth
    provider alongside PAT tokens.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    token_hash: str = Field(index=True)  # SHA-256 of the raw token
    user_id: str = Field(foreign_key="user.id", index=True)
    client_id: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime
    revoked: bool = False


# ---------------------------------------------------------------------------
# Sources & Ingestion
# ---------------------------------------------------------------------------


class Source(SQLModel, table=True):
    """Raw ingested source — before compilation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
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
    clean_text: str | None = Field(
        default=None,
        sa_type=Text,
        exclude=True,
    )  # DB-backed source content; excluded from API responses
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
        raw_storage = get_raw_storage(self.user_id)
        try:
            txt_path = raw_storage.resolve_path(self.file_path)
        except ValueError:
            return False
        return find_original_sibling(txt_path) is not None


class SourceImage(SQLModel, table=True):
    """Image extracted from a PDF source, stored in Postgres.

    Replaces filesystem storage so web and worker machines can both
    access extracted images without shared volumes (issue #638).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_id: str = Field(
        sa_column=Column(String, ForeignKey("source.id", ondelete="CASCADE"), index=True),
    )
    user_id: str = Field(foreign_key="user.id", index=True)
    filename: str  # e.g. "picture-1.png", "table-2.png"
    kind: str  # "figure" or "table"
    image_data: bytes = Field(sa_type=LargeBinary, exclude=True)
    created_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# Wiki Content — Articles, Concepts, Backlinks
# ---------------------------------------------------------------------------


class Article(SQLModel, table=True):
    """Compiled wiki article metadata. Content lives in .md file."""

    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_article_user_slug"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    slug: str = Field(index=True)
    title: str
    file_path: str  # Path to .md file in wiki/
    concept_ids: str | None = None  # JSON array of concept IDs
    confidence: ConfidenceLevel | None = None
    linter_score: float | None = None
    summary: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    # Numeric article-level confidence in [0.0, 1.0] computed from source
    # count, recency, source-type quality, and contradiction count. Distinct
    # from the categorical per-claim ``confidence`` field above. See
    # ``wikimind.engine.confidence`` for the formula.
    confidence_score: float = Field(default=0.5)
    # Timestamp of the most recent (re)compilation; used by ``apply_decay``
    # to compute ``effective_confidence`` at read time.
    last_reinforced_at: datetime | None = None
    # Date of the most recent source used in this article (issue #425).
    source_newest_at: datetime | None = None
    source_ids: str | None = None  # JSON array of source IDs
    # Which LLM provider compiled this article (issue #67). Recompiling the
    # same source with the same provider replaces this article in place;
    # different providers stack as separate articles for comparison.
    provider: Provider | None = None
    page_type: PageType = Field(
        default=PageType.SOURCE,
        sa_column=Column(String, default=PageType.SOURCE),
    )
    # Manual editing support (issue #449). When a user edits an article's
    # content directly, ``manually_edited`` is set to True and ``edited_at``
    # records the timestamp. Recompilation respects this flag: a force
    # parameter is required to overwrite user edits.
    manually_edited: bool = False
    edited_at: datetime | None = None
    # Stub page support (issue #451). Stub articles are user-created
    # placeholder pages for concepts that have no source coverage yet.
    # They appear in article lists but are visually differentiated.
    is_stub: bool = False
    # Compilation monitoring fields (issue #547). Track when and how
    # long compilation took, plus total LLM tokens consumed.
    compiled_at: datetime | None = None
    compilation_duration_ms: int | None = None
    compilation_tokens: int | None = None

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


class ReinforcementEvent(SQLModel, table=True):
    """Records each event that reinforces an article's freshness (issue #425).

    Events are created when an article is recompiled, gains a new source,
    or is manually refreshed by the user. The ``compute_staleness`` function
    uses ``Article.last_reinforced_at`` (the max of all events) for its
    decay calculation.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    event_type: str  # "new_source", "recompile", "manual_refresh"
    occurred_at: datetime = Field(default_factory=utcnow_naive)
    source_id: str | None = None
    user_id: str = Field(foreign_key="user.id", index=True)


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
    user_id: str = Field(foreign_key="user.id", index=True)
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
    user_id: str = Field(foreign_key="user.id", index=True)
    context: str | None = None  # Sentence where link appears
    relation_type: str = Field(default=RelationType.REFERENCES)
    resolution: str | None = None
    resolution_note: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class Contradiction(SQLModel, table=True):
    """A persisted contradiction between claims in two wiki articles.

    Created by the linter when it detects contradictory claims across articles.
    Users can browse, resolve, or dismiss contradictions as first-class wiki content.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    claim_a: str
    claim_b: str
    article_a_id: str = Field(foreign_key="article.id", index=True)
    article_b_id: str = Field(foreign_key="article.id", index=True)
    source_finding_id: str | None = None  # FK to ContradictionFinding that created this
    claim_fingerprint: str = Field(default="", index=True)  # SHA-256 of sorted article+claim pair
    detected_at: datetime = Field(default_factory=utcnow_naive)
    status: ContradictionStatus = ContradictionStatus.ACTIVE
    resolution: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    user_id: str = Field(foreign_key="user.id", index=True)


class Tag(SQLModel, table=True):
    """User-created organizational tag (separate from LLM-derived concepts).

    Tags like ``read-later``, ``favorite``, ``to-revisit`` give users their own
    retrieval layer. Each tag has a display color for pill-badge rendering.
    """

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    color: str = "#6366f1"  # Default indigo
    created_at: datetime = Field(default_factory=utcnow_naive)


class ArticleTag(SQLModel, table=True):
    """Join table linking articles to user-created tags."""

    __table_args__ = (UniqueConstraint("article_id", "tag_id", name="uq_articletag_article_tag"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    tag_id: str = Field(foreign_key="tag.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_naive)


class ShareLink(SQLModel, table=True):
    """A signed, revocable read-only share link for a single article.

    Each share link has a cryptographically random token used in the public
    URL. Links can be revoked or set to expire. View counts are tracked
    for analytics.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    token: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime | None = None
    revoked: bool = False
    view_count: int = 0
    last_viewed_at: datetime | None = None


class SavedSearch(SQLModel, table=True):
    """User-saved search with optional tag and concept filters.

    Stores a search query string plus a JSON blob of filters so users can
    one-click re-execute common searches like "Q2 Research" or "read-later
    items about prompt caching".
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    query: str
    filters_json: str = "{}"  # JSON: {"tags": ["read-later"], "concepts": [...]}
    created_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# Conversations & Q&A
# ---------------------------------------------------------------------------


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
    user_id: str = Field(foreign_key="user.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")
    crystallized_article_id: str | None = Field(default=None, foreign_key="article.id")
    parent_conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    forked_at_turn_index: int | None = None


class Query(SQLModel, table=True):
    """Q&A history entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
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


# ---------------------------------------------------------------------------
# Jobs & Cost Tracking
# ---------------------------------------------------------------------------


class Job(SQLModel, table=True):
    """Async job record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
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
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: Provider
    model: str
    task_type: TaskType
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    job_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class LLMTrace(SQLModel, table=True):
    """Opt-in LLM call trace for debugging and cost monitoring.

    Always stores lightweight metrics (tokens, latency, model, operation).
    Prompt/completion text is only stored when ``trace_store_content`` is enabled.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)
    prompt_text: str | None = Field(default=None, sa_type=Text)
    completion_text: str | None = Field(default=None, sa_type=Text)
    source_id: str | None = None
    operation: str  # "compile", "query", "synthesis", etc.


class SyncLog(SQLModel, table=True):
    """Cloud sync history."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    direction: str  # push | pull
    articles_pushed: int = 0
    articles_pulled: int = 0
    conflicts: int = 0
    started_at: datetime = Field(default_factory=utcnow_naive)
    completed_at: datetime | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Ambient Capture
# ---------------------------------------------------------------------------


class CaptureSource(SQLModel, table=True):
    """An item captured by an ambient capture adapter (issue #442).

    Captures are cheap and promiscuous: every item matching an adapter's
    filter is logged here. A triage step (manual or auto) decides whether
    to promote the capture to a full Source for compilation, or discard it.

    Lifecycle: captured -> triaged -> ingested | discarded
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    kind: CaptureKind
    external_id: str | None = Field(default=None, index=True)
    title: str | None = None
    raw_payload: str  # JSON blob or plain text
    content_hash: str = Field(default="", index=True)
    status: CaptureStatus = CaptureStatus.CAPTURED
    source_url: str | None = None
    source_id: str | None = Field(default=None, foreign_key="source.id")
    received_at: datetime = Field(default_factory=utcnow_naive)
    triaged_at: datetime | None = None
    ingested_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None


class RssFeed(SQLModel, table=True):
    """A user-subscribed RSS/Atom feed (issue #442).

    The RSS adapter polls each enabled feed on a schedule, creating
    CaptureSource rows for new entries (deduped by guid or link).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    feed_url: str
    title: str | None = None
    enabled: bool = True
    last_polled_at: datetime | None = None
    last_entry_id: str | None = None  # guid or link of most recent entry
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# Compilation Drafts & Claims
# ---------------------------------------------------------------------------


class CompilationDraft(SQLModel, table=True):
    """Draft compilation output awaiting user review before finalizing.

    Created when ``compilation.interactive`` is enabled. The LLM extracts
    key takeaways and a draft article; the user reviews, optionally adds
    guidance, and approves or rejects before the article is saved to the wiki.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    source_id: str = Field(foreign_key="source.id", index=True)
    title: str
    summary: str
    key_takeaways: str  # JSON array of strings
    draft_result_json: str  # Serialized CompilationResult
    user_guidance: str | None = None  # User-provided focus direction
    status: str = "pending"  # pending | approved | rejected
    created_at: datetime = Field(default_factory=utcnow_naive)
    reviewed_at: datetime | None = None


class CompiledClaim(SQLModel, table=True):
    """A persisted compiled claim extracted from a source article (issue #466).

    Promoted from the Pydantic-only ``CompiledClaimDTO`` to a first-class table
    so that claims are individually queryable, linkable to concept clusters,
    and carry their own embedding for semantic similarity.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    text: str  # The claim text
    subjects: str = "[]"  # JSON list[str]: LLM-extracted canonical subject names
    predicate: str | None = None  # LLM-extracted predicate (nullable initially)
    confidence_level: str  # ConfidenceLevel enum value
    confidence_score: float = Field(default=0.5)  # numeric, reused from #422
    source_ids: str = "[]"  # JSON list of source UUIDs supporting this claim
    last_reinforced_at: datetime = Field(default_factory=utcnow_naive)
    quote: str | None = None
    embedding: bytes | None = None  # raw float32 array; nullable until embedding runs
    embedding_version: str | None = None  # e.g. "bge-small-1.5"
    cluster_assignment_reconciled: bool = False
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ConceptCluster(SQLModel, table=True):
    """An implicit concept cluster derived from compiled claim subjects (issue #466).

    Clusters group semantically related claims by subject. The two-stage pipeline
    assigns claims to clusters: online (advisory) at ingest time, offline
    (reconciled) by the batch reconciler.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    canonical_text: str  # canonical subject name
    centroid_embedding: bytes | None = None  # raw float32 array
    embedding_version: str | None = None  # centroid valid only for this version
    member_count: int = 0
    status: str = Field(default=ClusterStatus.CANDIDATE)  # ClusterStatus enum value
    superseded_by: str | None = Field(default=None, foreign_key="conceptcluster.id")
    last_reinforced_at: datetime = Field(default_factory=utcnow_naive)
    last_reconciled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ClaimConcept(SQLModel, table=True):
    """Join table linking compiled claims to concept clusters (issue #466).

    ``advisory=True`` is the default at ingest time — the online clusterer's
    best guess. The offline reconciler sets ``advisory=False`` and updates
    ``CompiledClaim.cluster_assignment_reconciled=True``.
    """

    claim_id: str = Field(foreign_key="compiledclaim.id", primary_key=True)
    concept_id: str = Field(foreign_key="conceptcluster.id", primary_key=True, index=True)
    role: str = Field(primary_key=True)  # ClaimConceptRole enum value
    advisory: bool = True  # TRUE until offline reconciler confirms
    created_at: datetime = Field(default_factory=utcnow_naive)


class CompilationSchema(SQLModel, table=True):
    """User-defined compilation rules that guide how sources become wiki articles.

    Each schema contains structured directives (article structure, style,
    extraction rules, concept taxonomy preferences) that are injected into
    the compiler's LLM prompt at compilation time. Only one schema per user
    can be active at a time (issue #420).
    """

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_compilationschema_user_name"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    description: str | None = None
    is_active: bool = False
    # Structured rule fields (JSON strings for flexibility)
    article_max_length: int | None = None
    required_sections: str | None = None  # JSON array: ["summary", "key_claims"]
    style: str | None = None  # Freeform style directive
    focus: str | None = None  # What to emphasize
    concept_max_depth: int | None = None
    concept_naming: str | None = None  # e.g. "lowercase, hyphenated"
    extraction_always_note: str | None = None  # JSON array: ["methodology"]
    extraction_ignore: str | None = None  # JSON array: ["author bios"]
    custom_directives: str | None = None  # Freeform additional directives
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# Billing Tables
# ---------------------------------------------------------------------------


class Plan(SQLModel, table=True):
    """Billing plan with limits and pricing."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True)
    display_name: str
    price_cents: int
    billing_interval: str | None = None
    max_sources: int | None = None
    max_articles: int | None = None
    max_queries_per_day: int | None = None
    max_storage_bytes: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    max_active_shares: int | None = None
    daily_llm_spend_cap_cents: int | None = None
    allowed_exports: list[str] = Field(sa_column=Column(JSON, nullable=False))
    mcp_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_model: str = "gpt-4o-mini"
    byok_allowed: bool = False
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0
    lemon_squeezy_variant_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class Subscription(SQLModel, table=True):
    """User subscription to a billing plan via Lemon Squeezy."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    plan_id: str
    lemon_squeezy_subscription_id: str = Field(unique=True)
    lemon_squeezy_customer_id: str
    status: str = "active"
    cancel_at_period_end: bool = False
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class WebhookEvent(SQLModel, table=True):
    """Processed Lemon Squeezy webhook events for idempotency."""

    __tablename__ = "webhook_event"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    lemon_squeezy_event_id: str = Field(unique=True)
    event_type: str
    processed_at: datetime
    payload_hash: str


class StorageUsage(SQLModel, table=True):
    """Precomputed storage usage per user for fast quota checks."""

    __tablename__ = "storage_usage"

    user_id: str = Field(primary_key=True)
    total_bytes: int = 0
    updated_at: datetime = Field(default_factory=utcnow_naive)


class QueryCount(SQLModel, table=True):
    """Daily query count per user for quota enforcement."""

    __tablename__ = "query_count"

    user_id: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
    count: int = 0


# ---------------------------------------------------------------------------
# Lint Report + Per-Kind Finding Tables
# ---------------------------------------------------------------------------


class LintReport(SQLModel, table=True):
    """One run of the linter. All findings from a run FK back to this row via report_id."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
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
    user_id: str = Field(foreign_key="user.id", index=True)
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
    contradiction_id: str | None = Field(default=None, index=True)  # FK to Contradiction


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
