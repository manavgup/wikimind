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
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
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
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    Provider,
    Source,
    TaskType,
)
from wikimind.services.activity_log import append_log_entry
from wikimind.services.wiki_index import regenerate_index_md

log = structlog.get_logger()


COMPILER_SYSTEM_PROMPT = """You are a knowledge compiler. Your job is to transform raw source material into a structured wiki article for a personal knowledge base.

The user is building a living wiki — every article should connect to others, surface open questions, and make their knowledge compound over time.

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{
  "title": "Concise, specific article title",
  "summary": "Exactly 2 sentences. What this is and why it matters.",
  "key_claims": [
    {
      "claim": "Specific, falsifiable claim from the source",
      "confidence": "sourced|inferred|opinion",
      "quote": "Optional direct quote under 15 words if the exact wording matters"
    }
  ],
  "concepts": ["concept-name-1", "concept-name-2"],
  "backlink_suggestions": ["Title of related concept that likely exists in wiki"],
  "open_questions": ["Question this source raises but does not answer"],
  "article_body": "Full markdown article. Use ## headings. Include Key Claims, Analysis, Open Questions sections."
}

Rules:
- Every claim must be attributable to the source
- Mark LLM inferences as confidence=inferred explicitly
- Suggest backlinks only to concepts genuinely related
- Open questions should drive future research
- article_body must be substantive — at least 300 words
- Never fabricate quotes or statistics not in the source
"""


