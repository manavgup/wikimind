"""Distill a multi-turn conversation into a structured wiki article.

Crystallization reads all messages in a conversation thread, asks an LLM
to synthesize the key findings, and persists the result as a new Article
with ``page_type: synthesis``.
"""

import asyncio
import json
from pathlib import Path

import structlog
from slugify import slugify
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.errors import NotFoundError, QueryError
from wikimind.models import (
    Article,
    CompletionRequest,
    Conversation,
    CrystallizeResponse,
    PageType,
    Query,
    TaskType,
)

log = structlog.get_logger()

CRYSTALLIZE_SYSTEM_PROMPT = """You are distilling a multi-turn research conversation into a \
structured wiki article.

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{
  "title": "A concise title derived from the research question",
  "research_question": "What the user was exploring",
  "key_findings": ["Numbered conclusion 1", "Numbered conclusion 2"],
  "explored_but_inconclusive": ["Things discussed but not resolved"],
  "sources_consulted": ["Sources referenced in the conversation"],
  "article_body": "Full markdown article with ## headings."
}

Rules:
- Derive the title from the core research question
- Key findings should be specific, falsifiable conclusions
- Explored-but-inconclusive captures threads that were started but not resolved
- Sources consulted should list any sources mentioned in the answers
- article_body must be substantive -- at least 200 words
- Do not fabricate information not present in the conversation
"""


def _format_conversation(queries: list[Query]) -> str:
    """Format conversation turns into a readable transcript for the LLM."""
    lines: list[str] = []
    for q in queries:
        lines.append(f"User: {q.question}")
        lines.append(f"Assistant: {q.answer}")
        lines.append("")
    return "\n".join(lines)


async def _generate_unique_slug(title: str, session: AsyncSession) -> str:
    """Generate a URL-safe slug, appending a suffix to avoid collisions."""
    base = slugify(title, max_length=80)
    candidate = base
    suffix = 2
    while True:
        existing = (await session.execute(select(Article).where(Article.slug == candidate))).scalars().first()
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def crystallize_conversation(
    conversation_id: str,
    session: AsyncSession,
    user_id: str,
) -> CrystallizeResponse:
    """Distill a conversation into a new wiki article.

    Loads the full conversation, sends it to the LLM for synthesis, and
    creates a new Article with ``page_type=synthesis``.

    Args:
        conversation_id: UUID of the conversation to crystallize.
        session: Async database session.
        user_id: User ID for ownership validation and data isolation.

    Returns:
        :class:`CrystallizeResponse` with the created article metadata.

    Raises:
        NotFoundError: If the conversation does not exist or belongs to another user.
        QueryError: If the conversation has no turns or LLM synthesis fails.
    """
    # Load and validate conversation ownership
    conversation = await session.get(Conversation, conversation_id)
    msg = "Conversation not found"
    if conversation is None:
        raise NotFoundError(msg)
    if user_id and conversation.user_id != user_id:
        raise NotFoundError(msg)

    # Load all turns
    result = await session.execute(
        select(Query).where(Query.conversation_id == conversation_id).order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
    )
    queries = list(result.scalars().all())

    if not queries:
        msg = "Conversation has no turns to crystallize"
        raise QueryError(msg)

    # Build LLM prompt
    formatted = _format_conversation(queries)
    user_prompt = f"""Conversation:
{formatted}

Distill this conversation into a structured wiki article following the JSON schema exactly."""

    router = get_llm_router()
    request = CompletionRequest(
        system=CRYSTALLIZE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=get_settings().compiler.max_tokens,
        temperature=0.3,
        response_format="json",
        task_type=TaskType.COMPILE,
    )

    response = await router.complete(request, user_id=user_id)

    try:
        data = router.parse_json_response(response)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        log.error(
            "Failed to parse crystallization response",
            error=str(e),
            response_preview=response.content[:500] if response else "no response",
        )
        msg = "LLM synthesis failed"
        raise QueryError(msg) from e

    title = data.get("title", conversation.title)
    research_question = data.get("research_question", "")
    key_findings = data.get("key_findings", [])
    explored_inconclusive = data.get("explored_but_inconclusive", [])
    sources_consulted = data.get("sources_consulted", [])
    article_body = data.get("article_body", "")

    # Build markdown content
    now = utcnow_naive()
    slug = await _generate_unique_slug(title, session)

    findings_md = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(key_findings))
    inconclusive_md = "\n".join(f"- {item}" for item in explored_inconclusive)
    sources_md = "\n".join(f"- {s}" for s in sources_consulted)

    content = f"""---
title: "{title}"
slug: {slug}
page_type: synthesis
crystallized_from: {conversation_id}
turns_distilled: {len(queries)}
crystallized_at: {now.isoformat()}
---

## Research Question

{research_question}

## Key Findings

{findings_md}

## Analysis

{article_body}

## Explored but Inconclusive

{inconclusive_md}

## Sources Consulted

{sources_md}
"""

    # Write to disk
    settings = get_settings()
    wiki_dir = Path(settings.data_dir) / "wiki"
    if user_id:
        wiki_dir = wiki_dir / user_id
    synthesis_dir = wiki_dir / "synthesis"
    await asyncio.to_thread(synthesis_dir.mkdir, parents=True, exist_ok=True)

    relative_path = f"synthesis/{slug}.md"
    file_path = wiki_dir / relative_path
    await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")

    # Create Article row
    article = Article(
        slug=slug,
        title=title,
        file_path=relative_path,
        summary=research_question[:200] if research_question else None,
        confidence=None,
        page_type=PageType.SYNTHESIS,
        created_at=now,
        updated_at=now,
        user_id=user_id,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)

    log.info(
        "Conversation crystallized",
        conversation_id=conversation_id,
        article_slug=slug,
        turns=len(queries),
    )

    return CrystallizeResponse(
        article_id=article.id,
        article_slug=article.slug,
        title=article.title,
        turns_distilled=len(queries),
    )
