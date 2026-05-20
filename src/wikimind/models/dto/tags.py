"""Tag and saved-search DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


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
