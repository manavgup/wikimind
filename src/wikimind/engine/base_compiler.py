"""Base compiler with shared utilities for all compiler variants.

Extracts the common constructor, _call_llm(), _generate_unique_slug(),
_index_article(), and _create_synthesizes_links() patterns that were
duplicated across compiler.py, concept_compiler.py, and synthesis_compiler.py.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.database import _dialect_insert
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    Backlink,
    CompletionRequest,
    CompletionResponse,
    Provider,
    RelationType,
    TaskType,
)
from wikimind.services.search import index_article as fts_index_article
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


class BaseCompiler:
    """Shared functionality for all WikiMind compilers."""

    def __init__(self, user_id: str) -> None:
        self.router = get_llm_router()
        self.settings = get_settings()
        self.user_id = user_id
        self._last_provider_used: Provider | None = None

    async def _call_llm(
        self,
        *,
        system: str,
        user_content: str,
        max_tokens: int | None = None,
        temperature: float = 0.3,
        task_type: TaskType = TaskType.COMPILE,
    ) -> CompletionResponse | None:
        """Call the LLM router with standard error handling.

        Returns the CompletionResponse on success, or None if the call fails.
        Sets ``self._last_provider_used`` on success.
        """
        if max_tokens is None:
            max_tokens = self.settings.compiler.max_tokens
        request = CompletionRequest(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format="json",
            task_type=task_type,
        )
        try:
            response = await self.router.complete(request, user_id=self.user_id)
            self._last_provider_used = response.provider_used
            return response
        except (RuntimeError, ValueError):
            log.warning(
                "LLM call failed",
                compiler=type(self).__name__,
                exc_info=True,
            )
            return None

    def _parse_json_response(self, response: CompletionResponse) -> dict | None:
        """Parse JSON from an LLM response with error handling.

        Returns the parsed dict, or None on failure.
        """
        try:
            return self.router.parse_json_response(response)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            log.warning(
                "JSON response parsing failed",
                compiler=type(self).__name__,
                response_preview=response.content[:500] if response.content else "",
                exc_info=True,
            )
            return None

    async def _generate_unique_slug(
        self,
        title: str,
        session: AsyncSession,
        *,
        prefix: str = "",
        max_length: int = 80,
    ) -> str:
        """Generate a URL-safe slug from a title, avoiding collisions.

        Args:
            title: The title to slugify.
            session: Async database session for collision checks.
            prefix: Optional prefix (e.g. "synthesis-") prepended to the slug.
            max_length: Maximum slug length before prefix.

        Raises:
            ValueError: If no unique slug is found within max attempts.
        """
        max_attempts = self.settings.compiler.slug_max_attempts
        base = f"{prefix}{slugify(title, max_length=max_length)}"
        candidate = base
        suffix = 2
        for _ in range(max_attempts):
            existing = (await session.exec(select(Article).where(Article.slug == candidate))).first()
            if existing is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1
        msg = f"Could not generate unique slug for {title!r} after {max_attempts} attempts"
        raise ValueError(msg)

    async def _index_article(
        self,
        session: AsyncSession,
        article_id: str,
        title: str,
        file_path: str,
    ) -> None:
        """Update the full-text search index for a compiled article."""
        wiki_storage = get_wiki_storage(self.user_id)
        try:
            article_content = await wiki_storage.read(file_path)
        except OSError:
            article_content = ""
        await fts_index_article(session, article_id, title, article_content)
        await session.commit()

    async def _create_synthesizes_links(
        self,
        source_article_id: str,
        target_article_ids: list[str],
        session: AsyncSession,
        *,
        user_id: str,
        context: str = "Synthesizes from source article",
    ) -> None:
        """Insert SYNTHESIZES backlinks from a compiled page to its sources."""
        conn = await session.connection()
        insert_fn = _dialect_insert(conn)
        for target_id in target_article_ids:
            stmt = (
                insert_fn(Backlink)
                .values(
                    source_article_id=source_article_id,
                    target_article_id=target_id,
                    relation_type=RelationType.SYNTHESIZES,
                    context=context,
                    user_id=user_id,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
        await session.commit()
