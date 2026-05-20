"""Query and conversation DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.dto.ingest import SourceResponse

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
# API request/response models
# ---------------------------------------------------------------------------


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
    """Q&A response enriched with a full Answer -> Article -> Source citation chain.

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


# ---------------------------------------------------------------------------
# File-back / crystallize DTOs
# ---------------------------------------------------------------------------


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
