"""WikiMind Compiler.

Transforms normalized source documents into structured wiki articles.
This is the core value-creation step.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.engine.confidence import compute_confidence
from wikimind.engine.frontmatter_validator import validate_frontmatter
from wikimind.engine.llm_router import get_llm_router
from wikimind.engine.wikilink_resolver import (
    ResolvedBacklink,
    resolve_backlink_candidates,
)
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    CompilationResult,
    CompilationSchema,
    CompiledClaim,
    CompletionRequest,
    Concept,
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    PageType,
    Provider,
    ReinforcementEvent,
    RelationType,
    Source,
    TaskType,
    TypedBacklinkSuggestion,
)
from wikimind.services.activity_log import append_log_entry
from wikimind.services.search import index_article as fts_index_article
from wikimind.services.taxonomy import (
    maybe_trigger_concept_pages,
    maybe_trigger_taxonomy_rebuild,
    update_article_counts,
    upsert_concepts,
)
from wikimind.services.wiki_index import regenerate_index_md
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

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


TAKEAWAY_SYSTEM_PROMPT = """You are a knowledge analyst. Your job is to extract the most important takeaways from raw source material so a user can decide what the resulting wiki article should focus on.

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{
  "takeaways": [
    "A concise one-sentence takeaway (10 max)"
  ]
}

Rules:
- Extract 3-10 key takeaways from the source
- Each takeaway should be a single sentence
- Prioritize surprising, counter-intuitive, or high-impact findings
- Include the most important facts, claims, and insights
- Order from most to least important
"""

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

Rich content preservation:
- Math: if the source contains mathematical expressions, reproduce them in LaTeX using $...$ for inline math and $$...$$ for display math blocks. Copy formulas verbatim from the source -- do not simplify or rewrite them.
- Tables: if the source contains tabular data, reproduce it as GitHub-flavored markdown tables (pipe-delimited). Preserve column headers and data exactly.
- Code: if the source contains code snippets, reproduce them in fenced code blocks (```language). Preserve the code exactly as it appears in the source.
- Images: if the source references images, preserve the markdown image syntax ![alt](url) with the original URL or path. Do not remove or rewrite image references.
- These rich content blocks are OPAQUE -- do not paraphrase, summarize, or rewrite their contents. They must survive round-trip compilation unchanged.
"""


def _safe_json_list(value: str | None) -> list[str] | None:
    """Parse a JSON string as a list, returning None on failure."""
    if not value:
        return None
    try:
        result = json.loads(value)
        return result if isinstance(result, list) and result else None
    except (json.JSONDecodeError, TypeError):
        return None


def _build_schema_directives(schema: CompilationSchema) -> str:
    """Build a prompt supplement from a user-defined compilation schema.

    Returns an empty string when the schema has no substantive directives,
    so it is always safe to append.
    """
    lines: list[str] = []

    # Simple scalar directives
    _scalar_directives = [
        (schema.article_max_length, lambda v: f"- Article body must not exceed {v} words."),
        (schema.style, lambda v: f"- Writing style: {v}"),
        (schema.focus, lambda v: f"- Focus: {v}"),
        (schema.concept_max_depth, lambda v: f"- Concept taxonomy max depth: {v} levels."),
        (schema.concept_naming, lambda v: f"- Concept naming convention: {v}"),
        (schema.custom_directives, lambda v: f"- Additional directives: {v}"),
    ]
    for value, fmt in _scalar_directives:
        if value:
            lines.append(fmt(value))

    # JSON list directives
    _list_directives = [
        (schema.required_sections, "- Article MUST include these sections: {}."),
        (schema.extraction_always_note, "- Always note these when present in the source: {}."),
        (schema.extraction_ignore, "- Ignore these during extraction: {}."),
    ]
    for raw_value, template in _list_directives:
        items = _safe_json_list(raw_value)
        if items:
            lines.append(template.format(", ".join(items)))

    if not lines:
        return ""
    return "\n\nUser-defined compilation rules (FOLLOW THESE):\n" + "\n".join(lines)


