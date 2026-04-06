"""Endpoints for asking questions against the wiki and filing answers back."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.engine.qa_agent import QAAgent
from wikimind.models import Query, QueryRequest, QueryResult

router = APIRouter()
qa_agent = QAAgent()


@router.post("")
async def ask(
    request: QueryRequest,
    session: AsyncSession = Depends(get_session),
):
    """Ask a question against the wiki."""
    query = await qa_agent.answer(request, session)
    return query


@router.get("/history")
async def query_history(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List past queries."""
    result = await session.execute(select(Query).order_by(Query.created_at.desc()).limit(limit))  # type: ignore[attr-defined]
    return result.scalars().all()


@router.post("/{query_id}/file-back")
async def file_back(
    query_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Save a past answer as a wiki article."""
    query = await session.get(Query, query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")

    result = QueryResult(
        answer=query.answer,
        confidence=query.confidence or "medium",
        sources=json.loads(query.source_article_ids or "[]"),
        related_articles=json.loads(query.related_article_ids or "[]"),
    )

    article_id = await qa_agent._file_back(query.question, result, session)
    query.filed_back = True
    query.filed_article_id = article_id
    session.add(query)
    await session.commit()

    return {"filed": True, "article_id": article_id}
