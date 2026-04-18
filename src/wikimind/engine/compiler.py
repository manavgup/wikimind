"""WikiMind Compiler.

Transforms normalized source documents into structured wiki articles.
This is the core value-creation step.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.db_compat import is_sqlite, json_array_contains
from wikimind.engine.frontmatter_validator import validate_frontmatter
from wikimind.engine.llm_router import get_llm_router
from wikimind.engine.wikilink_resolver import (
    ResolvedBacklink,
    resolve_backlink_candidates,
)
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompletionRequest,
    Concept,
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    PageType,
    Provider,
    RelationType,
    Source,
    TaskType,
    TypedBacklinkSuggestion,
)
from wikimind.services.activity_log import append_log_entry
from wikimind.services.taxonomy import (
    maybe_trigger_concept_pages,
    maybe_trigger_taxonomy_rebuild,
    update_article_counts,
    upsert_concepts,
)
from wikimind.services.wiki_index import regenerate_index_md
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()


def _normalize_backlink_suggestions(raw: list[str | dict]) -> list[str]:
    """Normalize typed backlink suggestions to plain strings for CompilationResult.

    The LLM may return backlink_suggestions as either:
      - New format: ``[{"target": "Title", "relation_type": "references"}, ...]``
      - Legacy format: ``["Title", ...]``

    This function extracts just the target strings for backward compatibility
    with ``CompilationResult.backlink_suggestions`` (``list[str]``). The typed
    metadata is preserved separately via ``_extract_typed_suggestions()``.
    """
    normalized: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            target = item.get("target", "")
            if target:
                normalized.append(str(target))
        elif isinstance(item, str):
            normalized.append(item)
    return normalized


def _extract_typed_suggestions(raw: list[str | dict]) -> list[TypedBacklinkSuggestion]:
    """Extract TypedBacklinkSuggestion objects from raw LLM output.

    Handles both typed dicts and plain strings (defaulting to ``references``).
    """
    suggestions: list[TypedBacklinkSuggestion] = []
    for item in raw:
        if isinstance(item, dict):
            target = item.get("target", "")
            rel = item.get("relation_type", "references")
            if target:
                try:
                    suggestions.append(TypedBacklinkSuggestion(target=str(target), relation_type=RelationType(rel)))
                except ValueError:
                    suggestions.append(
                        TypedBacklinkSuggestion(target=str(target), relation_type=RelationType.REFERENCES)
                    )
        elif isinstance(item, str) and item.strip():
            suggestions.append(TypedBacklinkSuggestion(target=item, relation_type=RelationType.REFERENCES))
    return suggestions


COMPILER_SYSTEM_PROMPT = """You are a knowledge compiler. Your job is to transform raw source material into a structured wiki article for a personal knowledge base.

The user is building a living wiki -- every article should connect to others, surface open questions, and make their knowledge compound over time.

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{
  "title": "Concise, specific article title",
  "page_type": "source",
  "summary": "Exactly 2 sentences. What this is and why it matters.",
  "key_claims": [
    {
      "claim": "Specific, falsifiable claim from the source",
      "confidence": "sourced|inferred|opinion",
      "quote": "Optional direct quote under 15 words if the exact wording matters"
    }
  ],
  "concepts": ["concept-name-1", "concept-name-2"],
  "backlink_suggestions": [
    {"target": "Title of related article", "relation_type": "references|extends|supersedes"}
  ],
  "open_questions": ["Question this source raises but does not answer"],
  "article_body": "Full markdown article. Use ## headings. Include Key Claims, Analysis, Open Questions sections."
}

