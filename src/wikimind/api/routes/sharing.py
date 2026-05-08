"""Endpoints for per-article share links and public article access."""

import html

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CreateShareLinkRequest,
    PublicArticleResponse,
    ShareLinkResponse,
)
from wikimind.services.sharing import SharingService, get_sharing_service

log = structlog.get_logger()

router = APIRouter()

# Public router — no auth required for shared article access
public_router = APIRouter()


@router.post(
    "/share-links",
    response_model=ShareLinkResponse,
    status_code=201,
    responses={404: {"description": "Article not found"}},
)
async def create_share_link(
    body: CreateShareLinkRequest,
    session: AsyncSession = Depends(get_session),
    service: SharingService = Depends(get_sharing_service),
    user_id: str = Depends(get_current_user_id),
) -> ShareLinkResponse:
    """Create a new share link for an article.

    The returned token can be used to construct a public URL for
    read-only access to the article content.
    """
    return await service.create_share_link(
        session,
        article_id=body.article_id,
        user_id=user_id,
        expires_in_days=body.expires_in_days,
    )


@router.delete(
    "/share-links/{link_id}",
    status_code=204,
    responses={404: {"description": "Share link not found"}},
)
async def revoke_share_link(
    link_id: str,
    session: AsyncSession = Depends(get_session),
    service: SharingService = Depends(get_sharing_service),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Revoke a share link so it can no longer be accessed."""
    await service.revoke_share_link(session, link_id, user_id)


@router.get(
    "/share-links",
    response_model=list[ShareLinkResponse],
)
async def list_share_links(
    article_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    service: SharingService = Depends(get_sharing_service),
    user_id: str = Depends(get_current_user_id),
) -> list[ShareLinkResponse]:
    """List all share links for the current user, optionally filtered by article."""
    return await service.list_share_links(session, user_id, article_id=article_id)


# ---------------------------------------------------------------------------
# Public endpoint — accessible without authentication
# ---------------------------------------------------------------------------

_PUBLIC_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — WikiMind</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    max-width: 800px;
    margin: 0 auto;
    padding: 2rem 1rem;
    color: #1a1a1a;
    line-height: 1.7;
    font-size: 15px;
    background: #fafafa;
  }}
  .header {{
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 1rem;
    margin-bottom: 2rem;
  }}
  .header h1 {{
    font-size: 2rem;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 0.5rem;
  }}
  .header .summary {{
    color: #64748b;
    font-size: 1rem;
    line-height: 1.5;
  }}
  .content h2 {{
    font-size: 1.4rem;
    margin-top: 2rem;
    margin-bottom: 0.5rem;
    color: #1e293b;
  }}
  .content h3 {{
    font-size: 1.15rem;
    margin-top: 1.5rem;
    margin-bottom: 0.5rem;
    color: #334155;
  }}
  .content p {{
    margin-bottom: 1rem;
  }}
  .content blockquote {{
    border-left: 4px solid #6366f1;
    margin: 1rem 0;
    padding: 0.75rem 1rem;
    background: #f1f5f9;
    border-radius: 0 4px 4px 0;
  }}
  .content code {{
    background: #f1f5f9;
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
    font-size: 0.9em;
  }}
  .content pre {{
    background: #f1f5f9;
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    margin: 1rem 0;
  }}
  .content pre code {{ background: none; padding: 0; }}
  .content ul, .content ol {{ padding-left: 1.5rem; margin-bottom: 1rem; }}
  .content li {{ margin-bottom: 0.3rem; }}
  .content a {{ color: #4f46e5; }}
  .sources {{
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e2e8f0;
  }}
  .sources h3 {{
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #94a3b8;
    margin-bottom: 0.75rem;
  }}
  .sources ul {{ list-style: none; padding: 0; }}
  .sources li {{
    padding: 0.5rem 0;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.9rem;
    color: #475569;
  }}
  .sources a {{ color: #4f46e5; text-decoration: none; }}
  .sources a:hover {{ text-decoration: underline; }}
  .footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid #e2e8f0;
    text-align: center;
    font-size: 0.8rem;
    color: #94a3b8;
  }}
  @media (max-width: 640px) {{
    body {{ padding: 1rem 0.75rem; }}
    .header h1 {{ font-size: 1.5rem; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  {summary_block}
</div>
<div class="content">
  {body}
</div>
{sources_block}
<div class="footer">
  Shared from <strong>WikiMind</strong>
</div>
</body>
</html>
"""


def _escape_html(text: str) -> str:
    """Escape HTML special characters including quotes for safe attribute use."""
    return html.escape(text, quote=True)


@public_router.get(
    "/public/articles/{token}",
    response_class=HTMLResponse,
    responses={
        404: {"description": "Share link not found or revoked"},
        410: {"description": "Share link has expired"},
    },
)
async def get_public_article(
    token: str,
    session: AsyncSession = Depends(get_session),
    service: SharingService = Depends(get_sharing_service),
) -> HTMLResponse:
    """Render a publicly shared article as a minimal HTML page.

    No authentication required. The article is identified by its
    cryptographically random share token.
    """
    article = await service.get_public_article(session, token)

    summary_block = ""
    if article.summary:
        summary_block = f'<p class="summary">{_escape_html(article.summary)}</p>'

    sources_block = ""
    if article.sources:
        source_items = []
        for src in article.sources:
            title = _escape_html(src.title or "Untitled source")
            if src.source_url:
                source_items.append(
                    f'<li><a href="{_escape_html(src.source_url)}" target="_blank" rel="noopener">{title}</a></li>'
                )
            else:
                source_items.append(f"<li>{title}</li>")
        sources_block = '<div class="sources"><h3>Sources</h3><ul>' + "\n".join(source_items) + "</ul></div>"

    html = _PUBLIC_HTML_TEMPLATE.format(
        title=_escape_html(article.title),
        summary_block=summary_block,
        body=article.content_html,
        sources_block=sources_block,
    )
    return HTMLResponse(content=html)


@public_router.get(
    "/public/articles/{token}/json",
    response_model=PublicArticleResponse,
    responses={
        404: {"description": "Share link not found or revoked"},
        410: {"description": "Share link has expired"},
    },
)
async def get_public_article_json(
    token: str,
    session: AsyncSession = Depends(get_session),
    service: SharingService = Depends(get_sharing_service),
) -> PublicArticleResponse:
    """Return a publicly shared article as JSON (for API consumers)."""
    return await service.get_public_article(session, token)
