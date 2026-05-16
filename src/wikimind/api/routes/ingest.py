"""Endpoints for ingesting sources (URLs, PDFs, text) into the knowledge base."""

import mimetypes
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.ingest.adapters.pdf import PDFAdapter
from wikimind.models import (
    Article,
    ArticleSource,
    IngestTextRequest,
    IngestURLRequest,
    LinkedArticleSummary,
    PipelineStep,
    Source,
    SourceContentResponse,
    SourceDetailResponse,
    SourceImage,
    SourceImageEntry,
)
from wikimind.services.factories import get_ingest_service
from wikimind.services.ingest import IngestService
from wikimind.storage import find_original_sibling, get_raw_storage

# Strict pattern: only alphanumeric, hyphens, underscores, dots (no path separators)
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_path_component(value: str, label: str = "path component") -> None:
    """Reject path components that could enable path traversal.

    Raises HTTPException(400) for values containing ``..``, path separators,
    or any character outside the safe set. This is defense-in-depth on top
    of the ``LocalFileStorage._resolve()`` guard in ``storage.py``.
    """
    if ".." in value or "/" in value or "\\" in value:
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    if not _SAFE_FILENAME_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")


router = APIRouter()


@router.post("/url", response_model=Source)
async def ingest_url(
    request: IngestURLRequest,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Ingest a web URL or YouTube video."""
    return await service.ingest_url(str(request.url), session, auto_compile=request.auto_compile, user_id=user_id)


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
    # Enforce 50 MB upload limit. Check Content-Length header first to reject
    # oversized uploads without reading into memory. Fall back to post-read
    # check for chunked transfers that omit Content-Length.
    max_size = 50 * 1024 * 1024  # 50 MB
    if file.size is not None and file.size > max_size:
        raise HTTPException(status_code=413, detail="PDF exceeds 50 MB size limit")
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(status_code=413, detail="PDF exceeds 50 MB size limit")
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
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
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


@router.get("/sources/{source_id}/detail", response_model=SourceDetailResponse)
async def get_source_detail(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Get full source detail with pipeline steps, images, and linked articles."""
    source = await service.get_source(source_id, session, user_id=user_id)

    # Build pipeline steps based on source status
    pipeline_steps = _build_pipeline_steps(source)

    # Query extracted images from source_image table
    img_stmt = (
        select(SourceImage.filename, SourceImage.kind)
        .where(SourceImage.source_id == source_id, SourceImage.user_id == user_id)
        .order_by(SourceImage.filename)
    )
    img_rows = (await session.exec(img_stmt)).all()
    images: list[SourceImageEntry] = []
    for filename, kind in img_rows:
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        parts = stem.rsplit("-", 1)
        num = parts[1] if len(parts) == 2 and parts[1].isdigit() else stem
        label = f"{'Table' if kind == 'table' else 'Figure'} {num}"
        images.append(SourceImageEntry(filename=filename, kind=kind, label=label))

    # Query linked articles via ArticleSource join table
    art_stmt = (
        select(Article.id, Article.slug, Article.title, Article.page_type)
        .join(ArticleSource, ArticleSource.article_id == Article.id)  # type: ignore[arg-type]
        .where(ArticleSource.source_id == source_id, Article.user_id == user_id)
    )
    art_rows = (await session.exec(art_stmt)).all()
    linked_articles = [LinkedArticleSummary(id=row[0], slug=row[1], title=row[2], page_type=row[3]) for row in art_rows]

    return SourceDetailResponse(
        id=source.id,
        source_type=source.source_type,
        source_url=source.source_url,
        title=source.title,
        author=source.author,
        published_date=source.published_date,
        status=source.status,
        ingested_at=source.ingested_at,
        compiled_at=source.compiled_at,
        token_count=source.token_count,
        error_message=source.error_message,
        has_original=source.has_original,
        pipeline_steps=pipeline_steps,
        images=images,
        linked_articles=linked_articles,
    )


def _build_pipeline_steps(source: Source) -> list[PipelineStep]:
    """Derive pipeline step statuses from the source's current state."""
    status = source.status

    if status == "failed":
        return [
            PipelineStep(name="Fetch", status="complete", description="Source fetched"),
            PipelineStep(name="Extract", status="failed", description=source.error_message or "Failed"),
            PipelineStep(name="Clean", status="pending", description="Normalize text"),
            PipelineStep(name="Compile", status="pending", description="Generate article via LLM"),
        ]

    if status == "pending":
        return [
            PipelineStep(name="Fetch", status="pending", description="Fetch source content"),
            PipelineStep(name="Extract", status="pending", description="Extract text & images"),
            PipelineStep(name="Clean", status="pending", description="Normalize text"),
            PipelineStep(name="Compile", status="pending", description="Generate article via LLM"),
        ]

    if status == "processing":
        return [
            PipelineStep(name="Fetch", status="complete", description="Source fetched"),
            PipelineStep(name="Extract", status="complete", description="Text extracted"),
            PipelineStep(name="Clean", status="complete", description="Text normalized"),
            PipelineStep(name="Compile", status="active", description="Compiling via LLM..."),
        ]

    if status == "review_pending":
        return [
            PipelineStep(name="Fetch", status="complete", description="Source fetched"),
            PipelineStep(name="Extract", status="complete", description="Text extracted"),
            PipelineStep(name="Clean", status="complete", description="Text normalized"),
            PipelineStep(name="Compile", status="complete", description="Draft ready for review"),
        ]

    # compiled
    return [
        PipelineStep(name="Fetch", status="complete", description="Source fetched"),
        PipelineStep(name="Extract", status="complete", description="Text extracted"),
        PipelineStep(name="Clean", status="complete", description="Text normalized"),
        PipelineStep(name="Compile", status="complete", description="Article compiled"),
    ]


@router.get(
    "/sources/{source_id}/content",
    response_model=SourceContentResponse,
    responses={404: {"description": "Source not found or has no content"}},
)
async def get_source_content(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Return the raw text content of a source for side-by-side reading."""
    return await service.get_source_content(source_id, session, user_id=user_id)


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

    raw_storage = get_raw_storage(user_id)
    try:
        txt_path = raw_storage.resolve_path(source.file_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="No original document available") from None
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


@router.get(
    "/sources/{source_id}/images",
    responses={404: {"description": "Source not found or no images available"}},
)
async def list_source_images(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """List extracted images for a PDF source.

    Reads from the ``source_image`` table first (DB-backed storage),
    falling back to the filesystem for pre-migration sources.
    """
    _validate_path_component(source_id, "source_id")
    await service.get_source(source_id, session, user_id=user_id)

    # DB-first: query source_image table
    stmt = (
        select(SourceImage.filename, SourceImage.kind)
        .where(SourceImage.source_id == source_id, SourceImage.user_id == user_id)
        .order_by(SourceImage.filename)
    )
    rows = (await session.exec(stmt)).all()
    if rows:
        entries = []
        for filename, kind in rows:
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            parts = stem.rsplit("-", 1)
            num = parts[1] if len(parts) == 2 and parts[1].isdigit() else stem
            label = f"{'Table' if kind == 'table' else 'Figure'} {num}"
            entries.append({"filename": filename, "kind": kind, "label": label})
        return entries

    # Filesystem fallback for pre-migration sources
    image_dir = PDFAdapter.get_image_dir(user_id, source_id)
    if not image_dir.is_dir():
        return []

    entries = []
    for path in sorted(image_dir.iterdir()):
        if not path.is_file():
            continue
        stem = path.stem
        kind = "table" if stem.startswith("table-") else "figure"
        parts = stem.rsplit("-", 1)
        num = parts[1] if len(parts) == 2 and parts[1].isdigit() else stem
        label = f"{'Table' if kind == 'table' else 'Figure'} {num}"
        entries.append({"filename": path.name, "kind": kind, "label": label})

    return entries


@router.get(
    "/sources/{source_id}/images/{filename}",
    responses={404: {"description": "Image not found"}},
)
async def get_source_image(
    source_id: str,
    filename: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
    user_id: str = Depends(get_current_user_id),
):
    """Serve an extracted image file for a PDF source.

    Reads from the ``source_image`` table first (DB-backed storage),
    falling back to the filesystem for pre-migration sources.
    """
    _validate_path_component(source_id, "source_id")
    _validate_path_component(filename, "filename")
    await service.get_source(source_id, session, user_id=user_id)

    content_type, _ = mimetypes.guess_type(filename)
    if content_type is None:
        content_type = "application/octet-stream"

    # DB-first: query source_image table
    stmt = select(SourceImage.image_data).where(
        SourceImage.source_id == source_id,
        SourceImage.user_id == user_id,
        SourceImage.filename == filename,
    )
    row = (await session.exec(stmt)).first()
    if row is not None:
        return Response(
            content=row,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Filesystem fallback for pre-migration sources
    image_dir = PDFAdapter.get_image_dir(user_id, source_id)
    image_path = (image_dir / filename).resolve()

    if not image_path.is_relative_to(image_dir.resolve()):
        raise HTTPException(status_code=404, detail="Image not found")

    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(
        path=str(image_path),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
