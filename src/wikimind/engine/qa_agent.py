"""WikiMind Q&A Agent.

Answers questions against the compiled wiki.
Every answer can be filed back to make the wiki smarter.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import HTTPException
from slugify import slugify
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import Article, CompletionRequest, Conversation, Query, QueryRequest, QueryResult, TaskType

log = structlog.get_logger()


QA_SYSTEM_PROMPT = """You are a knowledge retrieval agent for a personal wiki.

Your job: answer the user's question using ONLY the wiki articles provided in context.

Rules:
- If the answer is not in the wiki, say so explicitly. Do NOT hallucinate.
- Cite specific articles by title when making claims
- If you can partially answer from the wiki, do so and note the gaps
- Suggest follow-up questions that would help fill knowledge gaps
- If the answer reveals a gap in the wiki, suggest a new article title

You MUST respond with valid JSON only. No preamble, no markdown fences.

Output schema:
{
  "answer": "Your complete answer in markdown",
  "confidence": "high|medium|low",
  "sources": ["Article Title 1", "Article Title 2"],
  "related_articles": ["Title of related article worth reading"],
  "new_article_suggested": "Optional: title of article that should be created",
  "follow_up_questions": ["Question 1", "Question 2"]
}
"""


class QAAgent:
    """Answer questions against the compiled wiki."""

    def __init__(self):
        self.router = get_llm_router()
        self.settings = get_settings()

    async def _load_prior_turns(
        self,
        conversation_id: str,
        up_to_turn_index: int,
        session: AsyncSession,
    ) -> list[Query]:
        """Load up to qa.max_prior_turns_in_context turns from a conversation.

        Returns the most recent N prior turns (where N = the configured cap),
        ordered ascending by turn_index so they can be formatted into the
        prompt in conversational order.

        Args:
            conversation_id: The conversation to load turns from.
            up_to_turn_index: Only return turns whose turn_index is strictly
                less than this value (i.e. turns BEFORE the one being asked).
            session: Async database session.

        Returns:
            List of Query rows ordered by turn_index ascending.
        """
        cap = self.settings.qa.max_prior_turns_in_context
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .where(Query.turn_index < up_to_turn_index)
            .order_by(Query.turn_index.desc())  # type: ignore[attr-defined]
            .limit(cap)
        )
        rows = list(result.scalars().all())
        rows.sort(key=lambda q: q.turn_index)  # back to ascending for prompt order
        return rows

    async def _get_or_create_conversation(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> Conversation:
        """Resolve an existing conversation or create a new one for this question."""
        if request.conversation_id is not None:
            existing = await session.get(Conversation, request.conversation_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Conversation not found")
            return existing

        title_max = self.settings.qa.conversation_title_max_chars
        new_conv = Conversation(
            title=request.question[:title_max],
        )
        session.add(new_conv)
        await session.flush()  # populate new_conv.id without committing
        return new_conv

    async def _next_turn_index(self, conversation_id: str, session: AsyncSession) -> int:
        """Return the next turn_index for a conversation (max + 1, or 0 if empty)."""
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .order_by(Query.turn_index.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        last = result.scalars().first()
        return (last.turn_index + 1) if last is not None else 0

    async def answer(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> tuple[Query, Conversation]:
        """Answer a question against the wiki.

        Conversation-aware: if request.conversation_id is None a new
        Conversation is created with this question's text as its title.
        Otherwise the turn is appended to the existing conversation and
        the prompt is augmented with the prior N turns as context.

        Args:
            request: The QueryRequest with question and optional conversation_id.
            session: Async database session.

        Returns:
            Tuple of (the new Query row, the parent Conversation).
        """
        log.info("Q&A query", question=request.question[:100])

        # Resolve or create the conversation
        conversation = await self._get_or_create_conversation(request, session)

        # Load prior turns BEFORE persisting the new one (so the new turn
        # doesn't appear in its own context)
        prior_turns: list[Query] = []
        if request.conversation_id is not None:
            next_turn_index = await self._next_turn_index(conversation.id, session)
            prior_turns = await self._load_prior_turns(
                conversation.id, up_to_turn_index=next_turn_index, session=session
            )
        else:
            next_turn_index = 0

        # Retrieve wiki context (unchanged from prior implementation)
        context = await self._retrieve_context(request.question, session)

        if not context:
            result = QueryResult(
                answer="No relevant articles found in your wiki for this question. Consider ingesting sources on this topic.",
                confidence="low",
                sources=[],
                related_articles=[],
                follow_up_questions=[f"What sources cover {request.question}?"],
            )
        else:
            result = await self._query_llm(request.question, context, prior_turns, session)

        # Persist the new Query row
        query_record = Query(
            question=request.question,
            answer=result.answer,
            confidence=result.confidence,
            source_article_ids=json.dumps(result.sources),
            related_article_ids=json.dumps(result.related_articles),
            conversation_id=conversation.id,
            turn_index=next_turn_index,
        )
        session.add(query_record)

        # File back if requested
        if request.file_back and result.confidence in ("high", "medium"):
            article_id = await self._file_back(request.question, result, session)
            query_record.filed_back = True
            query_record.filed_article_id = article_id

        # Touch the conversation's updated_at
        conversation.updated_at = datetime.utcnow()
        session.add(conversation)

        await session.commit()
        await session.refresh(query_record)
        await session.refresh(conversation)

        return query_record, conversation

    async def _retrieve_context(self, question: str, session: AsyncSession) -> list[dict]:
        """Retrieve relevant wiki articles for the question."""
        # Extract key terms from question (simple approach for Phase 1)
        terms = [t for t in question.lower().split() if len(t) > 3]

        result = await session.execute(select(Article))
        all_articles = result.scalars().all()

        relevant = []
        for article in all_articles:
            content = self._read_article_content(article.file_path)
            if not content:
                continue

            # Score by term overlap
            score = sum(1 for t in terms if t in content.lower())
            if score > 0:
                relevant.append(
                    {
                        "title": article.title,
                        "content": content[:3000],  # Truncate for context window
                        "score": score,
                    }
                )

        # Sort by relevance, take top 5
        relevant.sort(key=lambda x: x["score"], reverse=True)
        return relevant[:5]

    def _read_article_content(self, file_path: str) -> str | None:
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except Exception:
            return None

    async def _query_llm(
        self,
        question: str,
        context: list[dict],
        prior_turns: list[Query],
        session: AsyncSession,
    ) -> QueryResult:
        """Build the LLM prompt (with optional conversation context) and call the router."""
        # Wiki context block (unchanged)
        context_text = "\n\n---\n\n".join([f"## {c['title']}\n\n{c['content']}" for c in context])

        # Conversation context block — only present when there are prior turns
        conv_block = ""
        if prior_turns:
            truncate_chars = self.settings.qa.prior_answer_truncate_chars
            conv_lines: list[str] = ["", "---", "", "Conversation so far:"]
            for prior in prior_turns:
                turn_n = prior.turn_index + 1
                truncated = prior.answer[:truncate_chars]
                conv_lines.append(f"Q{turn_n}: {prior.question}")
                conv_lines.append(f"A{turn_n}: {truncated}")
            conv_block = "\n".join(conv_lines)

        user_message = f"""Wiki context:

