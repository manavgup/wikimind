"""WikiMind Compiler.

Transforms normalized source documents into structured wiki articles.
This is the core value-creation step.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import structlog
from slugify import slugify
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    CompilationResult,
    CompletionRequest,
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    Source,
    TaskType,
)

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

    async def compile(
        self,
        doc: NormalizedDocument,
        session: AsyncSession,
    ) -> CompilationResult | None:
        """Compile a normalized document into a wiki article."""
        log.info("Compiling document", title=doc.title, tokens=doc.estimated_tokens)

        # For large documents, compile in chunks and merge
        if doc.estimated_tokens > 80_000:
            return await self._compile_chunked(doc, session)

        request = CompletionRequest(
            system=COMPILER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_user_prompt(doc)}],
            max_tokens=4096,
            temperature=0.2,  # Low temp for factual compilation
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        response = await self.router.complete(request, session=session)

        try:
            data = self.router.parse_json_response(response)
            return CompilationResult(**data)
        except Exception as e:
            log.error("Failed to parse compilation response", error=str(e))
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

    async def _compile_chunked(self, doc: NormalizedDocument, session: AsyncSession) -> CompilationResult | None:
        """Compile large documents in chunks and merge results."""
        log.info("Chunked compilation", chunks=len(doc.chunks))
        chunk_results = []

        for i, chunk in enumerate(doc.chunks[:10]):  # Max 10 chunks
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
        """Persist compiled article to filesystem and database."""
        slug = self._generate_unique_slug(result.title)
        file_path = self._write_article_file(result, source, slug)

        article = Article(
            slug=slug,
            title=result.title,
            file_path=str(file_path),
            confidence=self._overall_confidence(result),
            summary=result.summary,
            source_ids=f'["{source.id}"]',
            concept_ids=f'["{chr(34).join(result.concepts)}"]',
        )

        session.add(article)

        # Update source status
        source.status = IngestStatus.COMPILED
        source.compiled_at = datetime.utcnow()
        session.add(source)

        await session.commit()
        await session.refresh(article)

        log.info("Article saved", slug=slug, title=result.title)
        return article

    def _generate_unique_slug(self, title: str) -> str:
        base = slugify(title, max_length=80)
        return base

    def _write_article_file(
        self,
        result: CompilationResult,
        source: Source,
        slug: str,
    ) -> Path:
        """Write .md file to wiki directory."""
        wiki_dir = Path(self.settings.data_dir) / "wiki"

        # Determine subdirectory from first concept
        concept = result.concepts[0] if result.concepts else "general"
        concept_dir = wiki_dir / slugify(concept)
        concept_dir.mkdir(parents=True, exist_ok=True)

        file_path = concept_dir / f"{slug}.md"

        # Build backlinks section
        backlinks = "\n".join([f"- [[{b}]]" for b in result.backlink_suggestions])

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
compiled: {datetime.utcnow().isoformat()}
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