Rules:
- page_type is always "source" for source compilations
- Every claim must be attributable to the source
- Mark LLM inferences as confidence=inferred explicitly
- Suggest backlinks only to concepts genuinely related
- For backlink_suggestions, use relation_type "references" (mentions related topic), "extends" (builds on/adds to claims), or "supersedes" (newer source replaces older claims)
- Open questions should drive future research
- article_body must be substantive -- at least 300 words
- Never fabricate quotes or statistics not in the source
- For concepts: reuse existing concept names when they match your intent -- do not invent synonyms or near-duplicates
"""


class Compiler:
    """Compile normalized documents into wiki articles."""

    def __init__(self):
        self.router = get_llm_router()
        self.settings = get_settings()
        # Provider that handled the most recent successful `complete()` call.
        self._last_provider_used: Provider | None = None
        # Typed backlink suggestions from the most recent `compile()` call.
        self._last_typed_suggestions: dict[str, str] = {}

    async def compile(
        self,
        doc: NormalizedDocument,
        session: AsyncSession,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> CompilationResult | None:
        """Compile a normalized document into a wiki article."""
        log.info("Compiling document", title=doc.title, tokens=doc.estimated_tokens)

        # For large documents, compile in chunks and merge
        if doc.estimated_tokens > 80_000:
            return await self._compile_chunked(doc, session, progress_callback)

        user_prompt = self._build_user_prompt(doc)

        # Concept ID registry injection: prevents concept fragmentation by
        # telling the LLM which concepts already exist (issue #143, Phase 2).
        existing_concepts = [c.name for c in (await session.execute(select(Concept))).scalars().all()]
        if existing_concepts:
            user_prompt += "\n\nExisting concepts in this wiki (REUSE these before inventing new ones):\n" + ", ".join(
                sorted(existing_concepts)
            )

        request = CompletionRequest(
            system=COMPILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=8192,
            temperature=0.2,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        response = await self.router.complete(request, session=session)
        self._last_provider_used = response.provider_used

        try:
            data = self.router.parse_json_response(response)
            # Extract typed backlink suggestions before normalizing to
            # plain strings. The typed map is used by save_article to
            # pass relation_type through to resolved backlinks.
            raw_suggestions = data.get("backlink_suggestions", [])
            typed = _extract_typed_suggestions(raw_suggestions)
            self._last_typed_suggestions = {s.target.lower(): s.relation_type.value for s in typed}
            # Normalize to plain strings for backward-compatible CompilationResult.
            data["backlink_suggestions"] = _normalize_backlink_suggestions(raw_suggestions)
            result = CompilationResult(**data)
            # System-controlled field overwriting: these fields are always
            # set by Python regardless of what the LLM emitted (issue #143).
            result.compiled = utcnow_naive()
            result.provider = self._last_provider_used
            result.page_type = PageType.SOURCE
            return result
        except Exception as e:
            log.error(
                "Failed to parse compilation response",
                error=str(e),
                response_preview=response.content[:500] if response else "no response",
            )
            return None

    def _build_user_prompt(self, doc: NormalizedDocument) -> str:
        """Build the user prompt for the LLM compiler."""
        meta = f"Title: {doc.title}"
        if doc.author:
            meta += f"\nAuthor: {doc.author}"
        if doc.published_date:
            meta += f"\nPublished: {doc.published_date}"

        return f"""{meta}

---

{doc.clean_text[:60000]}

---

