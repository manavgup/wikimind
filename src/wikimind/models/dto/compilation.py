"""Compilation DTOs — dependency-light request/response schemas.

Covers compilation results, frontmatter, compilation schemas, and drafts.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.enums import (
    ConfidenceLevel,
    PageType,
    Provider,
    RelationType,
    SourceType,
)

# ---------------------------------------------------------------------------
# Compiled claim DTO (pipeline)
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
    source_span_ids: list[str] = []  # SourceSpan UUIDs anchoring this claim (issue #450)


# ---------------------------------------------------------------------------
# Compilation result models (pipeline)
# ---------------------------------------------------------------------------


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
# Frontmatter models
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
# Compilation schema request/response models (issue #420)
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
