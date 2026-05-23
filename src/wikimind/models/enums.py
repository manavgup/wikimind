"""Domain enums — vocabulary types for sources, statuses, providers, and more.

All StrEnum classes are collected here so that SQLModel tables, Pydantic schemas,
and service layers can import a lightweight module without pulling in the full
ORM graph.
"""

from enum import StrEnum

# ---------------------------------------------------------------------------
# Core domain enums
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
    BROWSER_HISTORY = "browser_history"


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
# Contradiction & Lint enums
# ---------------------------------------------------------------------------


class ContradictionStatus(StrEnum):
    """Lifecycle status of a persisted contradiction."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


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


class ContradictionResolution(StrEnum):
    """Valid resolution values for a contradiction between two articles."""

    SOURCE_A_WINS = "source_a_wins"
    SOURCE_B_WINS = "source_b_wins"
    BOTH_VALID = "both_valid"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# Export enums
# ---------------------------------------------------------------------------


class ExportFormat(StrEnum):
    """Supported article export formats."""

    PDF = "pdf"
    LINKEDIN = "linkedin"
    SLIDES = "slides"


class ArticleDownloadFormat(StrEnum):
    """Supported single-article download formats (GET endpoint)."""

    MARKDOWN = "markdown"
    JSON = "json"


class WikiExportFormat(StrEnum):
    """Supported full-wiki export formats."""

    OBSIDIAN = "obsidian"
    MARKDOWN_JSON = "markdown_json"


class LocatorKind(StrEnum):
    """Type of anchor locator for a source span (issue #450)."""

    PDF_PAGE_RECT = "pdf-page-rect"
    HTML_PARAGRAPH_OFFSET = "html-paragraph-offset"
    TEXT_BYTE_RANGE = "text-byte-range"
    YOUTUBE_TIMESTAMP = "youtube-timestamp"
