"""Export wiki articles as PDF HTML, LinkedIn drafts, or Marp slide decks.

Also supports full-wiki export to Obsidian-flavored markdown or plain
markdown + JSON metadata for portability, and single-article download
as markdown or structured JSON.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    Article,
    ArticleDownloadFormat,
    ArticleDownloadResponse,
    ExportFormat,
    ExportResponse,
    WikiExportFormat,
)
from wikimind.services.export import ExportService
from wikimind.services.factories import get_export_service, get_wiki_export_service
from wikimind.services.wiki import (
    _fetch_concept_names_from_join,
    _fetch_source_ids_from_join,
    _fetch_sources,
    _to_source_response,
)
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


@router.get(
    "/articles/{id_or_slug}/export",
    response_model=None,
    responses={
        200: {
            "description": "Downloadable article file (markdown or JSON)",
            "content": {
                "text/markdown": {},
                "application/json": {},
            },
        },
        404: {"description": "Article not found"},
    },
)
async def download_article(
    id_or_slug: str,
    format: ArticleDownloadFormat = Query(..., description="Download format: markdown or json"),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> Response | ArticleDownloadResponse:
    """Download a single article as a markdown file or structured JSON.

    - **markdown**: Returns the article content as a downloadable ``.md`` file
      with a ``Content-Disposition: attachment`` header.
    - **json**: Returns structured JSON with article metadata, content,
      sources, and concepts.
    """
    article = await _resolve_article(id_or_slug, session, user_id)
    content = await read_article_content(article.file_path, user_id=user_id)

    if not content:
        raise HTTPException(status_code=404, detail="Article content not found on disk")

    if format == ArticleDownloadFormat.MARKDOWN:
        filename = f"{article.slug}.md"
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # JSON format — include metadata, content, sources, and concepts
    source_ids = await _fetch_source_ids_from_join(session, article.id)
    sources = await _fetch_sources(session, source_ids)
    concepts = await _fetch_concept_names_from_join(session, article.id)

    return ArticleDownloadResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        content=content,
        page_type=article.page_type,
        concepts=concepts,
        sources=[_to_source_response(s) for s in sources],
        created_at=article.created_at,
        updated_at=article.updated_at,
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
