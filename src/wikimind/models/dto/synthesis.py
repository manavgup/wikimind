"""Synthesis DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.enums import PageType


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