class Compiler:
    """Compile normalized documents into wiki articles."""

    def __init__(self, user_id: str):
        self.router = get_llm_router()
        self.settings = get_settings()
        self.user_id = user_id
        # Provider that handled the most recent successful `complete()` call.
        self._last_provider_used: Provider | None = None
        # Typed backlink suggestions from the most recent `compile()` call.
        self._last_typed_suggestions: dict[str, str] = {}
        # Compilation monitoring — set during compile(), read during save_article().
        self._last_compilation_duration_ms: int | None = None
        self._last_compilation_tokens: int | None = None

    async def extract_takeaways(
        self,
        doc: NormalizedDocument,
    ) -> list[str]:
        """Extract key takeaways from a document without full compilation.

        Used by the interactive compilation flow to present the user with
        a preview of what the LLM found interesting before committing to
        a full article.

        Args:
            doc: Normalized document to analyze.

        Returns:
            A list of takeaway strings (3-10 items).
        """
        user_prompt = self._build_user_prompt(doc)
        settings = get_settings()
        request = CompletionRequest(
            system=TAKEAWAY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=settings.compiler.max_tokens // 2,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        response = await self.router.complete(request, user_id=self.user_id)
        try:
            data = self.router.parse_json_response(response)
            takeaways = data.get("takeaways", [])
            return [str(t) for t in takeaways if t][:10]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            log.warning("Failed to parse takeaways", error=str(e))
            return []

    async def compile_with_guidance(
        self,
        doc: NormalizedDocument,
        session: AsyncSession,
        guidance: str,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> CompilationResult | None:
        """Compile a document with user-provided focus guidance.

        Identical to :meth:`compile` but appends the user's guidance to
        the prompt so the LLM weights the article toward what matters
        to the user.

        Args:
            doc: Normalized document to compile.
            session: Async database session.
            guidance: User-provided focus direction.
            progress_callback: Optional async callback for progress messages.

        Returns:
            CompilationResult or None on failure.
        """
        log.info(
            "Compiling with guidance",
            title=doc.title,
            guidance_len=len(guidance),
        )

        if doc.estimated_tokens > 80_000:
            return await self._compile_chunked(doc, session, progress_callback)

        user_prompt = self._build_user_prompt(doc)
        user_prompt += "\n\nUSER GUIDANCE — weight the article toward these priorities:\n" + guidance

        existing_concepts = [c.name for c in (await session.execute(select(Concept))).scalars().all()]
        if existing_concepts:
            user_prompt += "\n\nExisting concepts in this wiki (REUSE these before inventing new ones):\n" + ", ".join(
                sorted(existing_concepts)
            )

        settings = get_settings()
        request = CompletionRequest(
            system=COMPILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=settings.compiler.max_tokens,
            temperature=0.2,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        compile_start = time.monotonic()
        response = await self.router.complete(request, user_id=self.user_id)
        self._last_compilation_duration_ms = round((time.monotonic() - compile_start) * 1000)
        self._last_compilation_tokens = response.input_tokens + response.output_tokens
        self._last_provider_used = response.provider_used

        try:
            data = self.router.parse_json_response(response)
            raw_suggestions = data.get("backlink_suggestions", [])
            typed = _extract_typed_suggestions(raw_suggestions)
            self._last_typed_suggestions = {s.target.lower(): s.relation_type.value for s in typed}
            data["backlink_suggestions"] = _normalize_backlink_suggestions(raw_suggestions)
            result = CompilationResult(**data)
            result.compiled = utcnow_naive()
            result.provider = self._last_provider_used
            result.page_type = PageType.SOURCE
            return result
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            log.error(
                "Failed to parse guided compilation response",
                error=str(e),
                response_preview=(response.content[:500] if response else "no response"),
            )
            return None

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

        # Load user-defined compilation schema (issue #420).
        system_prompt = COMPILER_SYSTEM_PROMPT
        active_schema_result = await session.execute(
            select(CompilationSchema).where(
                CompilationSchema.user_id == self.user_id,
                CompilationSchema.is_active == True,  # noqa: E712
            )
        )
        active_schema = active_schema_result.scalar_one_or_none()
        if active_schema is not None:
            schema_directives = _build_schema_directives(active_schema)
            if schema_directives:
                system_prompt += schema_directives

        settings = get_settings()
        request = CompletionRequest(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=settings.compiler.max_tokens,
            temperature=0.2,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        compile_start = time.monotonic()
        response = await self.router.complete(request, user_id=self.user_id)
        self._last_compilation_duration_ms = round((time.monotonic() - compile_start) * 1000)
        self._last_compilation_tokens = response.input_tokens + response.output_tokens
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
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            log.error(
                "Failed to parse compilation response",
                error=str(e),
                response_preview=response.content[:500] if response else "no response",
            )
            return None

    def _build_user_prompt(self, doc: NormalizedDocument) -> str:
        """Build the user prompt for the LLM compiler."""
        max_chars = get_settings().compiler.source_text_max_chars
        meta = f"Title: {doc.title}"
        if doc.author:
            meta += f"\nAuthor: {doc.author}"
        if doc.published_date:
            meta += f"\nPublished: {doc.published_date}"

        return f"""{meta}

---

{doc.clean_text[:max_chars]}

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
        return await self._upsert_article(result, source, session, provider, existing=existing)

    async def save_article_in_place(
        self,
        existing: Article,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> Article:
        """Replace an existing article in place, bypassing provider lookup.

        Use this when the caller already holds the article row that should be
        updated (e.g. the force-recompile path).
        """
        return await self._upsert_article(result, source, session, existing.provider, existing=existing)

    async def _find_article_for_source_and_provider(
        self,
        session: AsyncSession,
        source_id: str,
        provider: Provider | None,
    ) -> Article | None:
        """Find an article previously compiled from this source by this provider."""
        if provider is None:
            return None
        result = await session.execute(
            select(Article)
            .join(ArticleSource, ArticleSource.article_id == Article.id)  # type: ignore[arg-type]
            .where(ArticleSource.source_id == source_id)
        )
        for article in result.scalars().all():
            if article.provider == provider:
                return article
        return None

    def _apply_article_fields(
        self,
        article: Article,
        result: CompilationResult,
        relative_path: str,
        source: Source,
        provider: Provider | None,
    ) -> None:
        """Apply compilation result fields to an existing article row."""
        article.title = result.title
        article.summary = result.summary
        article.confidence = self._overall_confidence(result)
        article.file_path = relative_path
        article.concept_ids = json.dumps(result.concepts)
        article.page_type = PageType.SOURCE
        article.updated_at = utcnow_naive()
        article.user_id = source.user_id
        article.compiled_at = utcnow_naive()
        article.compilation_duration_ms = self._last_compilation_duration_ms
        article.compilation_tokens = self._last_compilation_tokens

    async def _upsert_article(
        self,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
        provider: Provider | None,
        existing: Article | None,
    ) -> Article:
        """Unified create-or-replace logic for a compiled article."""
        wiki_storage = get_wiki_storage(self.user_id)
        old_relative: str | None = None
        if existing is not None:
            slug = existing.slug
            # Strip any legacy absolute prefix to get a relative path for comparison.
            root_prefix = str(wiki_storage.resolve_path("")) + "/"
            old_relative = existing.file_path.removeprefix(root_prefix)
        else:
            slug = await self._generate_unique_slug(result.title, session)

        resolved, unresolved = await resolve_backlink_candidates(
            result.backlink_suggestions,
            session,
            exclude_article_id=existing.id if existing is not None else None,
            relation_types=self._last_typed_suggestions,
            user_id=self.user_id,
        )

        relative_path = await self._write_article_file(result, source, slug, resolved, unresolved)

        if existing is not None:
            # Delete old file only after new file is written successfully to
            # avoid data loss if the write fails (issue #183).
            if old_relative is not None and old_relative != relative_path:
                await wiki_storage.delete(old_relative)

            self._apply_article_fields(existing, result, relative_path, source, provider)
            session.add(existing)
            article = existing

            # Remove stale backlinks and join-table rows before re-populating.
            await self._clear_article_relations(existing.id, session)
        else:
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
                user_id=self.user_id,
                compiled_at=utcnow_naive(),
                compilation_duration_ms=self._last_compilation_duration_ms,
                compilation_tokens=self._last_compilation_tokens,
            )
            session.add(article)

        source.status = IngestStatus.COMPILED
        source.compiled_at = utcnow_naive()
        session.add(source)

        await session.commit()
        await session.refresh(article)

        # Populate join tables
        session.add(ArticleSource(article_id=article.id, source_id=source.id))
        for concept_name in result.concepts:
            session.add(ArticleConcept(article_id=article.id, concept_name=concept_name))
        await session.commit()

        # Update full-text search index
        wiki_storage = get_wiki_storage(self.user_id)
        try:
            article_content = await wiki_storage.read(relative_path)
        except OSError:
            article_content = ""
        await fts_index_article(session, article.id, article.title, article_content)
        await session.commit()

        await self._persist_resolved_backlinks(
            article.id,
            resolved,
            session,
            user_id=self.user_id,
        )

        await self._persist_claims(article.id, result, source, session)

        await self._refresh_confidence_score(article, session)

        await self._post_save_side_effects(article, result, source, session)

        log.info(
            "Article saved" if existing is None else "Article replaced in place",
            slug=slug,
            title=result.title,
            provider=provider,
            resolved_backlinks=len(resolved),
            unresolved_backlinks=len(unresolved),
        )
        return article

    async def _refresh_confidence_score(
        self,
        article: Article,
        session: AsyncSession,
    ) -> None:
        """Recompute and persist ``confidence_score`` and ``last_reinforced_at``.

        Aggregates the article's current source set (via the
        :class:`ArticleSource` join table) and counts incoming
        ``CONTRADICTS`` backlinks, then delegates to
        :func:`wikimind.engine.confidence.compute_confidence`.

        Also sets ``source_newest_at`` and creates a ``ReinforcementEvent``
        for staleness tracking (issue #425).
        """
        now = utcnow_naive()
        # Gather sources currently linked to the article.
        src_result = await session.execute(
            select(Source)
            .join(ArticleSource, ArticleSource.source_id == Source.id)  # type: ignore[arg-type]
            .where(ArticleSource.article_id == article.id)
        )
        sources = list(src_result.scalars().all())
        source_count = len(sources)
        if sources:
            newest = max(s.ingested_at for s in sources)
            newest_age_days = max(0, (now - newest).days)
            article.source_newest_at = newest
        else:
            newest_age_days = 0

        # Count incoming CONTRADICTS backlinks pointing at this article.
        contra_result = await session.execute(
            select(Backlink).where(
                Backlink.target_article_id == article.id,
                Backlink.relation_type == RelationType.CONTRADICTS,
            )
        )
        contradiction_count = len(list(contra_result.scalars().all()))

        article.confidence_score = compute_confidence(
            source_count=source_count,
            newest_source_age_days=newest_age_days,
            contradiction_count=contradiction_count,
        )
        article.last_reinforced_at = now
        session.add(article)

        # Record the reinforcement event (issue #425)
        event = ReinforcementEvent(
            article_id=article.id,
            event_type="recompile",
            occurred_at=now,
            user_id=self.user_id,
        )
        session.add(event)

        await session.commit()

    async def _clear_article_relations(
        self,
        article_id: str,
        session: AsyncSession,
    ) -> None:
        """Delete backlinks, claims, and join-table rows for an article before re-populating."""
        old_bl = await session.execute(select(Backlink).where(Backlink.source_article_id == article_id))
        for row in old_bl.scalars().all():
            await session.delete(row)
        old_claims = await session.execute(select(CompiledClaim).where(CompiledClaim.article_id == article_id))
        for claim in old_claims.scalars().all():
            await session.delete(claim)
        old_ac = await session.execute(select(ArticleConcept).where(ArticleConcept.article_id == article_id))
        for ac in old_ac.scalars().all():
            await session.delete(ac)
        old_as = await session.execute(select(ArticleSource).where(ArticleSource.article_id == article_id))
        for a_s in old_as.scalars().all():
            await session.delete(a_s)

    async def _post_save_side_effects(
        self,
        article: Article,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> None:
        """Run taxonomy updates, activity logging, and index regeneration."""
        try:
            await upsert_concepts(result.concepts, session, user_id=self.user_id)
            await update_article_counts(session, user_id=self.user_id)
            await maybe_trigger_taxonomy_rebuild(session, user_id=self.user_id)
            # Concept page generation must use its own session to avoid
            # identity-map conflicts when both the source compiler and
            # concept compiler create Backlinks for overlapping article
            # pairs (issue #152 — greenlet_spawn error).
            async with get_session_factory()() as concept_session:
                await maybe_trigger_concept_pages(concept_session, user_id=self.user_id)
        except (SQLAlchemyError, RuntimeError, ValueError):
            log.warning("taxonomy upsert failed", article_id=article.id)

        try:
            append_log_entry(
                "compile",
                article.title,
                extra={"source_id": source.id, "article_slug": article.slug},
                user_id=self.user_id,
            )
        except OSError:
            log.warning("activity log write failed", op="compile", article_id=article.id)

        try:
            await regenerate_index_md(session, user_id=self.user_id)
        except (OSError, SQLAlchemyError):
            log.warning("index.md regeneration failed", article_id=article.id)

    async def _persist_resolved_backlinks(
        self,
        source_article_id: str,
        resolved: list[ResolvedBacklink],
        session: AsyncSession,
        user_id: str,
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
                user_id=user_id,
            )
            session.add(bl)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                log.debug(
                    "Skipped duplicate backlink",
                    source=source_article_id,
                    target=rb.target_id,
                )
        await session.commit()

    async def _persist_claims(
        self,
        article_id: str,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> None:
        """Persist CompiledClaim rows for each key_claim in the compilation result."""
        for dto in result.key_claims:
            claim = CompiledClaim(
                article_id=article_id,
                user_id=self.user_id,
                text=dto.claim,
                subjects=json.dumps(dto.subjects),
                predicate=dto.predicate,
                confidence_level=dto.confidence.value if hasattr(dto.confidence, "value") else str(dto.confidence),
                quote=dto.quote,
                source_ids=json.dumps(dto.source_ids or [source.id]),
            )
            session.add(claim)
        await session.commit()

    async def _generate_unique_slug(self, title: str, session: AsyncSession) -> str:
        """Generate a URL-safe slug from a title, avoiding collisions.

        Tries the base slug first; if it already exists, appends ``-2``,
        ``-3``, etc. until a unique value is found.
        """
        base = slugify(title, max_length=80)
        candidate = base
        suffix = 2
        while True:
            existing = (await session.execute(select(Article).where(Article.slug == candidate))).scalars().first()
            if existing is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1

    async def _write_article_file(
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
        concept = result.concepts[0] if result.concepts else "general"
        concept_slug = slugify(concept)
        relative_path = f"{concept_slug}/{slug}.md"

        related_lines: list[str] = [f"- [{rb.candidate_text}](/wiki/{rb.target_id})" for rb in resolved]
        related_lines.extend(f"- [[{text}]]" for text in unresolved)
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

        storage = get_wiki_storage(source.user_id)
        await storage.write(relative_path, content)

        # Post-write frontmatter validation (best-effort, log warnings)
        validate_frontmatter(content)

        return relative_path

    def _overall_confidence(self, result: CompilationResult) -> ConfidenceLevel:
        """Determine overall confidence from claims."""
        if not result.key_claims:
            return ConfidenceLevel.INFERRED

        sourced = sum(1 for c in result.key_claims if c.confidence == "sourced")
        ratio = sourced / len(result.key_claims)

        if ratio >= 0.8:
            return ConfidenceLevel.SOURCED
        if ratio >= 0.4:
            return ConfidenceLevel.MIXED
        return ConfidenceLevel.INFERRED