{context_text}{conv_block}

---

Current question: {question}

Answer based on the wiki context above. Use the conversation history
to disambiguate references like "it" or "that approach". If the
conversation context contradicts the wiki, prefer the wiki."""

        request_obj = CompletionRequest(
            system=QA_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.QA,
        )

        response = await self.router.complete(request_obj, session=session)

        try:
            data = self.router.parse_json_response(response)
            return QueryResult(**data)
        except Exception as e:
            log.error("Failed to parse QA response", error=str(e))
            return QueryResult(
                answer="Error processing answer. Please try again.",
                confidence="low",
                sources=[],
                related_articles=[],
            )

    async def _file_back(
        self,
        question: str,
        result: QueryResult,
        session: AsyncSession,
    ) -> str | None:
        """Save Q&A answer as a new wiki article."""
        wiki_dir = Path(self.settings.data_dir) / "wiki" / "qa-answers"
        wiki_dir.mkdir(parents=True, exist_ok=True)

        slug = slugify(question[:80])
        file_path = wiki_dir / f"{slug}.md"

        sources_list = "\n".join([f"- [[{s}]]" for s in result.sources])
        related_list = "\n".join([f"- [[{r}]]" for r in result.related_articles])
        questions_list = "\n".join([f"- {q}" for q in result.follow_up_questions])

        content = f"""---
title: "Q: {question}"
slug: {slug}
type: qa-answer
confidence: {result.confidence}
compiled: {datetime.utcnow().isoformat()}
---

## Question

{question}

## Answer

{result.answer}

## Sources

{sources_list}

## Related

{related_list}

## Follow-up Questions

{questions_list}
"""

        file_path.write_text(content, encoding="utf-8")

        # Q&A answer confidence ("high"/"medium"/"low") is a different concept
        # from Article.confidence (sourced/mixed/inferred/opinion), so we leave
        # the article-level confidence unset on filed-back answers. The agent's
        # confidence string is preserved on the originating Query row.
        article = Article(
            slug=slug,
            title=f"Q: {question[:80]}",
            file_path=str(file_path),
            summary=result.answer[:200],
            confidence=None,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)

        log.info("Answer filed back to wiki", slug=slug)
        return article.id
