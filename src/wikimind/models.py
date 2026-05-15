"""Domain models — SQLModel tables persisted to SQLite and Pydantic schemas for the pipeline.

Enums define the vocabulary (source types, statuses, providers). SQLModel tables
store sources, articles, concepts, backlinks, queries, jobs, and cost logs.
Pydantic models carry data through the ingest → compile → query pipeline.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, NamedTuple

from pydantic import AnyHttpUrl, BaseModel, computed_field
from sqlalchemy import Column, ForeignKey, LargeBinary, String, Text, UniqueConstraint
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
    SYNTHESIS = "synthesis"


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
    REVIEW_PENDING = "review_pending"
    COMPILED = "compiled"
    FAILED = "failed"


class ConfidenceLevel(StrEnum):
    """Confidence level for claims."""

    SOURCED = "sourced"  # Claim directly from source
    MIXED = "mixed"  # Mix of source + inference
    INFERRED = "inferred"  # LLM synthesis
    OPINION = "opinion"  # Author's stated opinion


class ClusterStatus(StrEnum):
    """Lifecycle status of a concept cluster.

    Progression: candidate -> active -> archived | superseded | rejected.
    See issue #466 for status semantics.
    """

    CANDIDATE = "candidate"  # singleton or unconfirmed; hidden from default views
    ACTIVE = "active"  # promoted (member_count >= 2, reconciled)
    ARCHIVED = "archived"  # no reinforcement for >N months; recoverable
    SUPERSEDED = "superseded"  # merged into another cluster; superseded_by redirects
    REJECTED = "rejected"  # flagged as bad cluster; kept as negative training data


class ClaimConceptRole(StrEnum):
    """Role of a claim's relationship to a concept cluster."""

    SUBJECT = "subject"
    MENTIONED = "mentioned"


class CaptureKind(StrEnum):
    """Kind of ambient capture adapter that produced a CaptureSource."""

    SHARE_TARGET = "share_target"
    RSS = "rss"
    EMAIL = "email"
    CLIPBOARD = "clipboard"
    VOICE = "voice"
    SCREENSHOT = "screenshot"
    SLACK = "slack"
    DISCORD = "discord"


class CaptureStatus(StrEnum):
    """Lifecycle status of a captured item."""

    CAPTURED = "captured"
    TRIAGED = "triaged"
    INGESTED = "ingested"
    DISCARDED = "discarded"


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
    POLL_RSS_FEEDS = "poll_rss_feeds"


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
    is_admin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


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
        from wikimind.storage import find_original_sibling, get_raw_storage  # noqa: PLC0415

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


class ContradictionStatus(StrEnum):
    """Lifecycle status of a persisted contradiction."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


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


class CompiledClaimDTO(BaseModel):
    """A single compiled claim from a source (pipeline DTO).

    This Pydantic model carries claim data through the ingest/compile pipeline.
    For the persisted table, see :class:`CompiledClaim` (SQLModel table).
    """

    claim: str
    confidence: ConfidenceLevel
    subjects: list[str] = []  # LLM-extracted canonical subject names
    predicate: str | None = None  # LLM-extracted predicate
    quote: str | None = None  # Direct quote < 15 words if critical
    source_ids: list[str] = []  # Source UUIDs supporting this claim


class CompilationResult(BaseModel):
    """Output from LLM compiler for a single source."""

    title: str
    summary: str
    key_claims: list[CompiledClaimDTO]
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


class SynthesisCompilationResult(BaseModel):
    """Compilation result for synthesis pages — cross-cutting analysis across sources."""

    title: str
    query: str  # The user's synthesis question/topic
    summary: str
    themes: list[str]
    comparisons: str  # Comparative analysis section
    contradictions: str  # Where sources disagree
    timeline: str  # Chronological evolution
    gaps: list[str]  # Knowledge gaps identified
    open_questions: list[str]
    article_body: str  # Full markdown
    source_article_ids: list[str] = []  # IDs of articles analyzed
    concepts: list[str] = []
    page_type: PageType = PageType.SYNTHESIS


class SynthesisFrontmatter(BaseModel):
    """Validates frontmatter for synthesis-type wiki pages."""

    page_type: PageType = PageType.SYNTHESIS
    title: str
    slug: str
    query: str
    source_article_ids: list[str] = []
    source_count: int = 0
    synthesized_at: datetime | None = None
    concepts: list[str] = []
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


class WikiWorthinessScore(BaseModel):
    """Score describing whether a Q&A answer is worth filing back as a wiki page.

    Produced by the Q&A agent's auto file-back scorer. ``passed`` is the
    overall verdict; ``auto_filed`` records whether a wiki article was
    actually created as a result of this score.
    """

    word_count: int
    source_count: int
    synthesizes: bool
    dedup_collision: bool
    passed: bool
    auto_filed: bool = False


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


class SourceContentResponse(BaseModel):
    """Raw text content of an ingested source for side-by-side reading."""

    content: str
    source_type: SourceType
    title: str | None
    truncated: bool = False


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
    tags: list["TagResponse"] = []
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
    tags: list["TagResponse"] = []
    source_ids: list[str] = []
    user_id: str | None = None
    manually_edited: bool = False
    is_stub: bool = False


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


class WikiExportFormat(StrEnum):
    """Supported full-wiki export formats."""

    OBSIDIAN = "obsidian"
    MARKDOWN_JSON = "markdown_json"


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


class TagResponse(BaseModel):
    """API response for a user tag."""

    id: str
    name: str
    color: str
    created_at: datetime


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
# Typed return models for public service/route functions (issue #394)
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
# Typed return models for public service/route functions (issue #394)
# ---------------------------------------------------------------------------


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

    resolved: list[Any]  # list[ResolvedBacklink] — avoids circular import
    unresolved: list[str]


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


class WikiExportResponse(BaseModel):
    """Response metadata for wiki export (actual file is streamed)."""

    format: WikiExportFormat
    article_count: int
    filename: str
