"""Registry-driven concept page compiler."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import _dialect_insert
from wikimind.engine.base_compiler import BaseCompiler
from wikimind.engine.prompts import CONCEPT_PROMPT_TEMPLATES as PROMPT_TEMPLATES
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    CompletionResponse,
    Concept,
    ConceptCompilationResult,
    ConceptKindDef,
    PageType,
    RelationType,
)
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


def get_prompt_template(template_key: str) -> str | None:
    """Look up a prompt template by key."""
    return PROMPT_TEMPLATES.get(template_key)


async def _collect_source_articles(
    concept_name: str,
    session: AsyncSession,
    *,
    user_id: str | None = None,
) -> list[Article]:
    normalized = slugify(concept_name)
    stmt = (
        select(Article)
        .join(ArticleConcept, ArticleConcept.article_id == Article.id)  # type: ignore[arg-type]
        .where(ArticleConcept.concept_name == normalized, Article.page_type == PageType.SOURCE)
    )
    if user_id:
        stmt = stmt.where(Article.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _build_source_material(articles: list[Article], user_id: str) -> str:
    max_chars = get_settings().compiler.concept_source_max_chars
    storage = get_wiki_storage(user_id)
    parts: list[str] = []
    for i, article in enumerate(articles, 1):
        section = f"### Source {i}: {article.title}\n"
        if article.summary:
            section += f"Summary: {article.summary}\n"
        try:
            fc = await storage.read(article.file_path)
            if len(fc) > max_chars:
                fc = fc[:max_chars] + "\n[...truncated...]"
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


class ConceptCompiler(BaseCompiler):
    """Registry-driven compiler that synthesizes concept pages from source articles."""

    async def compile_concept_page(self, concept: Concept, session: AsyncSession) -> Article | None:
        """Compile a concept page by synthesizing all source articles tagged with this concept."""
        kind_def = await self._load_kind_def(concept.concept_kind, session)
        if kind_def is None:
            kind_def = await self._load_kind_def("topic", session)
        template = get_prompt_template(kind_def.prompt_template_key) if kind_def else None
        if template is None:
            return None
        source_articles = await _collect_source_articles(concept.name, session, user_id=self.user_id)
        min_sources = self.settings.taxonomy.concept_page_min_sources
        if len(source_articles) < min_sources:
            return None
        source_material = await _build_source_material(source_articles, user_id=self.user_id)
        source_ids = [a.id for a in source_articles]
        ct = await _collect_contradictions(source_ids, session)
        contradiction_section = ct or "No known contradictions."
        prompt = template.format(
            concept_name=concept.description or concept.name,
            concept_description=concept.description or concept.name,
            source_count=len(source_articles),
            source_material=source_material,
            contradiction_section=contradiction_section,
        )

        # Release the DB connection before the long-running LLM call to
        # avoid PgBouncer idle-connection timeouts (same pattern as Compiler).
        await session.commit()

        response = await self._call_llm(
            system=prompt,
            user_content="Synthesize a concept page from these sources.",
        )
        if response is None:
            return None

        compilation = self._parse_concept_response(response, concept.name)
        if compilation is None:
            return None
        return await self._save_concept_page(compilation, concept, source_articles, session)

    def _parse_concept_response(
        self, response: CompletionResponse, concept_name: str
    ) -> ConceptCompilationResult | None:
        """Parse and validate an LLM response into a ConceptCompilationResult."""
        data = self._parse_json_response(response)
        if data is None:
            return None
        try:
            return ConceptCompilationResult(**data)
        except (KeyError, ValueError, TypeError):
            log.warning(
                "Concept page response validation failed",
                concept=concept_name,
                exc_info=True,
            )
            return None

    async def _load_kind_def(self, kind_name: str, session: AsyncSession) -> ConceptKindDef | None:
        result = await session.exec(select(ConceptKindDef).where(ConceptKindDef.name == kind_name))
        return result.one_or_none()

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
        # Compute the relative path that _write_concept_file will produce,
        # but defer writing until after the DB commit succeeds (#169).
        relative_path = f"{slug}/{slug}.md"
        if existing is not None:
            existing.title = compilation.title
            existing.summary = compilation.overview
            existing.file_path = relative_path
            existing.concept_ids = json.dumps([concept.name])
            existing.source_ids = json.dumps(source_ids)
            existing.provider = self._last_provider_used
            existing.updated_at = now
            existing.page_type = PageType.CONCEPT
            existing.user_id = concept.user_id
            session.add(existing)
            old_links = await session.exec(
                select(Backlink).where(
                    Backlink.source_article_id == existing.id,
                    Backlink.relation_type == RelationType.SYNTHESIZES,
                )
            )
            for bl in old_links.all():
                await session.delete(bl)
            # Refresh join tables
            old_ac = await session.exec(select(ArticleConcept).where(ArticleConcept.article_id == existing.id))
            for ac in old_ac.all():
                await session.delete(ac)
            old_as = await session.exec(select(ArticleSource).where(ArticleSource.article_id == existing.id))
            for a_s in old_as.all():
                await session.delete(a_s)
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
                user_id=concept.user_id,
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
        # Write the file AFTER DB commit — prevents orphaned DB rows
        # pointing at files that were never written (#169).
        await self._write_concept_file(compilation, concept, source_articles)
        # Populate join tables
        session.add(ArticleConcept(article_id=article.id, concept_name=concept.name))
        for sid in source_ids:
            session.add(ArticleSource(article_id=article.id, source_id=sid))
        await session.commit()

        # Update full-text search index
        await self._index_article(session, article.id, article.title, relative_path)

        await self._create_synthesizes_links(
            article.id,
            source_ids,
            session,
            user_id=self.user_id,
            context="Concept page synthesizes from source article",
        )
        await self._create_related_to_links(article, compilation.related_concepts, session, user_id=self.user_id)
        return article

    async def _find_existing_concept_article(self, concept_name: str, session: AsyncSession) -> Article | None:
        slug = f"concept-{slugify(concept_name)}"
        result = await session.execute(
            select(Article).where(
                Article.slug == slug,
                Article.page_type == PageType.CONCEPT,
                Article.user_id == self.user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _write_concept_file(
        self, compilation: ConceptCompilationResult, concept: Concept, source_articles: list[Article]
    ) -> str:
        """Write concept page markdown. Returns wiki-relative path."""
        slug = slugify(concept.name)
        relative_path = f"{slug}/{slug}.md"
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
        storage = get_wiki_storage(concept.user_id)
        await storage.write(relative_path, content)
        return relative_path

    # _create_synthesizes_links is inherited from BaseCompiler

    async def _create_related_to_links(
        self,
        concept_article: Article,
        related_concepts: list[str],
        session: AsyncSession,
        user_id: str,
    ) -> None:
        if not related_concepts:
            return
        conn = await session.connection()
        insert_fn = _dialect_insert(conn)
        for related_name in related_concepts:
            normalized = slugify(related_name)
            if not normalized:
                continue
            target_slug = f"concept-{normalized}"
            result = await session.execute(
                select(Article).where(
                    Article.slug == target_slug,
                    Article.page_type == PageType.CONCEPT,
                    Article.user_id == user_id,
                )
            )
            target = result.scalar_one_or_none()
            if target is None:
                continue
            for src_id, tgt_id in [(concept_article.id, target.id), (target.id, concept_article.id)]:
                stmt = (
                    insert_fn(Backlink)
                    .values(
                        source_article_id=src_id,
                        target_article_id=tgt_id,
                        relation_type=RelationType.RELATED_TO,
                        context=f"Related: {concept_article.title} <-> {target.title}",
                        user_id=user_id,
                    )
                    .on_conflict_do_nothing()
                )
                await session.execute(stmt)
        await session.commit()
