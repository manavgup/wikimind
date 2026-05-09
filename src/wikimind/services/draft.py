"""Service layer for compilation draft management (issue #418).

When ``compilation.interactive`` is enabled, the worker creates a draft
instead of finalizing the article immediately. The user reviews key
takeaways, optionally provides guidance, and approves or rejects the
draft via the API.
"""

import functools
import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.engine.compiler import Compiler
from wikimind.errors import NotFoundError
from wikimind.models import (
    ApproveDraftResponse,
    CompilationDraft,
    CompilationDraftResponse,
    CompilationResult,
    IngestStatus,
    NormalizedDocument,
    RejectDraftResponse,
    Source,
)
from wikimind.storage import get_raw_storage

log = structlog.get_logger()


class DraftService:
    """Manage compilation drafts for interactive review."""

    async def create_draft(
        self,
        source: Source,
        doc: NormalizedDocument,
        result: CompilationResult,
        takeaways: list[str],
        session: AsyncSession,
    ) -> CompilationDraft:
        """Create a draft from a compilation result and extracted takeaways.

        Args:
            source: The source being compiled.
            doc: The normalized document.
            result: The LLM's compilation result.
            takeaways: Extracted key takeaways.
            session: Async database session.

        Returns:
            The persisted CompilationDraft row.
        """
        draft = CompilationDraft(
            user_id=source.user_id,
            source_id=source.id,
            title=result.title,
            summary=result.summary,
            key_takeaways=json.dumps(takeaways),
            draft_result_json=result.model_dump_json(),
            status="pending",
        )
        session.add(draft)

        source.status = IngestStatus.REVIEW_PENDING
        session.add(source)

        await session.commit()
        await session.refresh(draft)

        log.info(
            "compilation draft created",
            draft_id=draft.id,
            source_id=source.id,
            takeaways_count=len(takeaways),
        )
        return draft

    async def get_draft_for_source(
        self,
        source_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> CompilationDraft:
        """Retrieve the pending draft for a source.

        Args:
            source_id: The source UUID.
            session: Async database session.
            user_id: Verify ownership.

        Returns:
            The CompilationDraft row.

        Raises:
            NotFoundError: If no pending draft exists for this source.
        """
        result = await session.execute(
            select(CompilationDraft).where(
                CompilationDraft.source_id == source_id,
                CompilationDraft.user_id == user_id,
                CompilationDraft.status == "pending",
            )
        )
        draft = result.scalars().first()
        if not draft:
            msg = "No pending draft for this source"
            raise NotFoundError(msg)
        return draft

    def to_response(self, draft: CompilationDraft) -> CompilationDraftResponse:
        """Convert a draft row to an API response.

        Args:
            draft: The CompilationDraft row.

        Returns:
            CompilationDraftResponse with parsed takeaways and draft body.
        """
        takeaways = json.loads(draft.key_takeaways)
        result_data = json.loads(draft.draft_result_json)
        return CompilationDraftResponse(
            id=draft.id,
            source_id=draft.source_id,
            title=draft.title,
            summary=draft.summary,
            key_takeaways=takeaways,
            draft_body=result_data.get("article_body", ""),
            status=draft.status,
            created_at=draft.created_at,
            reviewed_at=draft.reviewed_at,
        )

    async def approve_draft(
        self,
        source_id: str,
        session: AsyncSession,
        user_id: str,
        guidance: str | None = None,
    ) -> ApproveDraftResponse:
        """Approve a draft, optionally with user guidance for re-compilation.

        When guidance is provided, the source is re-compiled with the user's
        focus direction. Otherwise the original draft result is saved directly.

        Args:
            source_id: The source UUID.
            session: Async database session.
            user_id: Verify ownership.
            guidance: Optional user-provided focus direction.

        Returns:
            ApproveDraftResponse with the saved article info.

        Raises:
            NotFoundError: If no pending draft exists.
        """
        draft = await self.get_draft_for_source(source_id, session, user_id)
        source = await session.get(Source, source_id)
        if not source:
            msg = "Source not found"
            raise NotFoundError(msg)

        compiler = Compiler(user_id=user_id)

        if guidance:
            draft.user_guidance = guidance
            # Re-read the source and compile with guidance
            raw_storage = get_raw_storage(user_id)
            if not source.file_path:
                msg = "Source has no content file"
                raise NotFoundError(msg)
            content = await raw_storage.read(source.file_path)
            from wikimind.ingest.service import (  # noqa: PLC0415
                chunk_text,
                estimate_tokens,
            )

            doc = NormalizedDocument(
                raw_source_id=source.id,
                clean_text=content,
                title=source.title or "Untitled",
                author=source.author,
                published_date=source.published_date,
                estimated_tokens=estimate_tokens(content),
                chunks=chunk_text(content, source.id),
            )
            result = await compiler.compile_with_guidance(doc, session, guidance)
            if not result:
                msg = "Guided compilation failed"
                raise NotFoundError(msg)
        else:
            result = CompilationResult.model_validate_json(draft.draft_result_json)

        article = await compiler.save_article(result, source, session)

        draft.status = "approved"
        draft.reviewed_at = utcnow_naive()
        session.add(draft)
        await session.commit()

        log.info(
            "draft approved",
            draft_id=draft.id,
            article_slug=article.slug,
            had_guidance=guidance is not None,
        )
        return ApproveDraftResponse(
            status="approved",
            article_slug=article.slug,
            article_title=article.title,
        )

    async def reject_draft(
        self,
        source_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> RejectDraftResponse:
        """Reject a draft and reset the source to pending.

        The user can re-ingest or retry compilation later.

        Args:
            source_id: The source UUID.
            session: Async database session.
            user_id: Verify ownership.

        Returns:
            RejectDraftResponse.

        Raises:
            NotFoundError: If no pending draft exists.
        """
        draft = await self.get_draft_for_source(source_id, session, user_id)
        source = await session.get(Source, source_id)
        if not source:
            msg = "Source not found"
            raise NotFoundError(msg)

        draft.status = "rejected"
        draft.reviewed_at = utcnow_naive()
        session.add(draft)

        source.status = IngestStatus.PENDING
        session.add(source)

        await session.commit()

        log.info("draft rejected", draft_id=draft.id, source_id=source_id)
        return RejectDraftResponse(status="rejected", source_id=source_id)


@functools.lru_cache(maxsize=1)
def get_draft_service() -> DraftService:
    """Return a singleton DraftService instance for FastAPI DI."""
    return DraftService()
