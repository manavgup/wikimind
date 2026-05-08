"""Tag management service — CRUD for user-created organizational tags.

Tags are user-asserted labels (``read-later``, ``favorite``, ``to-revisit``)
that provide an organizational layer separate from LLM-derived concepts.
"""

import functools

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleTag,
    Tag,
    TagResponse,
)

log = structlog.get_logger()


def _to_tag_response(tag: Tag) -> TagResponse:
    """Project a Tag row into the API-facing TagResponse."""
    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        created_at=tag.created_at,
    )


class TagService:
    """Manage user-created tags and article-tag associations."""

    async def create_tag(
        self,
        session: AsyncSession,
        user_id: str,
        name: str,
        color: str = "#6366f1",
    ) -> TagResponse:
        """Create a new tag for the user.

        Args:
            session: Async database session.
            user_id: Owner of the tag.
            name: Display name (must be unique per user).
            color: Hex color for pill badge rendering.

        Returns:
            The newly created tag.
        """
        tag = Tag(user_id=user_id, name=name, color=color)
        session.add(tag)
        await session.flush()
        await session.refresh(tag)
        return _to_tag_response(tag)

    async def list_tags(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[TagResponse]:
        """List all tags belonging to a user.

        Args:
            session: Async database session.
            user_id: Owner of the tags.

        Returns:
            List of tags ordered by creation time.
        """
        result = await session.execute(
            select(Tag).where(Tag.user_id == user_id).order_by(Tag.created_at)  # type: ignore[arg-type]
        )
        return [_to_tag_response(t) for t in result.scalars().all()]

    async def delete_tag(
        self,
        session: AsyncSession,
        tag_id: str,
        user_id: str,
    ) -> None:
        """Delete a tag and all its article associations.

        Args:
            session: Async database session.
            tag_id: Tag to delete.
            user_id: Must match the tag owner.

        Raises:
            NotFoundError: If the tag does not exist for this user.
        """
        tag = await self._get_tag(session, tag_id, user_id)
        # Remove all article-tag associations first
        result = await session.execute(select(ArticleTag).where(ArticleTag.tag_id == tag.id))
        for at in result.scalars().all():
            await session.delete(at)
        await session.delete(tag)

    async def tag_article(
        self,
        session: AsyncSession,
        article_id: str,
        tag_id: str,
        user_id: str,
    ) -> None:
        """Apply a tag to an article.

        Args:
            session: Async database session.
            article_id: Article to tag.
            tag_id: Tag to apply.
            user_id: Must own both the tag and the article.

        Raises:
            NotFoundError: If the tag or article does not exist for this user.
        """
        await self._get_tag(session, tag_id, user_id)
        await self._get_article(session, article_id, user_id)

        # Check for existing association
        existing = await session.execute(
            select(ArticleTag).where(
                ArticleTag.article_id == article_id,
                ArticleTag.tag_id == tag_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return  # Already tagged

        association = ArticleTag(article_id=article_id, tag_id=tag_id)
        session.add(association)

    async def untag_article(
        self,
        session: AsyncSession,
        article_id: str,
        tag_id: str,
        user_id: str,
    ) -> None:
        """Remove a tag from an article.

        Args:
            session: Async database session.
            article_id: Article to untag.
            tag_id: Tag to remove.
            user_id: Must own the tag.

        Raises:
            NotFoundError: If the association does not exist.
        """
        await self._get_tag(session, tag_id, user_id)
        result = await session.execute(
            select(ArticleTag).where(
                ArticleTag.article_id == article_id,
                ArticleTag.tag_id == tag_id,
            )
        )
        association = result.scalar_one_or_none()
        if association is None:
            msg = "Article is not tagged with this tag"
            raise NotFoundError(msg)
        await session.delete(association)

    async def get_articles_by_tag(
        self,
        session: AsyncSession,
        tag_id: str,
        user_id: str,
    ) -> list[str]:
        """Return article IDs tagged with the given tag.

        Args:
            session: Async database session.
            tag_id: Tag to filter by.
            user_id: Must own the tag.

        Returns:
            List of article IDs.

        Raises:
            NotFoundError: If the tag does not exist for this user.
        """
        await self._get_tag(session, tag_id, user_id)
        result = await session.execute(select(ArticleTag.article_id).where(ArticleTag.tag_id == tag_id))
        return [row[0] for row in result.all()]

    async def get_tags_for_article(
        self,
        session: AsyncSession,
        article_id: str,
    ) -> list[TagResponse]:
        """Return all tags applied to an article.

        Args:
            session: Async database session.
            article_id: Article to look up.

        Returns:
            List of TagResponse records.
        """
        result = await session.execute(
            select(Tag)
            .join(ArticleTag, ArticleTag.tag_id == Tag.id)  # type: ignore[arg-type]
            .where(ArticleTag.article_id == article_id)
        )
        return [_to_tag_response(t) for t in result.scalars().all()]

    async def get_tags_for_articles(
        self,
        session: AsyncSession,
        article_ids: list[str],
    ) -> dict[str, list[TagResponse]]:
        """Batch-fetch tags for multiple articles.

        Args:
            session: Async database session.
            article_ids: Articles to look up.

        Returns:
            Dict mapping article_id to list of TagResponse.
        """
        result_map: dict[str, list[TagResponse]] = {aid: [] for aid in article_ids}
        if not article_ids:
            return result_map
        result = await session.execute(
            select(ArticleTag.article_id, Tag)
            .join(Tag, Tag.id == ArticleTag.tag_id)  # type: ignore[arg-type]
            .where(
                ArticleTag.article_id.in_(article_ids)  # type: ignore[attr-defined]
            )
        )
        for row in result.all():
            article_id = row[0]
            tag = row[1]
            result_map[article_id].append(_to_tag_response(tag))
        return result_map

    async def _get_tag(
        self,
        session: AsyncSession,
        tag_id: str,
        user_id: str,
    ) -> Tag:
        """Look up a tag by ID, scoped to the user."""
        result = await session.execute(select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id))
        tag = result.scalar_one_or_none()
        if tag is None:
            msg = "Tag not found"
            raise NotFoundError(msg)
        return tag

    async def _get_article(
        self,
        session: AsyncSession,
        article_id: str,
        user_id: str,
    ) -> Article:
        """Look up an article by ID, scoped to the user."""
        result = await session.execute(select(Article).where(Article.id == article_id, Article.user_id == user_id))
        article = result.scalar_one_or_none()
        if article is None:
            msg = "Article not found"
            raise NotFoundError(msg)
        return article


@functools.lru_cache(maxsize=1)
def get_tag_service() -> TagService:
    """Return a singleton TagService instance for FastAPI dependency injection."""
    return TagService()
