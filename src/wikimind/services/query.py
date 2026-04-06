"""Handle question answering against the wiki and file-back to articles.

Wraps the QA agent, manages query persistence, and coordinates the
file-back workflow that promotes Q&A answers into wiki articles.
"""

import json

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.qa_agent import QAAgent
from wikimind.models import Query, QueryRequest, QueryResult


class QueryService:
    """Orchestrate wiki Q&A, query history, and answer file-back."""

    def __init__(self) -> None:
        self._qa_agent = QAAgent()

    async def ask(self, request: QueryRequest, session: AsyncSession) -> Query:
        """Ask a question against the wiki and persist the result.

        Args:
            request: The query request with question and options.
            session: Async database session.

        Returns:
            The persisted Query record with answer.
        """
        return await self._qa_agent.answer(request, session)

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