Compile this into a wiki article following the JSON schema exactly."""

    async def _compile_chunked(
        self,
        doc: NormalizedDocument,
        session: AsyncSession,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> CompilationResult | None:
        """Compile large documents in chunks and merge results."""
        total_chunks = min(len(doc.chunks), 10)
        log.info("Chunked compilation", chunks=total_chunks)
        chunk_results = []

        for i, chunk in enumerate(doc.chunks[:10]):
            if progress_callback:
                await progress_callback(f"Compiling chunk {i + 1}/{total_chunks}...")
            chunk_doc = NormalizedDocument(
                raw_source_id=doc.raw_source_id,
                clean_text=chunk.content,
                title=f"{doc.title} (Part {i + 1})",
                author=doc.author,
                published_date=doc.published_date,
                estimated_tokens=chunk.token_count,
            )
            result = await self.compile(chunk_doc, session)
            if result:
                chunk_results.append(result)

        if not chunk_results:
            return None

        return self._merge_chunk_results(doc.title, chunk_results)

    def _merge_chunk_results(self, title: str, results: list[CompilationResult]) -> CompilationResult:
        """Merge multiple chunk results into a single CompilationResult."""
        all_claims = []
        all_concepts: set[str] = set()
        all_backlinks: set[str] = set()
        all_questions = []
        body_parts = []

        for r in results:
            all_claims.extend(r.key_claims)
            all_concepts.update(r.concepts)
            all_backlinks.update(r.backlink_suggestions)
            all_questions.extend(r.open_questions)
            body_parts.append(r.article_body)

        return CompilationResult(
            title=title,
            summary=results[0].summary,
            key_claims=all_claims[:20],
            concepts=list(all_concepts)[:10],
            backlink_suggestions=list(all_backlinks)[:10],
            open_questions=list(set(all_questions))[:5],
            article_body="\n\n---\n\n".join(body_parts),
        )

    async def save_article(
        self,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> Article:
        """Persist a compiled article, replacing any prior same-provider build."""
        provider = self._last_provider_used
        existing = await self._find_article_for_source_and_provider(session, source.id, provider)
        if existing is not None:
            return await self._replace_article_in_place(existing, result, source, session)
        return await self._create_article(result, source, session, provider)

    async def _find_article_for_source_and_provider(
        self,
        session: AsyncSession,
        source_id: str,
        provider: Provider | None,
    ) -> Article | None:
        """Find an article previously compiled from this source by this provider."""
        if provider is None:
            return None
        settings = get_settings()
        dialect = "sqlite" if is_sqlite(settings.database_url) else "postgresql"
        if dialect == "postgresql":
            clause = json_array_contains(dialect, "source_ids", source_id)
            result = await session.execute(select(Article).where(clause))  # type: ignore[arg-type]
        else:
            needle = f'"{source_id}"'
            result = await session.execute(
                select(Article).where(Article.source_ids.contains(needle))  # type: ignore[union-attr]
            )
        for article in result.scalars().all():
            if article.provider == provider:
                return article
        return None

    async def _create_article(
        self,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
        provider: Provider | None,
    ) -> Article:
        """Create a brand-new article (no existing same-provider article)."""
        slug = self._generate_unique_slug(result.title)

        resolved, unresolved = await resolve_backlink_candidates(
            result.backlink_suggestions,
            session,
            relation_types=self._last_typed_suggestions,
        )

        relative_path = self._write_article_file(result, source, slug, resolved, unresolved)

        article = Article(
            slug=slug,
            title=result.title,
            file_path=relative_path,
            confidence=self._overall_confidence(result),
            summary=result.summary,
            source_ids=json.dumps([source.id]),
            concept_ids=json.dumps(result.concepts),
            provider=provider,
            page_type=PageType.SOURCE,
        )
        session.add(article)

        source.status = IngestStatus.COMPILED
        source.compiled_at = utcnow_naive()
        session.add(source)

        await session.commit()
        await session.refresh(article)

        await self._persist_resolved_backlinks(article.id, resolved, session)

        try:
            await upsert_concepts(result.concepts, session)
            await update_article_counts(session)
            await maybe_trigger_taxonomy_rebuild(session)
            # Concept page generation must use its own session to avoid
            # identity-map conflicts when both the source compiler and
            # concept compiler create Backlinks for overlapping article
            # pairs (issue #152 — greenlet_spawn error).
            async with get_session_factory()() as concept_session:
                await maybe_trigger_concept_pages(concept_session)
        except Exception:
            log.warning("taxonomy upsert failed", article_id=article.id)

        try:
            append_log_entry(
                "compile",
                article.title,
                extra={"source_id": source.id, "article_slug": article.slug},
            )
        except Exception:
            log.warning("activity log write failed", op="compile", article_id=article.id)

        try:
            await regenerate_index_md(session)
        except Exception:
            log.warning("index.md regeneration failed", article_id=article.id)

        log.info(
            "Article saved",
            slug=slug,
            title=result.title,
            provider=provider,
            resolved_backlinks=len(resolved),
            unresolved_backlinks=len(unresolved),
        )
        return article

    async def _replace_article_in_place(
        self,
        existing: Article,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> Article:
        """Replace an existing same-source same-provider article in place."""
        old_concept_ids = existing.concept_ids

        old_path = resolve_wiki_path(existing.file_path)
        old_path.unlink(missing_ok=True)

        resolved, unresolved = await resolve_backlink_candidates(
            result.backlink_suggestions,
            session,
            exclude_article_id=existing.id,
            relation_types=self._last_typed_suggestions,
        )

        relative_path = self._write_article_file(result, source, existing.slug, resolved, unresolved)

        existing.title = result.title
        existing.summary = result.summary
        existing.confidence = self._overall_confidence(result)
        existing.file_path = relative_path
        existing.concept_ids = json.dumps(result.concepts)
        existing.page_type = PageType.SOURCE
        existing.updated_at = utcnow_naive()
        session.add(existing)

        source.status = IngestStatus.COMPILED
        source.compiled_at = utcnow_naive()
        session.add(source)

        old_bl = await session.execute(select(Backlink).where(Backlink.source_article_id == existing.id))
        for row in old_bl.scalars().all():
            await session.delete(row)

        await session.commit()
        await session.refresh(existing)

        await self._persist_resolved_backlinks(existing.id, resolved, session)

        try:
            await upsert_concepts(result.concepts, session)
            await update_article_counts(session)
            await maybe_trigger_taxonomy_rebuild(session)
            # Concept page generation must use its own session to avoid
            # identity-map conflicts (same pattern as _create_article,
            # issue #152).  Added here so recompiling an existing source
            # also updates concept pages (issue #162).
            async with get_session_factory()() as concept_session:
                await maybe_trigger_concept_pages(concept_session)
        except Exception:
            log.warning(
                "taxonomy upsert failed",
                article_id=existing.id,
                old_concept_ids=old_concept_ids,
            )

        try:
            append_log_entry(
                "compile",
                existing.title,
                extra={"source_id": source.id, "article_slug": existing.slug},
            )
        except Exception:
            log.warning("activity log write failed", op="compile", article_id=existing.id)

        try:
            await regenerate_index_md(session)
        except Exception:
            log.warning("index.md regeneration failed", article_id=existing.id)

        log.info(
            "Article replaced in place",
            slug=existing.slug,
            title=result.title,
            provider=existing.provider,
            resolved_backlinks=len(resolved),
            unresolved_backlinks=len(unresolved),
        )
        return existing

    async def _persist_resolved_backlinks(
        self,
        source_article_id: str,
        resolved: list[ResolvedBacklink],
        session: AsyncSession,
    ) -> None:
        """Insert one Backlink row per resolved candidate with relation_type."""
        for rb in resolved:
            try:
                rel = RelationType(rb.relation_type)
            except ValueError:
                rel = RelationType.REFERENCES
            bl = Backlink(
                source_article_id=source_article_id,
                target_article_id=rb.target_id,
                context=rb.candidate_text,
                relation_type=rel,
            )
            session.add(bl)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                log.debug(
                    "Skipped duplicate backlink",
                    source=source_article_id,
                    target=rb.target_id,
                )

    def _generate_unique_slug(self, title: str) -> str:
        """Generate a URL-safe slug from a title."""
        base = slugify(title, max_length=80)
        return base

    def _write_article_file(
        self,
        result: CompilationResult,
        source: Source,
        slug: str,
        resolved: list[ResolvedBacklink],
        unresolved: list[str],
    ) -> str:
        """Write .md file to wiki directory with page_type:source frontmatter.

        Returns the wiki-relative path (e.g. ``concept-slug/article.md``)
        for storage in Article.file_path.
        """
        wiki_dir = Path(self.settings.data_dir) / "wiki"

        concept = result.concepts[0] if result.concepts else "general"
        concept_slug = slugify(concept)
        concept_dir = wiki_dir / concept_slug
        concept_dir.mkdir(parents=True, exist_ok=True)

        file_path = concept_dir / f"{slug}.md"

        related_lines: list[str] = []
        for rb in resolved:
            related_lines.append(f"- [{rb.candidate_text}](/wiki/{rb.target_id})")
        for text in unresolved:
            related_lines.append(f"- [[{text}]]")
        backlinks = "\n".join(related_lines)

        claims = "\n".join(
            [f"- **{c.claim}** *({c.confidence})*" + (f' -- "{c.quote}"' if c.quote else "") for c in result.key_claims]
        )

        questions = "\n".join([f"- {q}" for q in result.open_questions])

        concepts_str = ", ".join(result.concepts)

        provider_str = result.provider or self._last_provider_used or ""

        content = f"""---
