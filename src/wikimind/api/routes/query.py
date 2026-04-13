"""Endpoints for asking questions, browsing conversations, and filing answers back."""

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session, get_session_factory
from wikimind.models import (
    AskResponse,
    ConversationDetail,
    ConversationSummary,
    FileBackSelectionRequest,
    ForkRequest,
    QueryRequest,
)
from wikimind.services.query import QueryService, get_query_service

log = structlog.get_logger()

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


@router.post("/stream")
async def ask_stream(
    request: QueryRequest,
    service: QueryService = Depends(get_query_service),
) -> StreamingResponse:
    """Stream an answer token-by-token via Server-Sent Events.

    Returns SSE events: ``chunk`` (text deltas), ``done`` (final AskResponse),
    or ``error``. The Query row is persisted only after the stream completes
    successfully. Client disconnect aborts without persisting.
    """

    async def _event_generator() -> AsyncIterator[str]:
        async with get_session_factory()() as session:
            try:
                async for event in service.ask_stream(request, session):  # type: ignore[arg-type]
                    yield event
            except asyncio.CancelledError:
                log.info("SSE client disconnected, aborting stream")
                await session.rollback()
            except Exception as e:
                log.error("SSE stream error", error=str(e))
                error_payload = json.dumps({"code": "stream_failed", "message": str(e)})
                yield f"event: error\ndata: {error_payload}\n\n"
                await session.rollback()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post("/conversations/file-back")
async def file_back_selection(
    request: FileBackSelectionRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """File selected turns from one or more conversations back to the wiki as a single article."""
    return await service.file_back_selection(request, session)


@router.post("/conversations/{conversation_id}/file-back")
async def file_back_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """File the entire conversation back to the wiki as a single article."""
    return await service.file_back_conversation(conversation_id, session)


@router.post("/conversations/{conversation_id}/fork", response_model=AskResponse)
async def fork_conversation(
    conversation_id: str,
    fork_request: ForkRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Fork a conversation at a specific turn with a new question.

    Creates a new conversation that shares turns 0..turn_index-1 with the
    parent by reference. The original branch is preserved immutably.
    """
    return await service.fork_conversation(conversation_id, fork_request, session)
