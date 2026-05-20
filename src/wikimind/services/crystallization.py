"""Distill a multi-turn conversation into a structured wiki article.

Crystallization reads all messages in a conversation thread, asks an LLM
to synthesize the key findings, and persists the result as a new Article
with ``page_type: synthesis``.
"""

import json
from datetime import datetime

import structlog
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
from wikimind.slug import generate_unique_slug
from wikimind.storage import get_wiki_storage

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


def _build_markdown(
    title: str,
    slug: str,
    conversation_id: str,
    turn_count: int,
    now: datetime,
    research_question: str,
    key_findings: list[str],
    explored_inconclusive: list[str],
    sources_consulted: list[str],
    article_body: str,
) -> str:
    """Build the YAML-frontmatter markdown content for the synthesis article."""
    findings_md = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(key_findings))
    inconclusive_md = "\n".join(f"- {item}" for item in explored_inconclusive)
    sources_md = "\n".join(f"- {s}" for s in sources_consulted)

    safe_title = title.replace('"', '\\"')
    return f"""---
title: "{safe_title}"
slug: {slug}
page_type: synthesis
crystallized_from: {conversation_id}
turns_distilled: {turn_count}
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


async def _check_already_crystallized(
    conversation: Conversation,
    session: AsyncSession,
) -> CrystallizeResponse | None:
    """Return an existing response if the conversation was already crystallized.

    If ``crystallized_article_id`` points at a missing Article, clears the
    dangling reference and returns ``None`` so the caller re-crystallizes.
    """
    if conversation.crystallized_article_id is None:
        return None

    existing = await session.get(Article, conversation.crystallized_article_id)
    if existing is None:
        conversation.crystallized_article_id = None
        return None

    log.info(
        "Conversation already crystallized — returning existing article",
        conversation_id=conversation.id,
        article_id=existing.id,
    )
    turn_result = await session.exec(select(Query).where(Query.conversation_id == conversation.id))
    turn_count = len(list(turn_result.all()))
    return CrystallizeResponse(
        article_id=existing.id,
        article_slug=existing.slug,
        title=existing.title,
        turns_distilled=turn_count,
    )


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

    # Idempotency: return existing article if already crystallized
    existing_response = await _check_already_crystallized(conversation, session)
    if existing_response is not None:
        return existing_response

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

    from wikimind.services.plan_routing import plan_aware_complete  # noqa: PLC0415

    router = get_llm_router()
    request = CompletionRequest(
        system=CRYSTALLIZE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=get_settings().compiler.max_tokens,
        temperature=0.3,
        response_format="json",
        task_type=TaskType.COMPILE,
    )

    response = await plan_aware_complete(router, request, user_id, session)

    if response is None:
        msg = "LLM synthesis failed"
        raise QueryError(msg)

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

    now = utcnow_naive()
    slug = await generate_unique_slug(title, session, user_id=user_id)
    content = _build_markdown(
        title,
        slug,
        conversation_id,
        len(queries),
        now,
        research_question,
        key_findings,
        explored_inconclusive,
        sources_consulted,
        article_body,
    )

    # Write to disk
    wiki_storage = get_wiki_storage(user_id)
    relative_path = f"synthesis/{slug}.md"
    await wiki_storage.write(relative_path, content)

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
    await session.flush()

    conversation.crystallized_article_id = article.id
    conversation.updated_at = now
    session.add(conversation)

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
