"""Service for per-article public share links.

Handles creation, revocation, listing, and token verification of
share links. Each share link has a cryptographically random token
and can be set to expire or be revoked.
"""

import functools
import secrets
from datetime import timedelta

import structlog
from sqlalchemy import desc
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.errors import GoneError, NotFoundError
from wikimind.models import (
    Article,
    PublicArticleResponse,
    ShareLink,
    ShareLinkResponse,
    SourceResponse,
)
from wikimind.services.export import _markdown_to_html
from wikimind.storage import read_article_content

log = structlog.get_logger()

# Token length in bytes — 32 bytes = 43 URL-safe base64 characters.
SHARE_TOKEN_BYTES = 32


class SharingService:
    """Manage per-article share links."""

    async def create_share_link(
        self,
        session: AsyncSession,
        article_id: str,
        user_id: str,
        expires_in_days: int | None = None,
    ) -> ShareLinkResponse:
        """Create a new share link for an article.

        Args:
            session: Database session.
            article_id: The article to share.
            user_id: Owner of the article.
            expires_in_days: Optional expiry in days from now.

        Returns:
            The created share link response.

        Raises:
            NotFoundError: If article not found or not owned by user.
        """
        article = await session.get(Article, article_id)
        if article is None or article.user_id != user_id:
            msg = "Article not found"
            raise NotFoundError(msg)

        token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
        now = utcnow_naive()
        expires_at = now + timedelta(days=expires_in_days) if expires_in_days else None

        link = ShareLink(
            user_id=user_id,
            article_id=article_id,
            token=token,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(link)
        await session.flush()
        await session.refresh(link)

        return ShareLinkResponse(
            id=link.id,
            article_id=link.article_id,
            token=link.token,
            created_at=link.created_at,
            expires_at=link.expires_at,
            revoked=link.revoked,
            view_count=link.view_count,
            last_viewed_at=link.last_viewed_at,
            article_title=article.title,
        )

    async def revoke_share_link(
        self,
        session: AsyncSession,
        link_id: str,
        user_id: str,
    ) -> None:
        """Revoke a share link so it can no longer be accessed.

        Args:
            session: Database session.
            link_id: The share link ID.
            user_id: Owner of the share link.

        Raises:
            NotFoundError: If link not found or not owned by user.
        """
        link = await session.get(ShareLink, link_id)
        if link is None or link.user_id != user_id:
            msg = "Share link not found"
            raise NotFoundError(msg)

        link.revoked = True
        session.add(link)

    async def list_share_links(
        self,
        session: AsyncSession,
        user_id: str,
        article_id: str | None = None,
    ) -> list[ShareLinkResponse]:
        """List share links for a user, optionally filtered by article.

        Args:
            session: Database session.
            user_id: Owner.
            article_id: Optional article filter.

        Returns:
            List of share link responses with article titles.
        """
        stmt = select(ShareLink).where(ShareLink.user_id == user_id)
        if article_id:
            stmt = stmt.where(ShareLink.article_id == article_id)
        stmt = stmt.order_by(desc(ShareLink.created_at))  # type: ignore[arg-type]

        result = await session.execute(stmt)
        links = list(result.scalars().all())

        # Batch-load article titles
        article_ids = list({link.article_id for link in links})
        titles: dict[str, str] = {}
        if article_ids:
            art_result = await session.execute(
                select(Article.id, Article.title).where(
                    Article.id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            for row in art_result.all():
                titles[row[0]] = row[1]

        return [
            ShareLinkResponse(
                id=link.id,
                article_id=link.article_id,
                token=link.token,
                created_at=link.created_at,
                expires_at=link.expires_at,
                revoked=link.revoked,
                view_count=link.view_count,
                last_viewed_at=link.last_viewed_at,
                article_title=titles.get(link.article_id),
            )
            for link in links
        ]

    async def get_public_article(
        self,
        session: AsyncSession,
        token: str,
    ) -> PublicArticleResponse:
        """Resolve a share token and return the article content for public viewing.

        Args:
            session: Database session.
            token: The share link token from the URL.

        Returns:
            Public article response with HTML content.

        Raises:
            NotFoundError: If link is revoked, invalid, or article missing.
            GoneError: If link has expired.
        """
        result = await session.execute(select(ShareLink).where(ShareLink.token == token))
        link = result.scalar_one_or_none()

        if link is None or link.revoked:
            msg = "Share link not found"
            raise NotFoundError(msg)

        now = utcnow_naive()
        if link.expires_at and link.expires_at < now:
            msg = "Share link has expired"
            raise GoneError(msg)

        article = await session.get(Article, link.article_id)
        if article is None:
            msg = "Article not found"
            raise NotFoundError(msg)

        # Update view count
        link.view_count += 1
        link.last_viewed_at = now
        session.add(link)

        # Read article content and convert to HTML
        content = await read_article_content(article.file_path, user_id=article.user_id)
        content_html = _markdown_to_html(content) if content else ""

        # Build source list for attribution
        from wikimind.models import ArticleSource, Source  # noqa: PLC0415

        source_stmt = (
            select(Source)
            .join(
                ArticleSource,
                Source.id == ArticleSource.source_id,  # type: ignore[arg-type]
            )
            .where(ArticleSource.article_id == article.id)
        )
        source_result = await session.execute(source_stmt)
        sources = [
            SourceResponse(
                id=s.id,
                source_type=s.source_type,
                title=s.title,
                source_url=s.source_url,
                ingested_at=s.ingested_at,
            )
            for s in source_result.scalars().all()
        ]

        return PublicArticleResponse(
            title=article.title,
            content_html=content_html,
            summary=article.summary,
            sources=sources,
            created_at=article.created_at,
            updated_at=article.updated_at,
        )


@functools.lru_cache(maxsize=1)
def get_sharing_service() -> SharingService:
    """Return the singleton sharing service."""
    return SharingService()