class Compiler:
    """Compile normalized documents into wiki articles."""

    def __init__(self):
        self.router = get_llm_router()
        self.settings = get_settings()
        # Provider that handled the most recent successful `complete()` call.
        # Used by `save_article` to find an existing article from the same
        # source compiled by the same provider, so re-runs replace in place
        # while different providers stack as separate articles (issue #67).
        self._last_provider_used: Provider | None = None

    async def compile(
        self,
        doc: NormalizedDocument,
        session: AsyncSession,
        progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> CompilationResult | None:
        """Compile a normalized document into a wiki article."""
        log.info("Compiling document", title=doc.title, tokens=doc.estimated_tokens)

        # For large documents, compile in chunks and merge
        if doc.estimated_tokens > 80_000:
            return await self._compile_chunked(doc, session, progress_callback)

        request = CompletionRequest(
            system=COMPILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(doc)}],
            max_tokens=8192,
            temperature=0.2,  # Low temp for factual compilation
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        response = await self.router.complete(request, session=session)
        self._last_provider_used = response.provider_used

        try:
            data = self.router.parse_json_response(response)
            return CompilationResult(**data)
        except Exception as e:
            log.error(
                "Failed to parse compilation response",
                error=str(e),
                response_preview=response.content[:500] if response else "no response",
            )
            return None

    def _build_user_prompt(self, doc: NormalizedDocument) -> str:
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
        progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> CompilationResult | None:
        """Compile large documents in chunks and merge results."""
        total_chunks = min(len(doc.chunks), 10)
        log.info("Chunked compilation", chunks=total_chunks)
        chunk_results = []

        for i, chunk in enumerate(doc.chunks[:10]):  # Max 10 chunks
            if progress_callback:
                # Report 0-100% within the compilation phase; the caller
                # (worker → emit_source_progress) maps this to the overall bar.
                pct = int((i / total_chunks) * 100)
                await progress_callback(pct, f"Compiling chunk {i + 1} of {total_chunks}...")
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

        # Merge chunk results into single article
        return self._merge_chunk_results(doc.title, chunk_results)

    def _merge_chunk_results(self, title: str, results: list[CompilationResult]) -> CompilationResult:
        all_claims = []
        all_concepts = set()
        all_backlinks = set()
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
            key_claims=all_claims[:20],  # Cap at 20
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
        """Persist a compiled article, replacing any prior same-provider build.

        Behavior (issue #67):
            - If an article already exists for `(source, provider)`, it is
              replaced **in place** — the slug and id are preserved, the
              `.md` file is rewritten, and only the metadata fields change.
            - If no article exists for that pair, a new row is created with
              `provider` set, leaving any same-source articles from other
              providers untouched.
            - When the provider could not be tracked (e.g. tests that
              bypass `compile()`), we fall back to always-create.

        Args:
            result: The compilation result returned by `compile()`.
            source: The Source row that was compiled.
            session: Async database session.

        Returns:
            The persisted Article (either replaced or freshly created).
        """
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
        """Find an article previously compiled from this source by this provider.

        `Article.source_ids` is a JSON-encoded string like ``["uuid1","uuid2"]``,
        so we use a `LIKE` filter on the quoted UUID and then narrow by
        provider in Python. Adequate for a single-user wiki — there is no
        index on `source_ids` and we don't expect millions of rows.
        """
        if provider is None:
            return None
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

        resolved, unresolved = await resolve_backlink_candidates(result.backlink_suggestions, session)

        file_path = self._write_article_file(result, source, slug, resolved, unresolved)

        article = Article(
            slug=slug,
            title=result.title,
            file_path=str(file_path),
            confidence=self._overall_confidence(result),
            summary=result.summary,
            source_ids=json.dumps([source.id]),
            concept_ids=json.dumps(result.concepts),
            provider=provider,
        )
        session.add(article)

        source.status = IngestStatus.COMPILED
        source.compiled_at = utcnow_naive()
        session.add(source)

        await session.commit()
        await session.refresh(article)

        await self._persist_resolved_backlinks(article.id, resolved, session)

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
        """Replace an existing same-source same-provider article in place.

        Keeps the slug and id stable so backlinks and external bookmarks
        remain valid. The old `.md` file is unlinked and a new one is
        written under the same slug. The new file may live in a different
        concept directory if the compiler picked a different first concept
        on this run — `existing.file_path` is updated to track the new
        location.
        """
        old_path = Path(existing.file_path)
        old_path.unlink(missing_ok=True)

        resolved, unresolved = await resolve_backlink_candidates(
            result.backlink_suggestions, session, exclude_article_id=existing.id
        )

        new_path = self._write_article_file(result, source, existing.slug, resolved, unresolved)

        existing.title = result.title
        existing.summary = result.summary
        existing.confidence = self._overall_confidence(result)
        existing.file_path = str(new_path)
        existing.concept_ids = json.dumps(result.concepts)
        existing.updated_at = utcnow_naive()
        session.add(existing)

        source.status = IngestStatus.COMPILED
        source.compiled_at = utcnow_naive()
        session.add(source)

        # Clear stale Backlink rows from the previous compile (source side only)
        old_bl = await session.execute(select(Backlink).where(Backlink.source_article_id == existing.id))
        for row in old_bl.scalars().all():
            await session.delete(row)

        await session.commit()
        await session.refresh(existing)

        await self._persist_resolved_backlinks(existing.id, resolved, session)

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
        """Insert one :class:`Backlink` row per resolved candidate.

        The composite primary key ``(source_article_id, target_article_id)``
        on :class:`Backlink` rejects duplicates automatically. We catch
        :class:`IntegrityError` per-row so one duplicate does not abort the
        batch. In normal use the resolver upstream already dedupes candidates
        by ``target_id`` (see :mod:`wikimind.engine.wikilink_resolver`), so
        this except branch is cold — it exists as a defense against contract
        drift between the resolver and this writer.

        Committed per-row AFTER the parent article has already been committed
        by the caller. This means the ``Article`` row and its backlinks are
        NOT transactionally coupled: if the process dies mid-loop, the
        article exists in the DB with a partially-populated backlink set.
        The next re-compile (which clears stale rows and re-inserts) will
        heal the state. The markdown file on disk is the other record of
        the resolved links and is written before any DB work.
        """
        for rb in resolved:
            bl = Backlink(
                source_article_id=source_article_id,
                target_article_id=rb.target_id,
                context=rb.candidate_text,
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
        base = slugify(title, max_length=80)
        return base

    def _write_article_file(
        self,
        result: CompilationResult,
        source: Source,
        slug: str,
        resolved: list[ResolvedBacklink],
        unresolved: list[str],
    ) -> Path:
        """Write .md file to wiki directory.

        The "Related" section emits standard markdown links for resolved
        wikilinks (``[Text](/wiki/<article_id>)``) and Obsidian-style
        brackets only for unresolved candidates (``[[Text]]``). The
        frontend's ArticleReader distinguishes the two at render time:
        resolved become React Router links, unresolved become dimmed spans.
        """
        wiki_dir = Path(self.settings.data_dir) / "wiki"

        # Determine subdirectory from first concept
        concept = result.concepts[0] if result.concepts else "general"
        concept_dir = wiki_dir / slugify(concept)
        concept_dir.mkdir(parents=True, exist_ok=True)

        file_path = concept_dir / f"{slug}.md"

        # Build backlinks section — resolved become real markdown links,
        # unresolved remain as [[Title]] brackets for the frontend to style.
        related_lines: list[str] = []
        for rb in resolved:
            related_lines.append(f"- [{rb.candidate_text}](/wiki/{rb.target_id})")
        for text in unresolved:
            related_lines.append(f"- [[{text}]]")
        backlinks = "\n".join(related_lines)

        # Build claims section
        claims = "\n".join(
            [f"- **{c.claim}** *({c.confidence})*" + (f' — "{c.quote}"' if c.quote else "") for c in result.key_claims]
        )

        # Build open questions
        questions = "\n".join([f"- {q}" for q in result.open_questions])

        # Build concepts tags
        concepts_str = ", ".join(result.concepts)

        content = f"""---
title: "{result.title}"
slug: {slug}
source_url: {source.source_url or ""}
source_type: {source.source_type}
compiled: {utcnow_naive().isoformat()}
concepts: [{concepts_str}]
confidence: {self._overall_confidence(result)}
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
        return file_path

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
