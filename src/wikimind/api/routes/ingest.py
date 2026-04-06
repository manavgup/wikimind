"""Endpoints for ingesting sources (URLs, PDFs, text) into the knowledge base."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import IngestTextRequest, IngestURLRequest, Source
from wikimind.services.ingest import IngestService, get_ingest_service

router = APIRouter()


@router.post("/url", response_model=Source)
async def ingest_url(
    request: IngestURLRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Ingest a web URL or YouTube video."""
    return await service.ingest_url(request.url, session)


@router.post("/pdf", response_model=Source)
async def ingest_pdf(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Upload and ingest a PDF."""
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    return await service.ingest_pdf(contents, file.filename, session)


@router.post("/text", response_model=Source)
async def ingest_text(
    request: IngestTextRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Ingest raw text or a note."""
    return await service.ingest_text(request.content, request.title, session)


@router.get("/sources")
async def list_sources(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """List all ingested sources."""
    return await service.list_sources(session, status=status, limit=limit, offset=offset)


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
