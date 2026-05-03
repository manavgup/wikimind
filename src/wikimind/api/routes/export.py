"""Export wiki articles as PDF HTML, LinkedIn drafts, or Marp slide decks."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import Article, ExportFormat, ExportResponse
from wikimind.services.export import ExportService, get_export_service
from wikimind.storage import get_wiki_storage

log = structlog.get_logger()

router = APIRouter()


async def _read_article_content(file_path: str, user_id: str) -> str:
    """Read article markdown content from disk via storage abstraction."""
    try:
        storage = get_wiki_storage(user_id)
        return await storage.read(file_path)
    except OSError:
        return ""


async def _resolve_article(
    id_or_slug: str,
    session: AsyncSession,
    user_id: str,
) -> Article:
    """Look up an article by ID or slug, raising 404 if not found."""
    id_stmt = select(Article).where(Article.id == id_or_slug)
    if user_id:
        id_stmt = id_stmt.where(Article.user_id == user_id)
    result = await session.execute(id_stmt)
    article = result.scalar_one_or_none()
    if article is None:
        slug_stmt = select(Article).where(Article.slug == id_or_slug)
        if user_id:
            slug_stmt = slug_stmt.where(Article.user_id == user_id)
        result = await session.execute(slug_stmt)
        article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post(
    "/articles/{id_or_slug}/export",
    response_model=ExportResponse,
    responses={
        200: {
            "description": "Export result (JSON for linkedin/slides, HTML for pdf)",
            "content": {
                "application/json": {},
                "text/html": {},
            },
        },
        404: {"description": "Article not found"},
        422: {"description": "Invalid export format"},
    },
)
async def export_article(
    id_or_slug: str,
    format: ExportFormat = Query(..., description="Export format: pdf, linkedin, or slides"),
    session: AsyncSession = Depends(get_session),
    service: ExportService = Depends(get_export_service),
    user_id: str = Depends(get_current_user_id),
) -> ExportResponse | HTMLResponse:
    """Export a wiki article in the requested format.

    - **pdf**: Returns styled HTML (text/html) suitable for browser print-to-PDF.
    - **linkedin**: Returns a LinkedIn post draft (JSON with content field).
    - **slides**: Returns a Marp-compatible markdown slide deck (JSON with content field).
    """
    article = await _resolve_article(id_or_slug, session, user_id)
    content = await _read_article_content(article.file_path, user_id=user_id)

    if not content:
        raise HTTPException(status_code=404, detail="Article content not found on disk")

    if format == ExportFormat.PDF:
        html = service.export_pdf_html(article.title, content)
        return HTMLResponse(content=html, media_type="text/html")

    if format == ExportFormat.LINKEDIN:
        text = await service.export_linkedin(article.title, content, user_id=user_id)
        return ExportResponse(
            format=ExportFormat.LINKEDIN,
            content=text,
            article_id=article.id,
            article_title=article.title,
        )

    # slides
    text = await service.export_slides(article.title, content, user_id=user_id)
    return ExportResponse(
        format=ExportFormat.SLIDES,
        content=text,
        article_id=article.id,
        article_title=article.title,
    )
