"""WikiMind Compiler.

Transforms normalized source documents into structured wiki articles.
This is the core value-creation step.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import _dialect_insert, get_session_factory
from wikimind.engine.base_compiler import BaseCompiler
from wikimind.engine.confidence import (
    aggregate_claim_confidence,
    compute_claim_confidence,
    compute_confidence,
)
from wikimind.engine.frontmatter_validator import validate_frontmatter
from wikimind.engine.prompts import COMPILER_SYSTEM_PROMPT, TAKEAWAY_SYSTEM_PROMPT
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

    from sqlmodel.ext.asyncio.session import AsyncSession

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


# Re-export prompt constants for backward compatibility with tests that
# import them from this module.
__all__ = ["COMPILER_SYSTEM_PROMPT", "TAKEAWAY_SYSTEM_PROMPT", "Compiler"]


def _safe_json_list(value: str | None) -> list[str] | None:
    """Parse a JSON string as a list, returning None on failure."""
    if not value:
        return None
    try:
        result = json.loads(value)
        return result if isinstance(result, list) and result else None
    except (json.JSONDecodeError, TypeError):
        return None


_GUIDANCE_SENTINEL_RE = re.compile(r"-{3,}")
_GUIDANCE_TAG_RE = re.compile(r"</?guidance>", re.IGNORECASE)


def _sanitize_guidance(raw: str, max_length: int | None = None) -> str:
    """Sanitize user-supplied guidance to prevent prompt injection.

    - Strips ``<guidance>`` / ``</guidance>`` XML tags that the prompt
      uses as delimiters -- a user could otherwise close the tag early
      and inject arbitrary instructions.
    - Strips sentinel sequences (``---``) the prompts rely on as delimiters.
    - Caps length at ``CompilerConfig.guidance_max_length`` characters.

    Args:
        raw: Raw user-supplied guidance string.
        max_length: Override for the max character limit. When *None*,
            reads ``settings.compiler.guidance_max_length``.
    """
    if max_length is None:
        max_length = get_settings().compiler.guidance_max_length
    cleaned = _GUIDANCE_TAG_RE.sub("", raw)
    cleaned = _GUIDANCE_SENTINEL_RE.sub("", cleaned)
    return cleaned[:max_length]


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


class Compiler(BaseCompiler):
    """Compile normalized documents into wiki articles."""

    def __init__(self, user_id: str):
        super().__init__(user_id)
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

        from wikimind.services.plan_routing import plan_aware_complete  # noqa: PLC0415

        response = await plan_aware_complete(self.router, request, self.user_id, session=None)
        if response is None:
            return []
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
            # Release the DB connection before the long-running chunked LLM
            # calls to avoid PgBouncer idle-connection timeouts (issue #667).
            await session.commit()
            return await self._compile_chunked(doc, session, progress_callback)

        user_prompt = self._build_user_prompt(doc)
        safe_guidance = _sanitize_guidance(guidance)
        user_prompt += (
            f"\n\nUSER GUIDANCE — weight the article toward these priorities:\n<guidance>{safe_guidance}</guidance>"
        )

        existing_concepts = [c.name for c in (await session.exec(select(Concept))).all()]
        if existing_concepts:
            user_prompt += "\n\nExisting concepts in this wiki (REUSE these before inventing new ones):\n" + ", ".join(
                sorted(existing_concepts)
            )

        # Release the DB connection before the long-running LLM call.
        # Same pattern as compile() -- PgBouncer closes idle connections
        # after ~15s; the LLM call can take 20-30s (issue #667).
        await session.commit()

        settings = get_settings()
        request = CompletionRequest(
            system=COMPILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=settings.compiler.max_tokens,
            temperature=0.2,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        from wikimind.services.plan_routing import plan_aware_complete  # noqa: PLC0415

        compile_start = time.monotonic()
        response = await plan_aware_complete(self.router, request, self.user_id, session)
        self._last_compilation_duration_ms = round((time.monotonic() - compile_start) * 1000)
        if response is None:
            return None
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
        existing_concepts = [c.name for c in (await session.exec(select(Concept))).all()]
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

        # Release the DB connection before the long-running LLM call.
        # Fly.io PgBouncer closes idle connections after ~15s; the LLM
        # call can take 20-30s.  commit() ends the current transaction
        # and returns the connection to the pool.  The next session
        # operation will check out a fresh connection (pool_pre_ping
        # verifies it is alive).  expire_on_commit=False ensures all
        # in-memory objects remain usable without lazy-loads.
        await session.commit()

        from wikimind.services.plan_routing import plan_aware_complete  # noqa: PLC0415

        compile_start = time.monotonic()
        response = await plan_aware_complete(self.router, request, self.user_id, session)
        self._last_compilation_duration_ms = round((time.monotonic() - compile_start) * 1000)
        if response is None:
            return None
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
        if doc.raw_source_id:
            meta += f"\nSource ID: {doc.raw_source_id}"

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

        The article-level confidence is the weighted mean of its persisted
        claims' confidence scores (issue #465). When no claims exist, it
        falls back to the provenance-based ``compute_confidence`` formula
        using source count, recency, and contradiction count.

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

        # Aggregate from claim-level scores when claims exist (issue #465).
        claims_result = await session.execute(
            select(CompiledClaim.confidence_score).where(
                CompiledClaim.article_id == article.id,
            )
        )
        claim_scores = [row[0] for row in claims_result.all()]

        if claim_scores:
            article.confidence_score = aggregate_claim_confidence(claim_scores)
        else:
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
        old_bl = await session.exec(select(Backlink).where(Backlink.source_article_id == article_id))
        for row in old_bl.all():
            await session.delete(row)
        old_claims = await session.exec(select(CompiledClaim).where(CompiledClaim.article_id == article_id))
        for claim in old_claims.all():
            await session.delete(claim)
        old_ac = await session.exec(select(ArticleConcept).where(ArticleConcept.article_id == article_id))
        for ac in old_ac.all():
            await session.delete(ac)
        old_as = await session.exec(select(ArticleSource).where(ArticleSource.article_id == article_id))
        for a_s in old_as.all():
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
        conn = await session.connection()
        insert_fn = _dialect_insert(conn)
        for rb in resolved:
            try:
                rel = RelationType(rb.relation_type)
            except ValueError:
                rel = RelationType.REFERENCES
            stmt = (
                insert_fn(Backlink)
                .values(
                    source_article_id=source_article_id,
                    target_article_id=rb.target_id,
                    context=rb.candidate_text,
                    relation_type=rel,
                    user_id=user_id,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
        await session.commit()

    async def _persist_claims(
        self,
        article_id: str,
        result: CompilationResult,
        source: Source,
        session: AsyncSession,
    ) -> None:
        """Persist CompiledClaim rows for each key_claim in the compilation result.

        Each claim receives a numeric ``confidence_score`` computed from its
        categorical confidence label and the number of backing sources
        (issue #465).
        """
        for dto in result.key_claims:
            claim_source_ids = dto.source_ids or [source.id]
            confidence_level = dto.confidence.value if hasattr(dto.confidence, "value") else str(dto.confidence)
            claim = CompiledClaim(
                article_id=article_id,
                user_id=self.user_id,
                text=dto.claim,
                subjects=json.dumps(dto.subjects),
                predicate=dto.predicate,
                confidence_level=confidence_level,
                confidence_score=compute_claim_confidence(
                    confidence_level=confidence_level,
                    source_count=len(claim_source_ids),
                ),
                quote=dto.quote,
                source_ids=json.dumps(claim_source_ids),
            )
            session.add(claim)
        await session.commit()

    # _generate_unique_slug is inherited from BaseCompiler

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