title: "{result.title}"
slug: {slug}
page_type: source
source_id: {source.id}
source_url: {source.source_url or ""}
source_type: {source.source_type}
compiled: {utcnow_naive().isoformat()}
concepts: [{concepts_str}]
confidence: {self._overall_confidence(result)}
provider: {provider_str}
---

## Summary

{result.summary}

## Key Claims

{claims}

## Analysis

{result.article_body}

## Open Questions

{questions}

## Related

{backlinks}

## Sources

- {source.title or source.source_url or "Uploaded document"} (ingested {source.ingested_at.strftime("%Y-%m-%d")})
"""

        file_path.write_text(content, encoding="utf-8")

        # Post-write frontmatter validation (best-effort, log warnings)
        validate_frontmatter(content)

        # Return relative path for DB storage instead of absolute Path
        return str(file_path.relative_to(wiki_dir))

    def _overall_confidence(self, result: CompilationResult) -> ConfidenceLevel:
        """Determine overall confidence from claims."""
        if not result.key_claims:
            return ConfidenceLevel.INFERRED

        sourced = sum(1 for c in result.key_claims if c.confidence == "sourced")
        ratio = sourced / len(result.key_claims)

        if ratio >= 0.8:
            return ConfidenceLevel.SOURCED
        elif ratio >= 0.4:
            return ConfidenceLevel.MIXED
        else:
            return ConfidenceLevel.INFERRED
