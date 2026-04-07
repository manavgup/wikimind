"""Endpoints for asking questions against the wiki and filing answers back."""

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import QueryRequest, QueryResponse
from wikimind.services.query import QueryService, get_query_service

router = APIRouter()


@router.post("", response_model=QueryResponse)
async def ask(
    request: QueryRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Ask a question against the wiki and receive an answer with citations."""
    return await service.ask(request, session)


@router.get("/history")
async def query_history(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """List past queries."""
    return await service.query_history(session, limit=limit)


@router.post("/{query_id}/file-back")
async def file_back(
    query_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Save a past answer as a wiki article."""
    return await service.file_back(query_id, session)
