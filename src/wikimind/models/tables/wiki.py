"""Wiki tables — articles, concepts, backlinks, and join tables."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, String, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import ConfidenceLevel, LocatorKind, PageType, Provider, RelationType


class SourceSpan(SQLModel, table=True):
    """A locatable span within a source document (issue #450).

    Anchors a verbatim text excerpt to a precise location in the original
    source (PDF page rectangle, HTML XPath offset, byte range, or YouTube
    timestamp). Claims link to spans via ``CompiledClaim.source_span_ids``
    to provide paragraph-level citation provenance.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_id: str = Field(
        sa_column=Column(String, ForeignKey("source.id", ondelete="CASCADE"), index=True),
    )
    user_id: str = Field(foreign_key="user.id", index=True)
    locator_kind: LocatorKind  # "pdf-page-rect", "html-xpath-offset", etc.
    locator: dict = Field(sa_column=Column(JSON, nullable=False))  # adapter-specific anchor
    text: str = Field(sa_type=Text)  # verbatim quoted text
    fingerprint: str = Field(index=True)  # SHA-256 of normalized text for re-anchoring
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
