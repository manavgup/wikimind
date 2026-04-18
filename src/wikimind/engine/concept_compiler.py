"""Registry-driven concept page compiler."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    Backlink,
    CompletionRequest,
    Concept,
    ConceptCompilationResult,
    ConceptKindDef,
    PageType,
    Provider,
    RelationType,
    TaskType,
)
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()

PROMPT_TEMPLATES: dict[str, str] = {
    "concept_synthesis_topic": """You are synthesizing a concept page for a personal knowledge wiki.
The concept is "{concept_name}" ({concept_description}).
Below are summaries from {source_count} source articles tagged with this concept.

{source_material}

{contradiction_section}

Produce a synthesis: Overview, Key Themes (JSON list), Consensus & Conflicts,
Open Questions (JSON list), Timeline, Sources Summary, Article Body (## headings, 300+ words),
Related Concepts (JSON list).

Output as JSON:
{{"title": "string", "overview": "string", "key_themes": ["string"],
"consensus_conflicts": "string", "open_questions": ["string"],
"timeline": "string", "sources_summary": "string",
"article_body": "string", "related_concepts": ["string"]}}

Valid JSON only. No preamble, no markdown fences.""",
    "concept_synthesis_person": """You are synthesizing a concept page about a person.
The person is "{concept_name}" ({concept_description}).
Below are summaries from {source_count} source articles.

{source_material}

{contradiction_section}

Produce a synthesis with the same JSON schema as above.
Valid JSON only. No preamble, no markdown fences.""",
    "concept_synthesis_org": """You are synthesizing a concept page about an organization.
The organization is "{concept_name}" ({concept_description}).
Below are summaries from {source_count} source articles.

{source_material}

{contradiction_section}

Produce a synthesis with the same JSON schema as above.
Valid JSON only. No preamble, no markdown fences.""",
    "concept_synthesis_product": """You are synthesizing a concept page about a product.
The product is "{concept_name}" ({concept_description}).
Below are summaries from {source_count} source articles.

{source_material}

{contradiction_section}

Produce a synthesis with the same JSON schema as above.
Valid JSON only. No preamble, no markdown fences.""",
    "concept_synthesis_paper": """You are synthesizing a concept page about a research paper.
The paper is "{concept_name}" ({concept_description}).
Below are summaries from {source_count} source articles.

{source_material}

{contradiction_section}

Produce a synthesis with the same JSON schema as above.
Valid JSON only. No preamble, no markdown fences.""",
}


def get_prompt_template(template_key: str) -> str | None:
    """Look up a prompt template by key."""
    return PROMPT_TEMPLATES.get(template_key)


async def _collect_source_articles(concept_name: str, session: AsyncSession) -> list[Article]:
    normalized = slugify(concept_name)
    result = await session.execute(select(Article))
    articles: list[Article] = []
    for article in result.scalars().all():
        if article.page_type != PageType.SOURCE:
            continue
        if not article.concept_ids:
            continue
        try:
            concept_ids = json.loads(article.concept_ids)
        except (TypeError, ValueError):
            continue
        if not isinstance(concept_ids, list):
            continue
        for cid in concept_ids:
            if slugify(str(cid)) == normalized:
                articles.append(article)
                break
    return articles


def _build_source_material(articles: list[Article]) -> str:
    parts: list[str] = []
    for i, article in enumerate(articles, 1):
        section = f"### Source {i}: {article.title}\n"
        if article.summary:
            section += f"Summary: {article.summary}\n"
        try:
            fc = resolve_wiki_path(article.file_path).read_text(encoding="utf-8")
            if len(fc) > 5000:
                fc = fc[:5000] + "\n[...truncated...]"
            section += f"\nContent:\n{fc}\n"
        except (OSError, ValueError):
            pass
        parts.append(section)
    return "\n---\n".join(parts)


async def _collect_contradictions(source_article_ids: list[str], session: AsyncSession) -> str:
    if not source_article_ids:
        return ""
    result = await session.execute(
        select(Backlink).where(
            Backlink.relation_type == RelationType.CONTRADICTS,
            Backlink.source_article_id.in_(source_article_ids),  # type: ignore[attr-defined]
            Backlink.target_article_id.in_(source_article_ids),  # type: ignore[attr-defined]
        )
    )
    contradictions = list(result.scalars().all())
    if not contradictions:
        return ""
    lines: list[str] = ["Known contradictions between sources:"]
    for bl in contradictions:
        line = f"- Article {bl.source_article_id} vs {bl.target_article_id}"
        if bl.context:
            line += f": {bl.context}"
        if bl.resolution:
            line += f" [RESOLVED: {bl.resolution}]"
            if bl.resolution_note:
                line += f" -- {bl.resolution_note}"
        else:
            line += " [UNRESOLVED]"
        lines.append(line)
    return "\n".join(lines)


class ConceptCompiler:
    """Registry-driven compiler that synthesizes concept pages from source articles."""

    def __init__(self) -> None:
        self.router = get_llm_router()
        self.settings = get_settings()
        self._last_provider_used: Provider | None = None

    async def compile_concept_page(self, concept: Concept, session: AsyncSession) -> Article | None:
        """Compile a concept page by synthesizing all source articles tagged with this concept."""
        kind_def = await self._load_kind_def(concept.concept_kind, session)
        if kind_def is None:
            kind_def = await self._load_kind_def("topic", session)
            if kind_def is None:
                return None
        template = get_prompt_template(kind_def.prompt_template_key)
        if template is None:
            return None
        source_articles = await _collect_source_articles(concept.name, session)
        min_sources = self.settings.taxonomy.concept_page_min_sources
        if len(source_articles) < min_sources:
            return None
        source_material = _build_source_material(source_articles)
        source_ids = [a.id for a in source_articles]
        ct = await _collect_contradictions(source_ids, session)
        contradiction_section = ct if ct else "No known contradictions."
        prompt = template.format(
            concept_name=concept.description or concept.name,
            concept_description=concept.description or concept.name,
            source_count=len(source_articles),
            source_material=source_material,
            contradiction_section=contradiction_section,
        )
        request = CompletionRequest(
            system=prompt,
            messages=[{"role": "user", "content": "Synthesize a concept page from these sources."}],
            max_tokens=8192,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.COMPILE,
        )
        try:
            response = await self.router.complete(request, session=session)
            self._last_provider_used = response.provider_used
        except Exception:
            return None
        try:
            data = self.router.parse_json_response(response)
            compilation = ConceptCompilationResult(**data)
        except Exception:
            return None
        return await self._save_concept_page(compilation, concept, source_articles, session)

    async def _load_kind_def(self, kind_name: str, session: AsyncSession) -> ConceptKindDef | None:
        result = await session.execute(select(ConceptKindDef).where(ConceptKindDef.name == kind_name))
        return result.scalar_one_or_none()

    async def _save_concept_page(
        self,
        compilation: ConceptCompilationResult,
        concept: Concept,
        source_articles: list[Article],
        session: AsyncSession,
    ) -> Article:
        slug = slugify(concept.name)
        now = utcnow_naive()
        source_ids = [a.id for a in source_articles]
        existing = await self._find_existing_concept_article(concept.name, session)
        relative_path = self._write_concept_file(compilation, concept, source_articles)
        if existing is not None:
            resolve_wiki_path(existing.file_path).unlink(missing_ok=True)
            existing.title = compilation.title
            existing.summary = compilation.overview
            existing.file_path = relative_path
            existing.concept_ids = json.dumps([concept.name])
            existing.source_ids = json.dumps(source_ids)
            existing.provider = self._last_provider_used
            existing.updated_at = now
            existing.page_type = PageType.CONCEPT
            session.add(existing)
            old_links = await session.execute(
                select(Backlink).where(
                    Backlink.source_article_id == existing.id, Backlink.relation_type == RelationType.SYNTHESIZES
                )
            )
            for bl in old_links.scalars().all():
                await session.delete(bl)
            await session.commit()
            await session.refresh(existing)
            article = existing
        else:
            article = Article(
                slug=f"concept-{slug}",
                title=compilation.title,
                file_path=relative_path,
                summary=compilation.overview,
                concept_ids=json.dumps([concept.name]),
                source_ids=json.dumps(source_ids),
                provider=self._last_provider_used,
                page_type=PageType.CONCEPT,
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
        await self._create_synthesizes_links(article.id, source_ids, session)
        await self._create_related_to_links(article, compilation.related_concepts, session)
        return article

    async def _find_existing_concept_article(self, concept_name: str, session: AsyncSession) -> Article | None:
        slug = f"concept-{slugify(concept_name)}"
        result = await session.execute(
            select(Article).where(Article.slug == slug, Article.page_type == PageType.CONCEPT)
        )
        return result.scalar_one_or_none()

    def _write_concept_file(
        self, compilation: ConceptCompilationResult, concept: Concept, source_articles: list[Article]
    ) -> str:
        """Write concept page markdown. Returns wiki-relative path."""
        wiki_dir = Path(self.settings.data_dir) / "wiki"
        slug = slugify(concept.name)
        concept_dir = wiki_dir / slug
        concept_dir.mkdir(parents=True, exist_ok=True)
        file_path = concept_dir / f"{slug}.md"
        now = utcnow_naive()
        source_ids = [a.id for a in source_articles]
        sources_lines = [f"- [{a.title}](/wiki/{a.id})" for a in source_articles]
        themes = "\n".join(f"- {t}" for t in compilation.key_themes)
        questions = "\n".join(f"- {q}" for q in compilation.open_questions)
        related = "\n".join(f"- [[{r}]]" for r in compilation.related_concepts)
        content = f"""---
page_type: concept
title: "{compilation.title}"
slug: concept-{slug}
concept_id: {concept.id}
concept_kind: {concept.concept_kind}
synthesized_from: {json.dumps(source_ids)}
source_count: {len(source_articles)}
last_synthesized: {now.isoformat()}
provider: {self._last_provider_used or "unknown"}
---

## Overview

{compilation.overview}

## Key Themes

{themes}

## Consensus & Conflicts

{compilation.consensus_conflicts}

## Open Questions

{questions}

## Timeline

{compilation.timeline}

## Analysis

{compilation.article_body}

## Related Concepts

{related}

## Sources

{chr(10).join(sources_lines)}

## Sources Summary

{compilation.sources_summary}
"""
        file_path.write_text(content, encoding="utf-8")
        return str(file_path.relative_to(wiki_dir))

    async def _create_synthesizes_links(
        self, concept_article_id: str, source_article_ids: list[str], session: AsyncSession
    ) -> None:
        for source_id in source_article_ids:
            # Guard against duplicate Backlinks (issue #152).
            existing = await session.execute(
                select(Backlink).where(
                    Backlink.source_article_id == concept_article_id,
                    Backlink.target_article_id == source_id,
                )
            )
            if existing.scalars().first() is not None:
                continue
            bl = Backlink(
                source_article_id=concept_article_id,
                target_article_id=source_id,
                relation_type=RelationType.SYNTHESIZES,
                context="Concept page synthesizes from source article",
            )
            session.add(bl)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def _create_related_to_links(
        self, concept_article: Article, related_concepts: list[str], session: AsyncSession
    ) -> None:
        if not related_concepts:
            return
        for related_name in related_concepts:
            normalized = slugify(related_name)
            if not normalized:
                continue
            target_slug = f"concept-{normalized}"
            result = await session.execute(
                select(Article).where(Article.slug == target_slug, Article.page_type == PageType.CONCEPT)
            )
            target = result.scalar_one_or_none()
            if target is None:
                continue
            for src_id, tgt_id in [(concept_article.id, target.id), (target.id, concept_article.id)]:
                # Guard against duplicate Backlinks (issue #152).
                existing = await session.execute(
                    select(Backlink).where(
                        Backlink.source_article_id == src_id,
                        Backlink.target_article_id == tgt_id,
                    )
                )
                if existing.scalars().first() is not None:
                    continue
                bl = Backlink(
                    source_article_id=src_id,
                    target_article_id=tgt_id,
                    relation_type=RelationType.RELATED_TO,
                    context=f"Related: {concept_article.title} <-> {target.title}",
                )
                session.add(bl)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
