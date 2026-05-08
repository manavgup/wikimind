"""Handle question answering against the wiki and file-back to articles.

Wraps the QA agent, manages query persistence, and coordinates the
file-back workflow that promotes Q&A answers into wiki articles.
Q&A responses are enriched with full Answer → Article → Source citation
chains so callers can trace every answer back to the raw source it came
from.
"""

import asyncio
import functools
import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import structlog
from fastapi.responses import Response
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.confidence import apply_decay
from wikimind.engine.conversation_serializer import (
    SelectedTurn,
    serialize_conversation_to_markdown,
    serialize_selected_turns_to_markdown,
)
from wikimind.engine.qa_agent import QAAgent
from wikimind.errors import NotFoundError, QueryError
from wikimind.models import (
    Article,
    ArticleSource,
    AskResponse,
    CitationArticleRef,
    CitationResponse,
    Conversation,
    ConversationDetail,
    ConversationResponse,
    ConversationSummary,
    FileBackArticleRef,
    FileBackResult,
    FileBackSelectionRequest,
    ForkRequest,
    PageType,
    Query,
    QueryRequest,
    QueryResponse,
    Source,
    SourceResponse,
    WikiWorthinessScore,
)
from wikimind.services.search import index_article as fts_index_article

log = structlog.get_logger()


def _parse_source_ids(raw: str | None) -> list[str]:
    """Parse the JSON-encoded ``Article.source_ids`` field into a list of IDs.

    Mirrors the helper in :mod:`wikimind.services.wiki` so the query
    service does not need to import private helpers from a sibling
    module. Returns an empty list when the field is missing or malformed.

    Args:
        raw: Raw JSON string stored on :attr:`Article.source_ids`.

    Returns:
        List of source UUID strings (possibly empty).
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Failed to parse Article.source_ids JSON", raw=raw)
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _parse_article_titles(raw: str | None) -> list[str]:
    """Parse the JSON-encoded ``Query.source_article_ids`` field.

    Despite the column name, the QA agent persists *article titles*
    here (the LLM cites by title, not by UUID). This helper decodes
    the JSON list defensively.

    Args:
        raw: Raw JSON string stored on :attr:`Query.source_article_ids`.

    Returns:
        List of article title strings (possibly empty).
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Failed to parse Query.source_article_ids JSON", raw=raw)
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


async def _build_citations(query: Query, session: AsyncSession, user_id: str) -> list[CitationResponse]:
    """Resolve a Q&A record into a full citation chain.

    Walks ``Query.source_article_ids`` (which the QA agent populates with
    article titles), looks up each cited :class:`Article` by exact title
    match, then fetches every :class:`Source` referenced by the
    article's ``source_ids`` JSON column. Articles that cannot be
    resolved are skipped.

    Args:
        query: The persisted Query record.
        session: Async database session.
        user_id: User ID for data isolation — scopes to this user's articles.

    Returns:
        Resolved citation list with full source provenance for each
        cited article.
    """
    titles = _parse_article_titles(query.source_article_ids)
    if not titles:
        return []

    stmt = select(Article).where(Article.title.in_(titles))  # type: ignore[attr-defined]
    if user_id:
        stmt = stmt.where(Article.user_id == user_id)
    article_result = await session.execute(stmt)
    articles_by_title = {a.title: a for a in article_result.scalars().all()}

    citations: list[CitationResponse] = []
    for title in titles:
        article = articles_by_title.get(title)
        if article is None:
            continue
        # Query join table for source IDs
        as_result = await session.execute(select(ArticleSource.source_id).where(ArticleSource.article_id == article.id))
        source_ids = [row[0] for row in as_result.all()]
        # Fallback to JSON column for pre-migration data
        if not source_ids:
            source_ids = _parse_source_ids(article.source_ids)
        sources: list[Source] = []
        if source_ids:
            src_result = await session.execute(
                select(Source).where(Source.id.in_(source_ids)),  # type: ignore[attr-defined]
            )
            by_id = {s.id: s for s in src_result.scalars().all()}
            sources = [by_id[sid] for sid in source_ids if sid in by_id]
        if article.last_reinforced_at is None:
            effective = article.confidence_score
        else:
            days = max(0, (utcnow_naive() - article.last_reinforced_at).days)
            effective = apply_decay(article.confidence_score, days)
        citations.append(
            CitationResponse(
                article=CitationArticleRef(slug=article.slug, title=article.title),
                sources=[
                    SourceResponse(
                        id=s.id,
                        source_type=s.source_type,
                        title=s.title,
                        source_url=s.source_url,
                        ingested_at=s.ingested_at,
                    )
                    for s in sources
                ],
                confidence_score=article.confidence_score,
                effective_confidence=effective,
            ),
        )
    return citations


