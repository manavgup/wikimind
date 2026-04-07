"""Handle question answering against the wiki and file-back to articles.

Wraps the QA agent, manages query persistence, and coordinates the
file-back workflow that promotes Q&A answers into wiki articles.
Q&A responses are enriched with full Answer → Article → Source citation
chains so callers can trace every answer back to the raw source it came
from.
"""

import json

import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    CitationArticleRef,
    CitationResponse,
    Query,
    QueryRequest,
    QueryResponse,
    QueryResult,
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
        citations=citations,
    )


class QueryService:
    """Orchestrate wiki Q&A, query history, and answer file-back."""

    def __init__(self) -> None:
        self._qa_agent = QAAgent()

    async def ask(self, request: QueryRequest, session: AsyncSession) -> QueryResponse:
        """Ask a question against the wiki and persist the result.

        After the QA agent answers and persists the :class:`Query`
        record, this method resolves each cited article title back to
        its :class:`Article` row and then to the underlying
        :class:`Source` records, returning a fully expanded
        Answer → Article → Source citation chain.

        Args:
            request: The query request with question and options.
            session: Async database session.

        Returns:
            :class:`QueryResponse` with answer text and resolved citations.
        """
        query = await self._qa_agent.answer(request, session)
        citations = await _build_citations(query, session)
        return _to_query_response(query, citations)

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

    async def file_back(self, query_id: str, session: AsyncSession) -> dict[str, object]:
        """Promote a past Q&A answer into a wiki article.

        Args:
            query_id: The query UUID to file back.
            session: Async database session.

        Returns:
            Dict confirming the file-back with the new article ID.

        Raises:
            HTTPException: If the query is not found.
        """
        query = await session.get(Query, query_id)
        if not query:
            raise HTTPException(status_code=404, detail="Query not found")

        result = QueryResult(
            answer=query.answer,
            confidence=query.confidence or "medium",
            sources=json.loads(query.source_article_ids or "[]"),
            related_articles=json.loads(query.related_article_ids or "[]"),
        )

        article_id = await self._qa_agent._file_back(query.question, result, session)
        query.filed_back = True
        query.filed_article_id = article_id
        session.add(query)
        await session.commit()

        return {"filed": True, "article_id": article_id}


_query_service: QueryService | None = None


def get_query_service() -> QueryService:
    """Return a singleton QueryService instance for FastAPI dependency injection."""
    global _query_service
    if _query_service is None:
        _query_service = QueryService()
    return _query_service
