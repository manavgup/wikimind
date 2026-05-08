"""Contradiction service — persistence and query layer for navigable contradictions.

Bridges linter findings (ephemeral per-report rows) to first-class wiki
content that users can browse, resolve, and dismiss.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    Contradiction,
    ContradictionResponse,
    ContradictionStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ContradictionService:
    """Query and manage persisted contradictions."""

    async def list_contradictions(
        self,
        session: AsyncSession,
        user_id: str,
        status: ContradictionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContradictionResponse]:
        """List contradictions for a user, optionally filtered by status.

        Args:
            session: Async database session.
            user_id: Owner user ID.
            status: Optional status filter.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            List of ContradictionResponse with article titles resolved.
        """
        stmt = (
            select(Contradiction)
            .where(Contradiction.user_id == user_id)
            .order_by(Contradiction.detected_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(Contradiction.status == status)
        result = await session.execute(stmt)
        contradictions = list(result.scalars().all())
        return [await self._to_response(session, c) for c in contradictions]

    async def get_contradiction(
        self,
        session: AsyncSession,
        contradiction_id: str,
        user_id: str,
    ) -> ContradictionResponse:
        """Get a single contradiction by ID with article details.

        Args:
            session: Async database session.
            contradiction_id: Contradiction UUID.
            user_id: Owner user ID for access check.

        Returns:
            ContradictionResponse with article titles.

        Raises:
            NotFoundError: If not found or not owned by user.
        """
        contradiction = await session.get(Contradiction, contradiction_id)
        if not contradiction or contradiction.user_id != user_id:
            msg = "Contradiction not found"
            raise NotFoundError(msg)
        return await self._to_response(session, contradiction)

    async def resolve_contradiction(
        self,
        session: AsyncSession,
        contradiction_id: str,
        user_id: str,
        new_status: ContradictionStatus,
        resolution: str | None = None,
    ) -> ContradictionResponse:
        """Resolve or dismiss a contradiction.

        Args:
            session: Async database session.
            contradiction_id: Contradiction UUID.
            user_id: User performing the resolution.
            new_status: New status (resolved or dismissed).
            resolution: Optional resolution note.

        Returns:
            Updated ContradictionResponse.

        Raises:
            NotFoundError: If not found or not owned by user.
        """
        contradiction = await session.get(Contradiction, contradiction_id)
        if not contradiction or contradiction.user_id != user_id:
            msg = "Contradiction not found"
            raise NotFoundError(msg)

        contradiction.status = new_status
        contradiction.resolution = resolution
        if new_status != ContradictionStatus.ACTIVE:
            contradiction.resolved_at = utcnow_naive()
            contradiction.resolved_by = user_id
        else:
            contradiction.resolved_at = None
            contradiction.resolved_by = None
        session.add(contradiction)
        await session.commit()
        await session.refresh(contradiction)
        return await self._to_response(session, contradiction)

    async def create_from_finding(
        self,
        session: AsyncSession,
        *,
        claim_a: str,
        claim_b: str,
        article_a_id: str,
        article_b_id: str,
        source_finding_id: str | None = None,
        user_id: str,
    ) -> Contradiction:
        """Create a Contradiction record from a linter finding (upsert).

        Avoids duplicates by checking for an existing active contradiction
        between the same article pair (order-independent).

        Args:
            session: Async database session.
            claim_a: First claim text.
            claim_b: Contradicting claim text.
            article_a_id: First article ID.
            article_b_id: Second article ID.
            source_finding_id: Optional FK to the ContradictionFinding.
            user_id: Owner user ID.

        Returns:
            The created or existing Contradiction record.
        """
        # Check for existing active contradiction between the same pair
        ids = sorted([article_a_id, article_b_id])
        existing_stmt = select(Contradiction).where(
            Contradiction.user_id == user_id,
            Contradiction.status == ContradictionStatus.ACTIVE,
            Contradiction.article_a_id.in_(ids),  # type: ignore[attr-defined]
            Contradiction.article_b_id.in_(ids),  # type: ignore[attr-defined]
        )
        result = await session.execute(existing_stmt)
        existing = result.scalars().first()
        if existing is not None:
            return existing

        contradiction = Contradiction(
            claim_a=claim_a,
            claim_b=claim_b,
            article_a_id=article_a_id,
            article_b_id=article_b_id,
            source_finding_id=source_finding_id,
            user_id=user_id,
        )
        session.add(contradiction)
        await session.flush()
        return contradiction

    async def _to_response(
        self,
        session: AsyncSession,
        contradiction: Contradiction,
    ) -> ContradictionResponse:
        """Convert a Contradiction row to an API response with article titles."""
        art_a = await session.get(Article, contradiction.article_a_id)
        art_b = await session.get(Article, contradiction.article_b_id)
        return ContradictionResponse(
            id=contradiction.id,
            claim_a=contradiction.claim_a,
            claim_b=contradiction.claim_b,
            article_a_id=contradiction.article_a_id,
            article_b_id=contradiction.article_b_id,
            article_a_title=art_a.title if art_a else None,
            article_b_title=art_b.title if art_b else None,
            detected_at=contradiction.detected_at,
            status=contradiction.status,
            resolution=contradiction.resolution,
            resolved_at=contradiction.resolved_at,
            resolved_by=contradiction.resolved_by,
        )


@functools.lru_cache(maxsize=1)
def get_contradiction_service() -> ContradictionService:
    """Return a singleton ContradictionService instance."""
    return ContradictionService()
