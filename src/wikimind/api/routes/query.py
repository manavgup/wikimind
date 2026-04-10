"""Endpoints for asking questions, browsing conversations, and filing answers back."""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import (
    AskResponse,
    ConversationDetail,
    ConversationSummary,
    QueryRequest,
)
from wikimind.services.query import QueryService, get_query_service

router = APIRouter()


@router.post("", response_model=AskResponse)
async def ask(
    request: QueryRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Ask a question against the wiki and receive an answer with citations.

    If request.conversation_id is None, a new conversation is created.
    Otherwise the question is appended as a new turn in the existing
    conversation.
    """
    return await service.ask(request, session)


@router.get("/history")
async def query_history(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """List past queries (legacy endpoint — UI uses /conversations instead)."""
    return await service.query_history(session, limit=limit)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """List conversations ordered by most recently updated first."""
    return await service.list_conversations(session, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Return a single conversation with all its turns."""
    return await service.get_conversation(conversation_id, session)


@router.get(
    "/conversations/{conversation_id}/export",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {"schema": {"type": "string"}}}}},
)
async def export_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
) -> Response:
    """Export a conversation as standalone markdown. Pure read, no DB writes."""
    return await service.export_conversation(conversation_id, session)


@router.post("/conversations/{conversation_id}/file-back")
async def file_back_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """File the entire conversation back to the wiki as a single article."""
    return await service.file_back_conversation(conversation_id, session)
