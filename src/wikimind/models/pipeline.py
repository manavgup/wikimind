"""Pipeline and compilation Pydantic models — data flowing through ingest/compile/query.

These are pure Pydantic models (NOT persisted to the database). They carry data
through the ingest -> compile -> query pipeline and include compilation results,
frontmatter validators, linter results, and typed return tuples for service functions.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel
from sqlmodel import Field

from wikimind.models.enums import (
    ConfidenceLevel,
    PageType,
    Provider,
    RelationType,
    SourceType,
    TaskType,
)

# ---------------------------------------------------------------------------
# Document processing
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


# ---------------------------------------------------------------------------
# Compilation results
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Frontmatter validators
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Q&A pipeline models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Linter pipeline models
# ---------------------------------------------------------------------------


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
    coverage_scores: dict[str, float] = {}  # concept -> 0.0-1.0


# ---------------------------------------------------------------------------
# LLM completion models
# ---------------------------------------------------------------------------


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
    model_override: str | None = None
    disable_fallback: bool = False


class CompletionResponse(BaseModel):
    """Response from LLM completion."""

    content: str
    provider_used: Provider
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


# ---------------------------------------------------------------------------
# Typed return tuples for service functions
# ---------------------------------------------------------------------------


class QAResult(NamedTuple):
    """Result of a Q&A answer call: query row, conversation, and optional score."""

    query: Any  # Query table instance
    conversation: Any  # Conversation table instance
    wiki_worthiness_score: WikiWorthinessScore | None


class FileBackArticlePair(NamedTuple):
    """Result of filing a conversation back to the wiki."""

    article: Any  # Article table instance
    is_update: bool


class ResolvedBacklinks(NamedTuple):
    """Result of resolving wikilink candidates against the article table."""

    resolved: list[Any]  # list[ResolvedBacklink] — avoids circular import
    unresolved: list[str]
