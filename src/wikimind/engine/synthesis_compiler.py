"""Synthesis page compiler — cross-cutting analysis across multiple sources.

Takes a user query/topic, identifies relevant articles in the wiki,
and produces a synthesis page that compares, contrasts, and finds
patterns across those sources.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.base_compiler import BaseCompiler
from wikimind.engine.prompts import SYNTHESIS_SYSTEM_PROMPT
from wikimind.models import (
    Article,
    ArticleConcept,
    ConfidenceLevel,
    PageType,
    SynthesisCompilationResult,
)
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


async def _find_relevant_articles(
    query: str,
    session: AsyncSession,
    user_id: str,
    article_ids: list[str] | None = None,
) -> list[Article]:
    """Find articles relevant to a synthesis query.

    If ``article_ids`` is provided, use those directly. Otherwise, search
    by matching concepts and titles against the query terms.
    """
    if article_ids:
        result = await session.execute(
            select(Article).where(
                Article.id.in_(article_ids),  # type: ignore[attr-defined]
                Article.user_id == user_id,
            )
        )
        return list(result.scalars().all())

    # Keyword-based relevance: match query terms against article titles,
    # concepts, and summaries. Simple but effective for personal wikis.
    query_terms = [t.lower() for t in query.split() if len(t) > 2]
    result = await session.execute(
        select(Article).where(
            Article.user_id == user_id,
            Article.page_type.in_(  # type: ignore[attr-defined]
                [PageType.SOURCE, PageType.CONCEPT]
            ),
        )
    )
    all_articles = list(result.scalars().all())

    scored: list[tuple[float, Article]] = []
    for article in all_articles:
        score = 0.0
        title_lower = article.title.lower()
        summary_lower = (article.summary or "").lower()
        concepts_lower = (article.concept_ids or "").lower()

        for term in query_terms:
            if term in title_lower:
                score += 3.0
            if term in summary_lower:
                score += 2.0
            if term in concepts_lower:
                score += 1.5

        if score > 0:
            scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    settings = get_settings()
    max_articles = settings.compiler.synthesis_max_sources
    return [article for _, article in scored[:max_articles]]


async def _build_synthesis_material(
    articles: list[Article],
    user_id: str,
) -> str:
    """Build the source material string from multiple articles."""
    max_chars = get_settings().compiler.concept_source_max_chars
    storage = get_wiki_storage(user_id)
    parts: list[str] = []
    for i, article in enumerate(articles, 1):
        section = f"### Source {i}: {article.title} (ID: {article.id})\n"
        if article.summary:
            section += f"Summary: {article.summary}\n"
        try:
            fc = await storage.read(article.file_path)
            if len(fc) > max_chars:
                fc = fc[:max_chars] + "\n[...truncated...]"
            section += f"\nContent:\n{fc}\n"
        except (OSError, ValueError):
            # File may not exist or be unreadable — skip content but keep the
            # article header so the LLM still sees the title and summary.
            pass
        parts.append(section)
    return "\n---\n".join(parts)


class SynthesisCompiler(BaseCompiler):
    """Compile synthesis pages from multiple wiki articles."""

    async def preview(
        self,
        session: AsyncSession,
        article_ids: list[str],
        synthesis_type: str | None = None,
        guidance: str | None = None,
    ) -> SynthesisCompilationResult | None:
        """Generate a synthesis draft without persisting it.

        Returns a SynthesisCompilationResult for preview, or None if
        synthesis could not be performed (e.g. articles not found).
        """
        articles = await _find_relevant_articles(
            guidance or "synthesis",
            session,
            self.user_id,
            article_ids=article_ids,
        )
        if len(articles) < 2:
            log.warning(
                "Not enough articles for synthesis preview",
                found=len(articles),
            )
            return None

        source_material = await _build_synthesis_material(
            articles,
            self.user_id,
        )

        prompt_parts = [
            f"Number of source articles: {len(articles)}\n\n",
            f"{source_material}\n\n",
            "Synthesize a cross-cutting analysis page from these sources.",
        ]
        if synthesis_type:
            prompt_parts.insert(0, f"Synthesis type: {synthesis_type}\n")
        if guidance:
            prompt_parts.insert(0, f"User guidance: {guidance}\n")

        prompt = "".join(prompt_parts)

        await session.commit()

        response = await self._call_llm(
            system=SYNTHESIS_SYSTEM_PROMPT,
            user_content=prompt,
            session=session,
        )
        if response is None:
            return None

        data = self._parse_json_response(response)
        if data is None:
            return None
        try:
            data["query"] = guidance or "synthesis preview"
            data["source_article_ids"] = [a.id for a in articles]
            return SynthesisCompilationResult(**data)
        except (KeyError, ValueError, TypeError):
            log.warning(
                "Synthesis preview response validation failed",
                exc_info=True,
            )
            return None

    async def refine(
        self,
        session: AsyncSession,
        article_ids: list[str],
        previous_draft: str,
        guidance: str,
    ) -> SynthesisCompilationResult | None:
        """Regenerate a synthesis draft incorporating user feedback.

        Returns a refined SynthesisCompilationResult, or None on failure.
        """
        articles = await _find_relevant_articles(
            guidance,
            session,
            self.user_id,
            article_ids=article_ids,
        )
        if len(articles) < 2:
            log.warning(
                "Not enough articles for synthesis refine",
                found=len(articles),
            )
            return None

        source_material = await _build_synthesis_material(
            articles,
            self.user_id,
        )

        prompt = (
            f"Previous draft (needs revision):\n{previous_draft}\n\n"
            f"User feedback: {guidance}\n\n"
            f"Source articles ({len(articles)}):\n{source_material}\n\n"
            "Revise the synthesis based on the user's feedback. "
            "Produce a complete new synthesis (not just the changes)."
        )

        await session.commit()

        response = await self._call_llm(
            system=SYNTHESIS_SYSTEM_PROMPT,
            user_content=prompt,
            session=session,
        )
        if response is None:
            return None

        data = self._parse_json_response(response)
        if data is None:
            return None
        try:
            data["query"] = guidance
            data["source_article_ids"] = [a.id for a in articles]
            return SynthesisCompilationResult(**data)
        except (KeyError, ValueError, TypeError):
            log.warning(
                "Synthesis refine response validation failed",
                exc_info=True,
            )
            return None

    async def confirm(
        self,
        session: AsyncSession,
        title: str,
        draft_content: str,
        article_ids: list[str],
    ) -> Article | None:
        """Save a confirmed draft as a real synthesis article.

        Returns the persisted Article, or None if articles not found.
        """
        articles = await _find_relevant_articles(
            "confirm",
            session,
            self.user_id,
            article_ids=article_ids,
        )
        if len(articles) < 2:
            log.warning(
                "Not enough articles for synthesis confirm",
                found=len(articles),
            )
            return None

        slug = await self._generate_unique_slug(title, session, prefix="synthesis-", max_length=70)
        source_ids = [a.id for a in articles]

        # Extract a summary from the first ~200 chars of draft content
        summary = draft_content[:200].strip()
        if len(draft_content) > 200:
            summary += "..."

        # Extract concepts from source articles (union of all source concepts)
        concepts: list[str] = []
        seen: set[str] = set()
        for a in articles:
            for c in json.loads(a.concept_ids or "[]"):
                if c not in seen:
                    seen.add(c)
                    concepts.append(c)

        article = Article(
            slug=slug,
            title=title,
            file_path="",
            summary=summary,
            concept_ids=json.dumps(concepts),
            source_ids=json.dumps(source_ids),
            provider=self._last_provider_used,
            page_type=PageType.SYNTHESIS,
            confidence=ConfidenceLevel.INFERRED,
            user_id=self.user_id,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)

        # Write the markdown file
        relative_path = f"synthesis/{slug}.md"
        storage = get_wiki_storage(self.user_id)
        await storage.write(relative_path, draft_content)

        article.file_path = relative_path
        session.add(article)
        await session.commit()

        # Populate concept join table
        for concept_name in concepts:
            session.add(
                ArticleConcept(
                    article_id=article.id,
                    concept_name=concept_name,
                )
            )
        await session.commit()

        # Update full-text search index
        await self._index_article(session, article.id, article.title, relative_path)

        # Create SYNTHESIZES backlinks to all source articles
        await self._create_synthesizes_links(
            article.id,
            source_ids,
            session,
            user_id=self.user_id,
            context="Synthesis page analyzes this source article",
        )

        log.info(
            "Synthesis draft confirmed and saved",
            slug=slug,
            title=title,
            source_count=len(articles),
        )
        return article

    async def synthesize(
        self,
        query: str,
        session: AsyncSession,
        article_ids: list[str] | None = None,
    ) -> tuple[Article, SynthesisCompilationResult] | None:
        """Create a synthesis page for the given query.

        Returns the persisted Article and the compilation result, or None
        if synthesis could not be performed (e.g. no relevant articles).
        """
        articles = await _find_relevant_articles(
            query,
            session,
            self.user_id,
            article_ids=article_ids,
        )
        if len(articles) < 2:
            log.warning(
                "Not enough articles for synthesis",
                query=query,
                found=len(articles),
            )
            return None

        source_material = await _build_synthesis_material(
            articles,
            self.user_id,
        )

        prompt = (
            f"Synthesis query: {query}\n\n"
            f"Number of source articles: {len(articles)}\n\n"
            f"{source_material}\n\n"
            "Synthesize a cross-cutting analysis page from these sources."
        )

        # Release the DB connection before the long-running LLM call to
        # avoid PgBouncer idle-connection timeouts (same pattern as Compiler).
        await session.commit()

        response = await self._call_llm(
            system=SYNTHESIS_SYSTEM_PROMPT,
            user_content=prompt,
            session=session,
        )
        if response is None:
            return None

        data = self._parse_json_response(response)
        if data is None:
            return None
        try:
            data["query"] = query
            data["source_article_ids"] = [a.id for a in articles]
            compilation = SynthesisCompilationResult(**data)
        except (KeyError, ValueError, TypeError):
            log.warning(
                "Synthesis response validation failed",
                query=query,
                exc_info=True,
            )
            return None

        article = await self._save_synthesis_page(compilation, articles, session)
        return article, compilation

    async def _save_synthesis_page(
        self,
        compilation: SynthesisCompilationResult,
        source_articles: list[Article],
        session: AsyncSession,
    ) -> Article:
        """Persist a synthesis page as a wiki article."""
        slug = await self._generate_unique_slug(compilation.title, session, prefix="synthesis-", max_length=70)
        source_ids = [a.id for a in source_articles]

        article = Article(
            slug=slug,
            title=compilation.title,
            file_path="",  # Set after writing
            summary=compilation.summary,
            concept_ids=json.dumps(compilation.concepts),
            source_ids=json.dumps(source_ids),
            provider=self._last_provider_used,
            page_type=PageType.SYNTHESIS,
            confidence=ConfidenceLevel.INFERRED,
            user_id=self.user_id,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)

        # Write the markdown file
        relative_path = await self._write_synthesis_file(
            compilation,
            source_articles,
            slug,
        )
        article.file_path = relative_path
        session.add(article)
        await session.commit()

        # Populate concept join table
        for concept_name in compilation.concepts:
            session.add(
                ArticleConcept(
                    article_id=article.id,
                    concept_name=concept_name,
                )
            )
        await session.commit()

        # Update full-text search index
        await self._index_article(session, article.id, article.title, relative_path)

        # Create SYNTHESIZES backlinks to all source articles
        await self._create_synthesizes_links(
            article.id,
            source_ids,
            session,
            user_id=self.user_id,
            context="Synthesis page analyzes this source article",
        )

        log.info(
            "Synthesis page saved",
            slug=slug,
            title=compilation.title,
            source_count=len(source_articles),
        )
        return article

    async def _write_synthesis_file(
        self,
        compilation: SynthesisCompilationResult,
        source_articles: list[Article],
        slug: str,
    ) -> str:
        """Write synthesis page markdown. Returns wiki-relative path."""
        now = utcnow_naive()
        relative_path = f"synthesis/{slug}.md"
        source_ids = [a.id for a in source_articles]
        sources_lines = [f"- [{a.title}](/wiki/{a.id})" for a in source_articles]
        themes = "\n".join(f"- {t}" for t in compilation.themes)
        gaps = "\n".join(f"- {g}" for g in compilation.gaps)
        questions = "\n".join(f"- {q}" for q in compilation.open_questions)
        concepts_str = ", ".join(compilation.concepts)
        provider_str = self._last_provider_used or ""

        content = f"""---
page_type: synthesis
title: "{compilation.title}"
slug: {slug}
query: "{compilation.query}"
source_article_ids: {json.dumps(source_ids)}
source_count: {len(source_articles)}
synthesized_at: {now.isoformat()}
concepts: [{concepts_str}]
confidence: inferred
provider: {provider_str}
---

## Summary

{compilation.summary}

## Themes

{themes}

## Comparative Analysis

{compilation.comparisons}

## Contradictions & Conflicts

{compilation.contradictions}

## Timeline

{compilation.timeline}

## Analysis

{compilation.article_body}

## Knowledge Gaps

{gaps}

## Open Questions

{questions}

## Sources Analyzed

{chr(10).join(sources_lines)}
"""
        storage = get_wiki_storage(self.user_id)
        await storage.write(relative_path, content)
        return relative_path

    # _generate_unique_slug and _create_synthesizes_links are inherited from BaseCompiler
