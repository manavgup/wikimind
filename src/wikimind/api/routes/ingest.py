"""Endpoints for ingesting sources (URLs, PDFs, text) into the knowledge base."""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import IngestTextRequest, IngestURLRequest, Source
from wikimind.services.ingest import IngestService, get_ingest_service
from wikimind.storage import find_original_sibling, resolve_raw_path

router = APIRouter()


@router.post("/url", response_model=Source)
async def ingest_url(
    request: IngestURLRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Ingest a web URL or YouTube video."""
    return await service.ingest_url(request.url, session, auto_compile=request.auto_compile, user_id=user_id)


@router.post("/pdf", response_model=Source)
async def ingest_pdf(
    file: UploadFile = File(...),
    auto_compile: bool = True,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
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
    user_id: str = Depends(get_current_user_id),
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
    user_id: str = Depends(get_current_user_id),
):
    """List all ingested sources."""
    return await service.list_sources(session, status=status, limit=limit, offset=offset, user_id=user_id)


@router.get("/sources/{source_id}", response_model=Source)
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Get source by ID."""
    return await service.get_source(source_id, session, user_id=user_id)


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a source by ID."""
    return await service.delete_source(source_id, session, user_id=user_id)


@router.get("/sources/{source_id}/original")
async def get_source_original(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Stream the original source document (PDF, HTML, etc.).

    Returns the raw binary stored during ingest — not the extracted text.
    Sources that have no original (text, YouTube) return 404.
    """
    source = await service.get_source(source_id, session, user_id=user_id)
    if not source.file_path:
        raise HTTPException(status_code=404, detail="No original document available")

    txt_path = resolve_raw_path(source.file_path, user_id=user_id)
    original = find_original_sibling(txt_path)
    if original is None:
        raise HTTPException(status_code=404, detail="No original document available")

    content_type, _ = mimetypes.guess_type(original.name)
    if content_type is None:
        content_type = "application/octet-stream"

    def iter_file():
        with open(original, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=content_type,
        headers={"Content-Disposition": "inline"},
    )
