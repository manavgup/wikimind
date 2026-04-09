"""WikiMind Q&A Agent.

Answers questions against the compiled wiki.
Every answer can be filed back to make the wiki smarter.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.conversation_serializer import serialize_conversation_to_markdown
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    CompletionRequest,
    Conversation,
    Query,
    QueryRequest,
    QueryResult,
    TaskType,
)
from wikimind.services.activity_log import append_log_entry

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

        # Touch the conversation's updated_at
        conversation.updated_at = utcnow_naive()
        session.add(conversation)

        # File back if requested — stage the changes and let the single
        # commit below persist everything atomically (no double commit).
        filed_article: Article | None = None
        if request.file_back and result.confidence in ("high", "medium"):
            await session.flush()  # make the new Query visible to file_back's SELECT
            article, _ = await self._file_back_thread(conversation.id, session)
            query_record.filed_back = True
            query_record.filed_article_id = article.id
            filed_article = article
            session.add(query_record)

        await session.commit()

        try:
            append_log_entry("query", request.question[:120])
            if filed_article is not None:
                append_log_entry(
                    "filed",
                    filed_article.title,
                    extra={"conversation_id": conversation.id},
                )
        except Exception:
            log.warning("activity log write failed", op="query")

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

    async def _file_back_thread(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> tuple[Article, bool]:
        """File a whole conversation back to the wiki as a single article.

        STAGES changes but does NOT commit — the caller owns the
        commit so that file-back operations land atomically with any
        other changes the caller has pending (e.g. the new Query row in
        answer()).

        If the conversation has not been filed back before, creates a
        new Article with slug = conversation.id (guaranteed unique).
        If it has, overwrites the existing Article's .md file in place.
        The article id, slug, and file_path stay stable across re-saves.

        See ADR-011 for the rationale on per-conversation file-back.

        Args:
            conversation_id: The conversation to file back.
            session: Async database session.

        Returns:
            Tuple of (article, was_update). was_update is True when an
            existing article was overwritten.
        """
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Load all turns ordered by turn_index
        result = await session.execute(
            select(Query).where(Query.conversation_id == conversation_id).order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
        )
        queries = list(result.scalars().all())

        markdown = serialize_conversation_to_markdown(conversation, queries)
        now = utcnow_naive()

        # Defensive: if filed_article_id points at a missing Article, clear it
        # and treat as a first save in this same invocation (no recursion).
        existing_article: Article | None = None
        if conversation.filed_article_id is not None:
            existing_article = await session.get(Article, conversation.filed_article_id)
            if existing_article is None:
                log.warning(
                    "Conversation.filed_article_id pointed at missing Article — recreating",
                    conversation_id=conversation_id,
                )
                conversation.filed_article_id = None

        if existing_article is None:
            # Create path
            wiki_dir = Path(self.settings.data_dir) / "wiki" / "qa-answers"
            wiki_dir.mkdir(parents=True, exist_ok=True)

            slug = conversation.id  # UUID — guaranteed unique, no collision possible
            file_path = wiki_dir / f"{slug}.md"
            file_path.write_text(markdown, encoding="utf-8")

            article = Article(
                slug=slug,
                title=conversation.title,
                file_path=str(file_path),
                summary=(queries[0].answer[:200] if queries else None),
                confidence=None,  # per #84 / Option 2 — Q&A confidence is on Query, not Article
                created_at=now,
                updated_at=now,
            )
            session.add(article)
            await session.flush()  # populate article.id before the caller commits

            conversation.filed_article_id = article.id
            conversation.updated_at = now
            session.add(conversation)

            log.info(
                "Conversation filed back to wiki (created, pending commit)",
                conversation_id=conversation_id,
                article_id=article.id,
            )
            return article, False

        # Update path: overwrite the existing Article's file in place
        Path(existing_article.file_path).write_text(markdown, encoding="utf-8")
        existing_article.updated_at = now
        conversation.updated_at = now
        session.add(existing_article)
        session.add(conversation)

        log.info(
            "Conversation filed back to wiki (updated, pending commit)",
            conversation_id=conversation_id,
            article_id=existing_article.id,
        )
        return existing_article, True