def _to_query_response(
    query: Query,
    citations: list[CitationResponse],
    wiki_worthiness: WikiWorthinessScore | None = None,
) -> QueryResponse:
    """Project a persisted :class:`Query` plus citations into a :class:`QueryResponse`."""
    return QueryResponse(
        id=query.id,
        question=query.question,
        answer=query.answer,
        confidence=query.confidence,
        source_article_ids=query.source_article_ids,
        related_article_ids=query.related_article_ids,
        filed_back=query.filed_back,
        filed_article_id=query.filed_article_id,
        created_at=query.created_at,
        conversation_id=query.conversation_id,
        turn_index=query.turn_index,
        citations=citations,
        wiki_worthiness=wiki_worthiness,
    )


def _to_conversation_response(conversation: Conversation, fork_count: int = 0) -> ConversationResponse:
    """Project a Conversation row into the API response shape."""
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        filed_article_id=conversation.filed_article_id,
        parent_conversation_id=conversation.parent_conversation_id,
        forked_at_turn_index=conversation.forked_at_turn_index,
        fork_count=fork_count,
    )


async def _count_forks(conversation_id: str, session: AsyncSession) -> int:
    """Count child conversations (forks) for a given conversation."""
    result = await session.execute(select(func.count()).where(Conversation.parent_conversation_id == conversation_id))
    return result.scalar_one()


async def _materialize_thread(
    conversation: Conversation,
    session: AsyncSession,
) -> list[Query]:
    """Materialize the full thread for a forked conversation.

    Walks the parent chain recursively, collecting ancestor turns before
    forked_at_turn_index from each ancestor, then appends this conversation's
    own turns. Returns a flat list ordered by turn_index.
    """
    # Collect ancestor chain (oldest first)
    ancestors: list[tuple[str, int]] = []  # (conversation_id, forked_at_turn_index)
    current = conversation
    while current.parent_conversation_id is not None and current.forked_at_turn_index is not None:
        ancestors.append((current.parent_conversation_id, current.forked_at_turn_index))
        parent = await session.get(Conversation, current.parent_conversation_id)
        if parent is None:
            break
        current = parent
    ancestors.reverse()  # oldest ancestor first

    # Collect turns from ancestors
    all_turns: list[Query] = []
    for ancestor_id, fork_at in ancestors:
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == ancestor_id)
            .where(Query.turn_index < fork_at)
            .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
        )
        all_turns.extend(result.scalars().all())

    # Add this conversation's own turns
    result = await session.execute(
        select(Query).where(Query.conversation_id == conversation.id).order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
    )
    all_turns.extend(result.scalars().all())

    return all_turns


