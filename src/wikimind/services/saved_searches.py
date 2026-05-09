"""Saved search service — CRUD and execution for user-saved searches.

Saved searches store a query string plus optional tag/concept filters so
users can one-click re-execute common queries.
"""

import functools
import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleTag,
    SavedSearch,
    SavedSearchResponse,
)

log = structlog.get_logger()


def _to_response(search: SavedSearch) -> SavedSearchResponse:
    """Project a SavedSearch row into the API-facing response."""
    return SavedSearchResponse(
        id=search.id,
        name=search.name,
        query=search.query,
        filters_json=search.filters_json,
        created_at=search.created_at,
    )


class SavedSearchService:
    """Manage user-saved searches with optional tag and concept filters."""

    async def create(
        self,
        session: AsyncSession,
        user_id: str,
        name: str,
        query: str = "",
        filters_json: str = "{}",
    ) -> SavedSearchResponse:
        """Create a new saved search.

        Args:
            session: Async database session.
            user_id: Owner of the saved search.
            name: Display name for the sidebar.
            query: The search query string.
            filters_json: JSON string of filters (tags, concepts).

        Returns:
            The newly created saved search.
        """
        saved = SavedSearch(
            user_id=user_id,
            name=name,
            query=query,
            filters_json=filters_json,
        )
        session.add(saved)
        await session.flush()
        await session.refresh(saved)
        return _to_response(saved)

    async def list_searches(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[SavedSearchResponse]:
        """List all saved searches for a user.

        Args:
            session: Async database session.
            user_id: Owner of the searches.

        Returns:
            List of saved searches ordered by creation time.
        """
        result = await session.execute(
            select(SavedSearch).where(SavedSearch.user_id == user_id).order_by(SavedSearch.created_at)  # type: ignore[arg-type]
        )
        return [_to_response(s) for s in result.scalars().all()]

    async def delete(
        self,
        session: AsyncSession,
        search_id: str,
        user_id: str,
    ) -> None:
        """Delete a saved search.

        Args:
            session: Async database session.
            search_id: Saved search to delete.
            user_id: Must match the owner.

        Raises:
            NotFoundError: If the saved search does not exist for this user.
        """
        saved = await self._get(session, search_id, user_id)
        await session.delete(saved)

    async def execute(
        self,
        session: AsyncSession,
        search_id: str,
        user_id: str,
    ) -> tuple[SavedSearchResponse, list[str]]:
        """Execute a saved search and return matching article IDs.

        The search applies tag and concept filters from ``filters_json``.
        The query string is matched against article titles using a simple
        substring (case-insensitive) match.

        Args:
            session: Async database session.
            search_id: Saved search to execute.
            user_id: Must match the owner.

        Returns:
            Tuple of (saved search response, list of matching article IDs).

        Raises:
            NotFoundError: If the saved search does not exist for this user.
        """
        saved = await self._get(session, search_id, user_id)
        response = _to_response(saved)

        try:
            filters = json.loads(saved.filters_json)
        except (json.JSONDecodeError, TypeError):
            filters = {}

        tag_names: list[str] = filters.get("tags", [])
        concept_names: list[str] = filters.get("concepts", [])

        # Start with all user articles
        query = select(Article.id).where(Article.user_id == user_id)

        # Apply query string filter (substring match on title)
        if saved.query.strip():
            query = query.where(
                Article.title.ilike(f"%{saved.query.strip()}%")  # type: ignore[attr-defined]
            )

        result = await session.execute(query)
        candidate_ids = {row[0] for row in result.all()}

        # Apply tag filter — articles must have ALL specified tags
        if tag_names:
            from wikimind.models import Tag  # noqa: PLC0415

            tag_result = await session.execute(
                select(Tag.id).where(
                    Tag.user_id == user_id,
                    Tag.name.in_(tag_names),  # type: ignore[attr-defined]
                )
            )
            tag_ids = [row[0] for row in tag_result.all()]
            for tid in tag_ids:
                at_result = await session.execute(select(ArticleTag.article_id).where(ArticleTag.tag_id == tid))
                tagged_ids = {row[0] for row in at_result.all()}
                candidate_ids &= tagged_ids

        # Apply concept filter — articles must have ALL specified concepts
        for concept_name in concept_names:
            ac_result = await session.execute(
                select(ArticleConcept.article_id).where(ArticleConcept.concept_name == concept_name)
            )
            concept_ids = {row[0] for row in ac_result.all()}
            candidate_ids &= concept_ids

        return response, list(candidate_ids)

    async def _get(
        self,
        session: AsyncSession,
        search_id: str,
        user_id: str,
    ) -> SavedSearch:
        """Look up a saved search by ID, scoped to the user."""
        result = await session.execute(
            select(SavedSearch).where(
                SavedSearch.id == search_id,
                SavedSearch.user_id == user_id,
            )
        )
        saved = result.scalar_one_or_none()
        if saved is None:
            msg = "Saved search not found"
            raise NotFoundError(msg)
        return saved


@functools.lru_cache(maxsize=1)
def get_saved_search_service() -> SavedSearchService:
    """Return a singleton SavedSearchService for FastAPI dependency injection."""
    return SavedSearchService()
