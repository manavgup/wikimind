"""Export wiki articles as PDF HTML, LinkedIn drafts, or Marp slide decks.

Also supports full-wiki export to Obsidian-flavored markdown or plain
markdown + JSON metadata for portability.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.api.services import get_export_service, get_wiki_export_service
from wikimind.database import get_session
from wikimind.models import Article, ExportFormat, ExportResponse, WikiExportFormat
from wikimind.services.export import ExportService
from wikimind.services.wiki_export import WikiExportService
from wikimind.storage import read_article_content

log = structlog.get_logger()

router = APIRouter()


async def _resolve_article(
    id_or_slug: str,
    session: AsyncSession,
    user_id: str,
) -> Article:
    """Look up an article by ID or slug, raising 404 if not found."""
    id_stmt = select(Article).where(Article.id == id_or_slug, Article.user_id == user_id)
    result = await session.execute(id_stmt)
    article = result.scalar_one_or_none()
    if article is None:
        slug_stmt = select(Article).where(Article.slug == id_or_slug, Article.user_id == user_id)
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
    content = await read_article_content(article.file_path, user_id=user_id)

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


@router.post(
    "/export/wiki",
    responses={
        200: {
            "description": "ZIP archive of the full wiki",
            "content": {"application/zip": {}},
        },
    },
)
async def export_wiki(
    format: WikiExportFormat = Query(
        default=WikiExportFormat.OBSIDIAN,
        description="Export format: obsidian or markdown_json",
    ),
    session: AsyncSession = Depends(get_session),
    export_service: WikiExportService = Depends(get_wiki_export_service),
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse:
    """Export the full wiki as a ZIP archive.

    - **obsidian**: Obsidian-flavored markdown with YAML frontmatter and tags.
    - **markdown_json**: Plain markdown files with a metadata.json sidecar.
    """
    buf, filename, _count = await export_service.export_wiki(session, user_id=user_id, fmt=format)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
