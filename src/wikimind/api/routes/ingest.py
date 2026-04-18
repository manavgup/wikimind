"""Endpoints for ingesting sources (URLs, PDFs, text) into the knowledge base."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import IngestTextRequest, IngestURLRequest, Source
from wikimind.services.ingest import IngestService, get_ingest_service

router = APIRouter()


@router.post("/url", response_model=Source)
async def ingest_url(
    request: IngestURLRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str | None = Depends(get_current_user_id),
):
    """Ingest a web URL or YouTube video."""
    return await service.ingest_url(request.url, session, auto_compile=request.auto_compile, user_id=user_id)


@router.post("/pdf", response_model=Source)
async def ingest_pdf(
    file: UploadFile = File(...),
    auto_compile: bool = True,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str | None = Depends(get_current_user_id),
):
    """Upload and ingest a PDF.

    The ``auto_compile`` query parameter (default ``True``) controls whether the
    source is enqueued for background compilation immediately after upload.
    """
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    return await service.ingest_pdf(contents, file.filename, session, auto_compile=auto_compile, user_id=user_id)


@router.post("/text", response_model=Source)
async def ingest_text(
    request: IngestTextRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str | None = Depends(get_current_user_id),
):
    """Ingest raw text or a note."""
    return await service.ingest_text(
        request.content,
        request.title,
        session,
        auto_compile=request.auto_compile,
        user_id=user_id,
    )


@router.get("/sources")
async def list_sources(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str | None = Depends(get_current_user_id),
):
    """List all ingested sources."""
    return await service.list_sources(session, status=status, limit=limit, offset=offset, user_id=user_id)


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Get source by ID."""
    return await service.get_source(source_id, session)


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Delete a source by ID."""
    return await service.delete_source(source_id, session)
