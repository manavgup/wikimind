"""User lifecycle management — provisioning and account deletion.

Handles auto-provisioning users from JWT claims and cascade-deleting
all user-owned data when an account is removed.
"""

import functools

from fastapi import HTTPException
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    Concept,
    ContradictionFinding,
    Conversation,
    CostLog,
    Job,
    LintReport,
    OrphanFinding,
    Query,
    Source,
    StructuralFinding,
    SyncLog,
    User,
    UserApiKey,
    UserPreference,
)


class UserService:
    """Manage user provisioning and account lifecycle."""

    async def get_or_create(
        self,
        session: AsyncSession,
        user_id: str,
        email: str | None = None,
    ) -> User:
        """Return an existing user or auto-provision a new one.

        Used by ``GET /auth/me`` to ensure a valid JWT always maps to a
        user row, even without the full OAuth callback flow.

        Args:
            session: Async database session.
            user_id: The user ID from the JWT ``sub`` claim.
            email: Optional email from the JWT ``email`` claim.

        Returns:
            The existing or newly created User record.
        """
        user = await session.get(User, user_id)
        if user:
            return user

        user = User(
            id=user_id,
            email=email or f"{user_id}@jwt.local",
            name=user_id,
            auth_provider="jwt",
            auth_provider_id=user_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    async def delete_account(self, session: AsyncSession, user_id: str) -> None:
        """Cascade-delete all data owned by a user, then remove the user row.

        Deletion order respects FK constraints: child/join rows that
        reference articles, conversations, or lint reports are removed
        before the parent rows.

        Args:
            session: Async database session.
            user_id: The user ID to delete.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Collect IDs for join-table / child-table cleanup
        article_ids = [
            row[0] for row in (await session.execute(select(Article.id).where(Article.user_id == user_id))).all()
        ]
        report_ids = [
            row[0] for row in (await session.execute(select(LintReport.id).where(LintReport.user_id == user_id))).all()
        ]
        conv_ids = [
            row[0]
            for row in (await session.execute(select(Conversation.id).where(Conversation.user_id == user_id))).all()
        ]

        # 1. Delete child rows that reference articles
        if article_ids:
            await session.execute(
                delete(ArticleConcept).where(
                    ArticleConcept.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ArticleSource).where(
                    ArticleSource.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.article_a_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.article_b_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(OrphanFinding).where(
                    OrphanFinding.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(StructuralFinding).where(
                    StructuralFinding.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )

        # 2. Delete lint findings that reference reports
        if report_ids:
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(OrphanFinding).where(
                    OrphanFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(StructuralFinding).where(
                    StructuralFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )

        # 3. Delete queries that reference conversations
        if conv_ids:
            await session.execute(
                delete(Query).where(
                    Query.conversation_id.in_(conv_ids)  # type: ignore[attr-defined]
                )
            )

        # 4. Delete all user-owned rows
        await session.execute(delete(Backlink).where(Backlink.user_id == user_id))
        await session.execute(delete(Article).where(Article.user_id == user_id))
        await session.execute(delete(Source).where(Source.user_id == user_id))
        await session.execute(delete(Concept).where(Concept.user_id == user_id))
        await session.execute(delete(Conversation).where(Conversation.user_id == user_id))
        await session.execute(delete(Job).where(Job.user_id == user_id))
        await session.execute(delete(CostLog).where(CostLog.user_id == user_id))
        await session.execute(delete(SyncLog).where(SyncLog.user_id == user_id))
        await session.execute(delete(LintReport).where(LintReport.user_id == user_id))
        await session.execute(delete(UserApiKey).where(UserApiKey.user_id == user_id))
        await session.execute(delete(UserPreference).where(UserPreference.user_id == user_id))

        # 5. Delete the user
        await session.delete(user)
        await session.commit()


@functools.lru_cache(maxsize=1)
def get_user_service() -> UserService:
    """Return a singleton UserService instance for FastAPI dependency injection."""
    return UserService()