class QueryService:
    """Orchestrate wiki Q&A, query history, and answer file-back."""

    def __init__(self) -> None:
        self._qa_agent = QAAgent()

    async def ask(self, request: QueryRequest, session: AsyncSession, user_id: str) -> AskResponse:
        """Ask a question against the wiki and persist the result.

        Conversation-aware: passes request.conversation_id to the agent.
        Returns both the new query (with full citation chain) and the
        parent conversation.

        Args:
            request: The query request with question and options.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            :class:`AskResponse` with the new query and its parent conversation.
        """
        query, conversation, wiki_worthiness = await self._qa_agent.answer(request, session, user_id=user_id)
        citations = await _build_citations(query, session, user_id=user_id)
        return AskResponse(
            query=_to_query_response(query, citations, wiki_worthiness=wiki_worthiness),
            conversation=_to_conversation_response(conversation),
        )

    async def ask_stream(
        self,
        request: QueryRequest,
        session: AsyncSession,
        user_id: str,
    ) -> AsyncIterator[str]:
        """Stream an answer token-by-token via SSE events.

        Delegates to :meth:`QAAgent.answer_stream` for LLM streaming and
        persistence, then wraps each value in the SSE event protocol.

        SSE events emitted:
        - ``event: chunk`` with ``{"text": "..."}`` for each text delta
        - ``event: done`` with the full ``AskResponse`` JSON after completion
        - ``event: error`` with ``{"code": "...", "message": "..."}`` on failure

        Args:
            request: The query request.
            session: Async database session.
            user_id: User ID for data isolation.

        Yields:
            SSE-formatted event strings.
        """
        try:
            async for item in self._qa_agent.answer_stream(request, session, user_id=user_id):
                if isinstance(item, str):
                    yield (f"event: chunk\ndata: {json.dumps({'text': item})}\n\n")
                else:
                    # Final tuple: (Query, Conversation, WikiWorthinessScore | None)
                    query_record, conversation, wiki_worthiness = item
                    citations = await _build_citations(query_record, session, user_id=user_id)
                    done_payload = AskResponse(
                        query=_to_query_response(query_record, citations, wiki_worthiness=wiki_worthiness),
                        conversation=_to_conversation_response(conversation),
                    )
                    yield (f"event: done\ndata: {done_payload.model_dump_json()}\n\n")
        except Exception:  # Intentional broad catch — SSE must send error event, not crash
            log.exception("SSE stream failed")
            error_payload = json.dumps({"code": "stream_failed", "message": "Internal server error"})
            yield f"event: error\ndata: {error_payload}\n\n"

    async def query_history(self, session: AsyncSession, user_id: str, limit: int = 50) -> list[Query]:
        """List past queries ordered by most recent first.

        Args:
            session: Async database session.
            limit: Maximum number of results.
            user_id: User ID for data isolation.

        Returns:
            List of Query records.
        """
        stmt = select(Query).order_by(Query.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
        if user_id:
            stmt = stmt.where(Query.user_id == user_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_conversations(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
    ) -> list[ConversationSummary]:
        """List conversations ordered by most-recently-updated first.

        Each summary includes turn_count for the sidebar UI.

        Args:
            session: Async database session.
            limit: Maximum number of results.
            user_id: User ID for data isolation.

        Returns:
            List of :class:`ConversationSummary` ordered by updated_at descending.
        """
        conv_stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        if user_id:
            conv_stmt = conv_stmt.where(Conversation.user_id == user_id)
        result = await session.execute(conv_stmt)
        conversations = list(result.scalars().all())

        if not conversations:
            return []

        # Compute turn counts in one query
        ids = [c.id for c in conversations]
        count_rows = await session.execute(
            select(Query.conversation_id, Query.id).where(Query.conversation_id.in_(ids))  # type: ignore[union-attr]
        )
        counts: dict[str, int] = {}
        for conv_id, _qid in count_rows.all():
            counts[conv_id] = counts.get(conv_id, 0) + 1

        # Compute fork counts in one query
        fork_count_rows = await session.execute(
            select(Conversation.parent_conversation_id, Conversation.id).where(
                Conversation.parent_conversation_id.in_(ids)  # type: ignore[union-attr]
            )
        )
        fork_counts: dict[str, int] = {}
        for parent_id, _child_id in fork_count_rows.all():
            fork_counts[parent_id] = fork_counts.get(parent_id, 0) + 1

        return [
            ConversationSummary(
                id=c.id,
                title=c.title,
                created_at=c.created_at,
                updated_at=c.updated_at,
                filed_article_id=c.filed_article_id,
                parent_conversation_id=c.parent_conversation_id,
                forked_at_turn_index=c.forked_at_turn_index,
                fork_count=fork_counts.get(c.id, 0),
                turn_count=counts.get(c.id, 0),
            )
            for c in conversations
        ]

    async def get_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> ConversationDetail:
        """Return a single conversation with all its queries ordered by turn_index.

        For forked conversations, materializes the full thread by walking the
        parent chain and collecting ancestor turns before the fork point.

        Args:
            conversation_id: The conversation UUID to retrieve.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            :class:`ConversationDetail` with conversation metadata and ordered queries.

        Raises:
            NotFoundError: If the conversation is not found.
        """
        conversation = await session.get(Conversation, conversation_id)
        msg = "Conversation not found"
        if conversation is None:
            raise NotFoundError(msg)
        if user_id and conversation.user_id != user_id:
            raise NotFoundError(msg)

        # Use thread materialization for forked conversations
        if conversation.parent_conversation_id is not None:
            queries = await _materialize_thread(conversation, session)
        else:
            result = await session.execute(
                select(Query).where(Query.conversation_id == conversation_id).order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
            )
            queries = list(result.scalars().all())

        fork_count = await _count_forks(conversation_id, session)

        # Build full QueryResponse for each turn (with citations)
        query_responses: list[QueryResponse] = []
        for q in queries:
            citations = await _build_citations(q, session, user_id=user_id)
            query_responses.append(_to_query_response(q, citations))

        return ConversationDetail(
            conversation=_to_conversation_response(conversation, fork_count),
            queries=query_responses,
        )

    async def file_back_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> FileBackResult:
        """File a whole conversation back to the wiki.

        Delegates to QAAgent._file_back_thread which handles create-vs-update
        based on Conversation.filed_article_id. Does not commit — the FastAPI
        session dependency (commit-on-success) persists the staged changes
        when the route handler returns.

        Args:
            conversation_id: The conversation UUID to file back.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            FileBackResult with article metadata and a was_update flag.
        """
        # Ownership check before delegating to QAAgent
        conversation = await session.get(Conversation, conversation_id)
        msg = "Conversation not found"
        if conversation is None:
            raise NotFoundError(msg)
        if user_id and conversation.user_id != user_id:
            raise NotFoundError(msg)

        article, was_update = await self._qa_agent._file_back_thread(conversation_id, session, user_id=user_id)
        return FileBackResult(
            article=FileBackArticleRef(id=article.id, slug=article.slug, title=article.title),
            was_update=was_update,
        )

    async def fork_conversation(
        self,
        conversation_id: str,
        fork_request: ForkRequest,
        session: AsyncSession,
        user_id: str,
    ) -> AskResponse:
        """Fork a conversation at a specific turn and ask a new question.

        Creates a new Conversation that shares turns 0..turn_index-1 with
        the parent by reference (via parent_conversation_id and
        forked_at_turn_index). Then runs the QA agent on the new question
        within the fork.

        Args:
            conversation_id: The parent conversation UUID to fork from.
            fork_request: Contains turn_index (fork point) and new_question.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            :class:`AskResponse` with the new query and the forked conversation.

        Raises:
            NotFoundError: If the parent conversation is not found.
            QueryError: If turn_index is invalid.
        """
        parent = await session.get(Conversation, conversation_id)
        msg = "Conversation not found"
        if parent is None:
            raise NotFoundError(msg)
        if user_id and parent.user_id != user_id:
            raise NotFoundError(msg)

        # Validate turn_index: must be >= 0 and there must be at least that
        # many turns in the parent (or its materialized thread)
        if fork_request.turn_index < 0:
            msg = "turn_index must be >= 0"
            raise QueryError(msg)

        # Create the fork conversation
        title_max = self._qa_agent.settings.qa.conversation_title_max_chars
        fork_conv = Conversation(
            title=fork_request.new_question[:title_max],
            parent_conversation_id=conversation_id,
            forked_at_turn_index=fork_request.turn_index,
            user_id=user_id,
        )
        session.add(fork_conv)
        await session.flush()

        # Now ask the new question in the forked conversation
        ask_request = QueryRequest(
            question=fork_request.new_question,
            conversation_id=fork_conv.id,
        )
        query, conversation, wiki_worthiness = await self._qa_agent.answer(ask_request, session, user_id=user_id)
        citations = await _build_citations(query, session, user_id=user_id)
        fork_count = await _count_forks(fork_conv.id, session)
        return AskResponse(
            query=_to_query_response(query, citations, wiki_worthiness=wiki_worthiness),
            conversation=_to_conversation_response(conversation, fork_count),
        )

    async def file_back_selection(
        self,
        request: FileBackSelectionRequest,
        session: AsyncSession,
        user_id: str,
    ) -> FileBackResult:
        """File selected turns from one or more conversations back to the wiki.

        Validates that all referenced conversations and turns exist, builds
        the selected-turn list, serializes to markdown, writes to disk, and
        creates an Article row.

        Args:
            request: The file-back selection request with turn selections and optional title.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            FileBackResult with article metadata.

        Raises:
            QueryError: If selections are empty or invalid.
            NotFoundError: If a conversation is not found.
        """
        if not request.selections:
            msg = "No selections provided"
            raise QueryError(msg)

        selected_turns: list[SelectedTurn] = []

        for selection in request.selections:
            conversation = await session.get(Conversation, selection.conversation_id)
            if conversation is None:
                msg = f"Conversation not found: {selection.conversation_id}"
                raise NotFoundError(msg)
            if user_id and conversation.user_id != user_id:
                msg = f"Conversation not found: {selection.conversation_id}"
                raise NotFoundError(msg)

            if not selection.turn_indices:
                continue

            result = await session.execute(
                select(Query)
                .where(Query.conversation_id == selection.conversation_id)
                .where(Query.turn_index.in_(selection.turn_indices))  # type: ignore[attr-defined]
                .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
            )
            queries = list(result.scalars().all())

            found_indices = {q.turn_index for q in queries}
            missing = set(selection.turn_indices) - found_indices
            if missing:
                msg = f"Turn indices {sorted(missing)} not found in conversation {selection.conversation_id}"
                raise QueryError(msg)

            selected_turns.extend(SelectedTurn(conversation=conversation, query=query) for query in queries)

        if not selected_turns:
            msg = "No turns selected"
            raise QueryError(msg)

        markdown = serialize_selected_turns_to_markdown(selected_turns, title=request.title)

        settings = get_settings()
        wiki_dir = Path(settings.data_dir) / "wiki"
        if user_id:
            wiki_dir = wiki_dir / user_id
        wiki_dir = wiki_dir / "qa-answers"
        await asyncio.to_thread(wiki_dir.mkdir, parents=True, exist_ok=True)

        now = utcnow_naive()
        effective_title = request.title or selected_turns[0].conversation.title

        slug = str(uuid.uuid4())
        file_path = wiki_dir / f"{slug}.md"
        await asyncio.to_thread(file_path.write_text, markdown, encoding="utf-8")

        article = Article(
            slug=slug,
            title=effective_title,
            file_path=f"qa-answers/{slug}.md",
            summary=(selected_turns[0].query.answer[:200] if selected_turns else None),
            confidence=None,
            page_type=PageType.ANSWER,
            created_at=now,
            updated_at=now,
            user_id=user_id,
        )
        session.add(article)

        # Mark selected turns as filed back
        for selected in selected_turns:
            selected.query.filed_back = True
            selected.query.filed_article_id = article.id
            session.add(selected.query)

        await session.commit()
        await session.refresh(article)

        # Index for full-text search
        await fts_index_article(session, article.id, article.title, markdown)
        await session.commit()

        return FileBackResult(
            article=FileBackArticleRef(id=article.id, slug=article.slug, title=article.title),
        )

    async def export_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> Response:
        """Export conversation as markdown. Read-only, no DB writes.

        Fetches the conversation and its queries, serializes them using the
        same serializer as file-back, and returns the markdown as a
        downloadable response.

        Args:
            conversation_id: The conversation UUID to export.
            session: Async database session.
            user_id: User ID for data isolation.

        Returns:
            :class:`Response` with ``text/markdown`` content and a
            ``Content-Disposition`` header for download.

        Raises:
            NotFoundError: If the conversation is not found.
        """
        conversation = await session.get(Conversation, conversation_id)
        msg = "Conversation not found"
        if conversation is None:
            raise NotFoundError(msg)
        if user_id and conversation.user_id != user_id:
            raise NotFoundError(msg)

        result = await session.execute(
            select(Query).where(Query.conversation_id == conversation_id).order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
        )
        queries = list(result.scalars().all())

        markdown = serialize_conversation_to_markdown(conversation, queries)

        filename = _sanitize_filename(conversation.title) + ".md"
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


_FILENAME_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_\- ]")


def _sanitize_filename(title: str) -> str:
    """Sanitize a conversation title for use as a download filename.

    Replaces non-alphanumeric characters (except hyphens, underscores, and
    spaces) with hyphens, collapses runs of hyphens, and strips leading/
    trailing hyphens.

    Args:
        title: Raw conversation title.

    Returns:
        A filesystem-safe filename (without extension).
    """
    sanitized = _FILENAME_UNSAFE_RE.sub("-", title)
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized.strip("- ") or "conversation"


@functools.lru_cache(maxsize=1)
def get_query_service() -> QueryService:
    """Return a singleton QueryService instance for FastAPI dependency injection."""
    return QueryService()
