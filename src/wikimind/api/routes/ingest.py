"""Endpoints for ingesting sources (URLs, PDFs, text) into the knowledge base."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.ingest.service import IngestService
from wikimind.models import IngestTextRequest, IngestURLRequest, Source

router = APIRouter()
ingest_service = IngestService()


@router.post("/url", response_model=Source)
async def ingest_url(
    request: IngestURLRequest,
    session: AsyncSession = Depends(get_session),
):
    """Ingest a web URL or YouTube video."""
    try:
        source = await ingest_service.ingest_url(request.url, session)
        return source
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/pdf", response_model=Source)
async def ingest_pdf(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload and ingest a PDF."""
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    contents = await file.read()
    source = await ingest_service.ingest_pdf(contents, file.filename, session)
    return source


@router.post("/text", response_model=Source)
async def ingest_text(
    request: IngestTextRequest,
    session: AsyncSession = Depends(get_session),
):
    """Ingest raw text or a note."""
    source = await ingest_service.ingest_text(request.content, request.title, session)
    return source


@router.get("/sources")
async def list_sources(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List all ingested sources."""
    query = select(Source).offset(offset).limit(limit)
    if status:
        query = query.where(Source.status == status)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get source by ID."""
    source = await session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a source by ID."""
    source = await session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await session.delete(source)
    await session.commit()
    return {"deleted": source_id}
