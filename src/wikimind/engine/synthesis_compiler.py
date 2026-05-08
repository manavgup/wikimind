"""Synthesis page compiler — cross-cutting analysis across multiple sources.

Takes a user query/topic, identifies relevant articles in the wiki,
and produces a synthesis page that compares, contrasts, and finds
patterns across those sources.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    ArticleConcept,
    Backlink,
    CompletionRequest,
    ConfidenceLevel,
    PageType,
    Provider,
    RelationType,
    SynthesisCompilationResult,
    TaskType,
)
from wikimind.services.search import index_article as fts_index_article
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

SYNTHESIS_SYSTEM_PROMPT = """You are a knowledge synthesizer. Your job is to analyze \
multiple wiki articles and produce a cross-cutting synthesis page that identifies \
themes, comparisons, contradictions, and knowledge gaps.

The user will provide a synthesis query/topic and the content of multiple source \
articles from their personal wiki.

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{{
  "title": "Concise synthesis page title",
  "summary": "2-3 sentences: what this synthesis covers and key findings.",
  "themes": ["Theme 1", "Theme 2"],
  "comparisons": "Markdown section comparing approaches/perspectives across sources.",
  "contradictions": "Markdown section noting where sources disagree or conflict.",
  "timeline": "Markdown section showing how the topic evolved chronologically.",
  "gaps": ["Knowledge gap 1", "Knowledge gap 2"],
  "open_questions": ["Question for further research"],
  "article_body": "Full markdown body with ## headings. 500+ words. \
Include Themes, Comparative Analysis, Contradictions, Timeline, Gaps sections.",
  "concepts": ["concept-1", "concept-2"]
}}

Rules:
- Synthesize ACROSS sources — do not summarize each source individually
- Identify patterns, trends, and contradictions
- Note where sources agree and disagree
- Highlight knowledge gaps — what is NOT covered
- Be specific: cite which sources support which claims
- article_body must be substantive — at least 500 words
- Never fabricate information not present in the sources
"""


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


class SynthesisCompiler:
    """Compile synthesis pages from multiple wiki articles."""

    def __init__(self, user_id: str) -> None:
        self.router = get_llm_router()
        self.settings = get_settings()
        self.user_id = user_id
        self._last_provider_used: Provider | None = None

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

        request = CompletionRequest(
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.settings.compiler.max_tokens,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        try:
            response = await self.router.complete(request, user_id=self.user_id)
            self._last_provider_used = response.provider_used
        except (RuntimeError, ValueError):
            log.warning("Synthesis LLM call failed", query=query, exc_info=True)
            return None

        try:
            data = self.router.parse_json_response(response)
            data["query"] = query
            data["source_article_ids"] = [a.id for a in articles]
            compilation = SynthesisCompilationResult(**data)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            log.warning(
                "Synthesis response parsing failed",
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
        slug = await self._generate_unique_slug(compilation.title, session)
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
        wiki_storage = get_wiki_storage(self.user_id)
        try:
            article_content = await wiki_storage.read(relative_path)
        except OSError:
            article_content = ""
        await fts_index_article(session, article.id, article.title, article_content)
        await session.commit()

        # Create SYNTHESIZES backlinks to all source articles
        await self._create_synthesizes_links(
            article.id,
            source_ids,
            session,
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

    async def _generate_unique_slug(
        self,
        title: str,
        session: AsyncSession,
    ) -> str:
        """Generate a unique slug prefixed with 'synthesis-'."""
        base = f"synthesis-{slugify(title, max_length=70)}"
        candidate = base
        suffix = 2
        while True:
            existing = (await session.execute(select(Article).where(Article.slug == candidate))).scalars().first()
            if existing is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1

    async def _create_synthesizes_links(
        self,
        synthesis_article_id: str,
        source_article_ids: list[str],
        session: AsyncSession,
    ) -> None:
        """Create SYNTHESIZES backlinks from the synthesis page to sources."""
        for source_id in source_article_ids:
            existing = await session.execute(
                select(Backlink).where(
                    Backlink.source_article_id == synthesis_article_id,
                    Backlink.target_article_id == source_id,
                )
            )
            if existing.scalars().first() is not None:
                continue
            bl = Backlink(
                source_article_id=synthesis_article_id,
                target_article_id=source_id,
                relation_type=RelationType.SYNTHESIZES,
                context="Synthesis page analyzes this source article",
                user_id=self.user_id,
            )
            session.add(bl)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
