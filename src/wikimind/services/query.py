"""Handle question answering against the wiki and file-back to articles.

Wraps the QA agent, manages query persistence, and coordinates the
file-back workflow that promotes Q&A answers into wiki articles.
Q&A responses are enriched with full Answer → Article → Source citation
chains so callers can trace every answer back to the raw source it came
from.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import structlog
from fastapi import HTTPException
from fastapi.responses import Response
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.conversation_serializer import (
    SelectedTurn,
    serialize_conversation_to_markdown,
    serialize_selected_turns_to_markdown,
)
from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    AskResponse,
    CitationArticleRef,
    CitationResponse,
    Conversation,
    ConversationDetail,
    ConversationResponse,
    ConversationSummary,
    FileBackSelectionRequest,
    ForkRequest,
    PageType,
    Query,
    QueryRequest,
    QueryResponse,
    Source,
    SourceResponse,
)

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


async def _build_citations(query: Query, session: AsyncSession) -> list[CitationResponse]:
    """Resolve a Q&A record into a full citation chain.

    Walks ``Query.source_article_ids`` (which the QA agent populates with
    article titles), looks up each cited :class:`Article` by exact title
    match, then fetches every :class:`Source` referenced by the
    article's ``source_ids`` JSON column. Articles that cannot be
    resolved are skipped.

    Args:
        query: The persisted Query record.
        session: Async database session.

    Returns:
        Resolved citation list with full source provenance for each
        cited article.
    """
    titles = _parse_article_titles(query.source_article_ids)
    if not titles:
        return []

    article_result = await session.execute(select(Article).where(Article.title.in_(titles)))  # type: ignore[attr-defined]
    articles_by_title = {a.title: a for a in article_result.scalars().all()}

    citations: list[CitationResponse] = []
    for title in titles:
        article = articles_by_title.get(title)
        if article is None:
            continue
        source_ids = _parse_source_ids(article.source_ids)
        sources: list[Source] = []
        if source_ids:
            src_result = await session.execute(
                select(Source).where(Source.id.in_(source_ids)),  # type: ignore[attr-defined]
            )
            by_id = {s.id: s for s in src_result.scalars().all()}
            sources = [by_id[sid] for sid in source_ids if sid in by_id]
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
            ),
        )
    return citations


def _to_query_response(query: Query, citations: list[CitationResponse]) -> QueryResponse:
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

    async def ask(self, request: QueryRequest, session: AsyncSession) -> AskResponse:
        """Ask a question against the wiki and persist the result.

        Conversation-aware: passes request.conversation_id to the agent.
        Returns both the new query (with full citation chain) and the
        parent conversation.

        Args:
            request: The query request with question and options.
            session: Async database session.

        Returns:
            :class:`AskResponse` with the new query and its parent conversation.
        """
        query, conversation = await self._qa_agent.answer(request, session)
        citations = await _build_citations(query, session)
        return AskResponse(
            query=_to_query_response(query, citations),
            conversation=_to_conversation_response(conversation),
        )

    async def ask_stream(
        self,
        request: QueryRequest,
        session: AsyncSession,
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

        Yields:
            SSE-formatted event strings.
        """
        try:
            async for item in self._qa_agent.answer_stream(request, session):
                if isinstance(item, str):
                    yield (f"event: chunk\ndata: {json.dumps({'text': item})}\n\n")
                else:
                    # Final tuple: (Query, Conversation)
                    query_record, conversation = item
                    citations = await _build_citations(query_record, session)
                    done_payload = AskResponse(
                        query=_to_query_response(query_record, citations),
                        conversation=_to_conversation_response(conversation),
                    )
                    yield (f"event: done\ndata: {done_payload.model_dump_json()}\n\n")
        except Exception as e:
            log.error("Stream failed", error=str(e))
            error_payload = json.dumps({"code": "stream_failed", "message": str(e)})
            yield f"event: error\ndata: {error_payload}\n\n"

    async def query_history(self, session: AsyncSession, limit: int = 50) -> list[Query]:
        """List past queries ordered by most recent first.

        Args:
            session: Async database session.
            limit: Maximum number of results.

        Returns:
            List of Query records.
        """
        result = await session.execute(
            select(Query).order_by(Query.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
        )
        return list(result.scalars().all())

    async def list_conversations(
        self,
        session: AsyncSession,
        limit: int = 50,
    ) -> list[ConversationSummary]:
        """List conversations ordered by most-recently-updated first.

        Each summary includes turn_count for the sidebar UI.

        Args:
            session: Async database session.
            limit: Maximum number of results.

        Returns:
            List of :class:`ConversationSummary` ordered by updated_at descending.
        """
        result = await session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        conversations = list(result.scalars().all())

        if not conversations:
            return []

        # Compute turn counts in one query
        ids = [c.id for c in conversations]
        count_rows = await session.execute(
            select(Query.conversation_id, Query.id).where(Query.conversation_id.in_(ids))  # type: ignore[arg-type, union-attr]
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
    ) -> ConversationDetail:
        """Return a single conversation with all its queries ordered by turn_index.

        For forked conversations, materializes the full thread by walking the
        parent chain and collecting ancestor turns before the fork point.

        Args:
            conversation_id: The conversation UUID to retrieve.
            session: Async database session.

        Returns:
            :class:`ConversationDetail` with conversation metadata and ordered queries.

        Raises:
            HTTPException: 404 if the conversation is not found.
        """
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

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
            citations = await _build_citations(q, session)
            query_responses.append(_to_query_response(q, citations))

        return ConversationDetail(
            conversation=_to_conversation_response(conversation, fork_count),
            queries=query_responses,
        )

    async def file_back_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> dict[str, object]:
        """File a whole conversation back to the wiki.

        Delegates to QAAgent._file_back_thread which handles create-vs-update
        based on Conversation.filed_article_id. Does not commit — the FastAPI
        session dependency (commit-on-success) persists the staged changes
        when the route handler returns.

        Args:
            conversation_id: The conversation UUID to file back.
            session: Async database session.

        Returns:
            Dict with article metadata (id, slug, title) and a was_update flag.
        """
        article, was_update = await self._qa_agent._file_back_thread(conversation_id, session)
        return {
            "article": {"id": article.id, "slug": article.slug, "title": article.title},
            "was_update": was_update,
        }

    async def fork_conversation(
        self,
        conversation_id: str,
        fork_request: ForkRequest,
        session: AsyncSession,
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

        Returns:
            :class:`AskResponse` with the new query and the forked conversation.

        Raises:
            HTTPException: 404 if the parent conversation is not found.
            HTTPException: 400 if turn_index is invalid.
        """
        parent = await session.get(Conversation, conversation_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Validate turn_index: must be >= 0 and there must be at least that
        # many turns in the parent (or its materialized thread)
        if fork_request.turn_index < 0:
            raise HTTPException(status_code=400, detail="turn_index must be >= 0")

        # Create the fork conversation
        title_max = self._qa_agent.settings.qa.conversation_title_max_chars
        fork_conv = Conversation(
            title=fork_request.new_question[:title_max],
            parent_conversation_id=conversation_id,
            forked_at_turn_index=fork_request.turn_index,
        )
        session.add(fork_conv)
        await session.flush()

        # Now ask the new question in the forked conversation
        ask_request = QueryRequest(
            question=fork_request.new_question,
            conversation_id=fork_conv.id,
        )
        query, conversation = await self._qa_agent.answer(ask_request, session)
        citations = await _build_citations(query, session)
        fork_count = await _count_forks(fork_conv.id, session)
        return AskResponse(
            query=_to_query_response(query, citations),
            conversation=_to_conversation_response(conversation, fork_count),
        )

    async def file_back_selection(
        self,
        request: FileBackSelectionRequest,
        session: AsyncSession,
    ) -> dict[str, object]:
        """File selected turns from one or more conversations back to the wiki.

        Validates that all referenced conversations and turns exist, builds
        the selected-turn list, serializes to markdown, writes to disk, and
        creates an Article row.

        Args:
            request: The file-back selection request with turn selections and optional title.
            session: Async database session.

        Returns:
            Dict with article metadata (id, slug, title).

        Raises:
            HTTPException: 400 if selections are empty or invalid.
            HTTPException: 404 if a conversation is not found.
        """
        if not request.selections:
            raise HTTPException(status_code=400, detail="No selections provided")

        selected_turns: list[SelectedTurn] = []

        for selection in request.selections:
            conversation = await session.get(Conversation, selection.conversation_id)
            if conversation is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Conversation not found: {selection.conversation_id}",
                )

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
                raise HTTPException(
                    status_code=400,
                    detail=(f"Turn indices {sorted(missing)} not found in conversation {selection.conversation_id}"),
                )

            for query in queries:
                selected_turns.append(SelectedTurn(conversation=conversation, query=query))

        if not selected_turns:
            raise HTTPException(status_code=400, detail="No turns selected")

        markdown = serialize_selected_turns_to_markdown(selected_turns, title=request.title)

        settings = get_settings()
        wiki_dir = Path(settings.data_dir) / "wiki" / "qa-answers"
        wiki_dir.mkdir(parents=True, exist_ok=True)

        now = utcnow_naive()
        effective_title = request.title or selected_turns[0].conversation.title

        slug = str(uuid.uuid4())
        file_path = wiki_dir / f"{slug}.md"
        file_path.write_text(markdown, encoding="utf-8")

        article = Article(
            slug=slug,
            title=effective_title,
            file_path=str(file_path),
            summary=(selected_turns[0].query.answer[:200] if selected_turns else None),
            confidence=None,
            page_type=PageType.ANSWER,
            created_at=now,
            updated_at=now,
        )
        session.add(article)

        # Mark selected turns as filed back
        for selected in selected_turns:
            selected.query.filed_back = True
            selected.query.filed_article_id = article.id
            session.add(selected.query)

        await session.commit()
        await session.refresh(article)

        return {
            "article": {"id": article.id, "slug": article.slug, "title": article.title},
        }

    async def export_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> Response:
        """Export conversation as markdown. Read-only, no DB writes.

        Fetches the conversation and its queries, serializes them using the
        same serializer as file-back, and returns the markdown as a
        downloadable response.

        Args:
            conversation_id: The conversation UUID to export.
            session: Async database session.

        Returns:
            :class:`Response` with ``text/markdown`` content and a
            ``Content-Disposition`` header for download.

        Raises:
            HTTPException: 404 if the conversation is not found.
        """
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

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


_query_service: QueryService | None = None


def get_query_service() -> QueryService:
    """Return a singleton QueryService instance for FastAPI dependency injection."""
    global _query_service
    if _query_service is None:
        _query_service = QueryService()
    return _query_service
