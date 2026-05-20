"""Service layer for human-in-the-loop discussion before compilation (issue #418).

Users discuss an article's source material with the LLM before triggering
recompilation. The discussion thread provides context that is distilled
into guidance for the compiler's ``compile_with_guidance`` method.
"""

import contextlib
import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.errors import NotFoundError
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    Article,
    ArticleSource,
    CompileWithGuidanceResponse,
    CompletionRequest,
    DiscussionMessage,
    DiscussionMessageResponse,
    DiscussionThreadResponse,
    Job,
    JobType,
    Source,
    TaskType,
)
from wikimind.storage import read_article_content

log = structlog.get_logger()

DISCUSSION_SYSTEM_PROMPT = """You are a knowledgeable research assistant helping \
the user discuss source material before it is compiled into a wiki article.

You have access to:
1. The wiki article's current content
2. The original source material that was used to compile it

Your job:
- Answer questions about the source material and article
- Help the user identify what's important, missing, or needs emphasis
- Suggest aspects that could be explored more deeply
- Point out potential issues, gaps, or alternative interpretations

Be concise and specific. Reference the source material directly when possible.
Do NOT make up information that isn't in the sources."""


class DiscussionService:
    """Manage discussion threads for articles."""

    async def _get_article_owned_by_user(
        self,
        article_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> Article:
        """Fetch an article and verify ownership."""
        article = await session.get(Article, article_id)
        if not article or article.user_id != user_id:
            msg = "Article not found"
            raise NotFoundError(msg)
        return article

    async def _build_article_context(
        self,
        article: Article,
        session: AsyncSession,
    ) -> str:
        """Build context string from article content and its sources."""
        parts: list[str] = []

        # Article content
        content = await read_article_content(article.file_path, article.user_id)
        if content:
            parts.append(f"## Current Article Content\n\n{content[:8000]}")

        # Source material
        result = await session.execute(
            select(Source)
            .join(ArticleSource, ArticleSource.source_id == Source.id)  # type: ignore[arg-type]
            .where(ArticleSource.article_id == article.id)
        )
        sources = list(result.scalars().all())
        for source in sources[:3]:
            if source.clean_text:
                truncated = source.clean_text[:5000]
                title = source.title or source.source_url or "Untitled source"
                parts.append(f"## Source: {title}\n\n{truncated}")

        return "\n\n---\n\n".join(parts) if parts else "No content available."

    async def post_message(
        self,
        article_id: str,
        user_message: str,
        session: AsyncSession,
        user_id: str,
    ) -> DiscussionMessageResponse:
        """Post a user message and get an LLM response.

        Args:
            article_id: The article to discuss.
            user_message: The user's message.
            session: Async database session.
            user_id: Current user ID.

        Returns:
            The assistant's response message.

        Raises:
            NotFoundError: If the article doesn't exist or isn't owned by the user.
        """
        article = await self._get_article_owned_by_user(article_id, session, user_id)
        context = await self._build_article_context(article, session)

        # Persist user message
        user_msg = DiscussionMessage(
            article_id=article_id,
            user_id=user_id,
            role="user",
            content=user_message,
        )
        session.add(user_msg)
        await session.commit()

        # Load prior messages for conversation context
        result = await session.execute(
            select(DiscussionMessage)
            .where(
                DiscussionMessage.article_id == article_id,
                DiscussionMessage.user_id == user_id,
            )
            .order_by(DiscussionMessage.created_at)  # type: ignore[arg-type]
        )
        all_messages = list(result.scalars().all())

        # Build LLM conversation
        llm_messages: list[dict[str, str]] = [
            {"role": "user", "content": f"Here is the article and source context:\n\n{context}"},
            {
                "role": "assistant",
                "content": "I've reviewed the article and source material. What would you like to discuss?",
            },
        ]
        llm_messages.extend({"role": msg.role, "content": msg.content} for msg in all_messages)

        settings = get_settings()
        request = CompletionRequest(
            system=DISCUSSION_SYSTEM_PROMPT,
            messages=llm_messages,
            max_tokens=settings.compiler.max_tokens // 2,
            temperature=0.4,
            response_format="text",
            task_type=TaskType.QA,
        )

        from wikimind.services.plan_routing import plan_aware_complete  # noqa: PLC0415

        router = get_llm_router()
        response = await plan_aware_complete(router, request, user_id, session=None)

        assistant_content = response.content if response else "I wasn't able to generate a response. Please try again."

        # Persist assistant response
        assistant_msg = DiscussionMessage(
            article_id=article_id,
            user_id=user_id,
            role="assistant",
            content=assistant_content,
        )
        session.add(assistant_msg)
        await session.commit()
        await session.refresh(assistant_msg)

        return DiscussionMessageResponse(
            id=assistant_msg.id,
            article_id=assistant_msg.article_id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            created_at=assistant_msg.created_at,
        )

    async def get_thread(
        self,
        article_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> DiscussionThreadResponse:
        """Retrieve the full discussion thread for an article.

        Args:
            article_id: The article ID.
            session: Async database session.
            user_id: Current user ID.

        Returns:
            DiscussionThreadResponse with all messages.

        Raises:
            NotFoundError: If the article doesn't exist or isn't owned by the user.
        """
        await self._get_article_owned_by_user(article_id, session, user_id)

        result = await session.execute(
            select(DiscussionMessage)
            .where(
                DiscussionMessage.article_id == article_id,
                DiscussionMessage.user_id == user_id,
            )
            .order_by(DiscussionMessage.created_at)  # type: ignore[arg-type]
        )
        messages = list(result.scalars().all())

        return DiscussionThreadResponse(
            article_id=article_id,
            messages=[
                DiscussionMessageResponse(
                    id=msg.id,
                    article_id=msg.article_id,
                    role=msg.role,
                    content=msg.content,
                    created_at=msg.created_at,
                )
                for msg in messages
            ],
        )

    async def compile_with_guidance(
        self,
        article_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> CompileWithGuidanceResponse:
        """Trigger recompilation incorporating discussion as guidance.

        Distills the discussion thread into guidance text and enqueues
        a recompile job with that guidance.

        Args:
            article_id: The article to recompile.
            session: Async database session.
            user_id: Current user ID.

        Returns:
            CompileWithGuidanceResponse with job info.

        Raises:
            NotFoundError: If the article doesn't exist or isn't owned by the user.
        """
        article = await self._get_article_owned_by_user(article_id, session, user_id)

        # Collect discussion messages
        result = await session.execute(
            select(DiscussionMessage)
            .where(
                DiscussionMessage.article_id == article_id,
                DiscussionMessage.user_id == user_id,
            )
            .order_by(DiscussionMessage.created_at)  # type: ignore[arg-type]
        )
        messages = list(result.scalars().all())

        # Distill discussion into guidance
        if messages:
            user_points = [msg.content for msg in messages if msg.role == "user"]
            guidance = "User discussion points:\n" + "\n".join(f"- {point}" for point in user_points)
        else:
            guidance = ""

        # Parse source IDs from the article
        source_ids: list[str] = []
        if article.source_ids:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                source_ids = json.loads(article.source_ids)

        # Also check the join table
        if not source_ids:
            src_result = await session.execute(
                select(ArticleSource.source_id).where(ArticleSource.article_id == article_id)
            )
            source_ids = [row[0] for row in src_result.all()]

        # Create recompile job with guidance stored in result_summary
        job = Job(
            user_id=user_id,
            job_type=JobType.RECOMPILE_ARTICLE,
            article_id=article_id,
            source_id=source_ids[0] if source_ids else None,
            result_summary=guidance[:2000] if guidance else None,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        # Dispatch the recompilation via the background compiler
        compiler = get_background_compiler()
        await compiler.schedule_recompile(article_id, "source", job.id, user_id=user_id)

        log.info(
            "discussion-guided recompile queued",
            article_id=article_id,
            job_id=job.id,
            message_count=len(messages),
        )

        return CompileWithGuidanceResponse(
            status="queued",
            job_id=job.id,
        )
