"""WikiMind Q&A Agent.

Answers questions against the compiled wiki.
Every answer can be filed back to make the wiki smarter.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
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
    CostLog,
    PageType,
    Query,
    QueryRequest,
    QueryResult,
    TaskType,
)
from wikimind.services.activity_log import append_log_entry
from wikimind.storage import resolve_wiki_path

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


@dataclass
class _PreparedContext:
    """Bundle of data prepared before an LLM call (shared by answer and answer_stream)."""

    conversation: Conversation
    next_turn_index: int
    prior_turns: list[Query]
    wiki_context: list[dict]
    completion_request: CompletionRequest | None  # None when wiki_context is empty
    no_context_result: QueryResult | None  # non-None when wiki_context is empty


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

        For forked conversations, also walks the parent chain to include
        ancestor turns that precede the fork point, providing full context.

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

        # Check if this is a forked conversation — if so, materialize ancestor turns
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None and conversation.parent_conversation_id is not None:
            # Collect ancestor turns by walking the parent chain
            all_turns: list[Query] = []
            current = conversation
            ancestors: list[tuple[str, int]] = []
            while current.parent_conversation_id is not None and current.forked_at_turn_index is not None:
                ancestors.append((current.parent_conversation_id, current.forked_at_turn_index))
                parent = await session.get(Conversation, current.parent_conversation_id)
                if parent is None:
                    break
                current = parent
            ancestors.reverse()

            for ancestor_id, fork_at in ancestors:
                result = await session.execute(
                    select(Query)
                    .where(Query.conversation_id == ancestor_id)
                    .where(Query.turn_index < fork_at)
                    .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
                )
                all_turns.extend(result.scalars().all())

            # Add this conversation's own prior turns
            result = await session.execute(
                select(Query)
                .where(Query.conversation_id == conversation_id)
                .where(Query.turn_index < up_to_turn_index)
                .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
            )
            all_turns.extend(result.scalars().all())

            # Take the most recent `cap` turns
            return all_turns[-cap:] if len(all_turns) > cap else all_turns

        # Non-forked conversation: simple query
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

    async def _prepare_context(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> _PreparedContext:
        """Prepare everything needed before the LLM call.

        Resolves the conversation, loads prior turns, retrieves wiki context,
        and builds the CompletionRequest. Shared by ``answer()`` and
        ``answer_stream()``.

        Args:
            request: The query request.
            session: Async database session.

        Returns:
            A :class:`_PreparedContext` with all data needed for the LLM call.
        """
        log.info("Q&A query", question=request.question[:100])

        conversation = await self._get_or_create_conversation(request, session)

        prior_turns: list[Query] = []
        if request.conversation_id is not None:
            next_turn_index = await self._next_turn_index(conversation.id, session)
            prior_turns = await self._load_prior_turns(
                conversation.id, up_to_turn_index=next_turn_index, session=session
            )
        else:
            next_turn_index = 0

        wiki_context = await self._retrieve_context(request.question, session)

        if not wiki_context:
            return _PreparedContext(
                conversation=conversation,
                next_turn_index=next_turn_index,
                prior_turns=prior_turns,
                wiki_context=wiki_context,
                completion_request=None,
                no_context_result=QueryResult(
                    answer=(
                        "No relevant articles found in your wiki for this question."
                        " Consider ingesting sources on this topic."
                    ),
                    confidence="low",
                    sources=[],
                    related_articles=[],
                    follow_up_questions=[f"What sources cover {request.question}?"],
                ),
            )

        completion_request = self._build_completion_request(request.question, wiki_context, prior_turns)
        return _PreparedContext(
            conversation=conversation,
            next_turn_index=next_turn_index,
            prior_turns=prior_turns,
            wiki_context=wiki_context,
            completion_request=completion_request,
            no_context_result=None,
        )

    def _build_completion_request(
        self,
        question: str,
        context: list[dict],
        prior_turns: list[Query],
    ) -> CompletionRequest:
        """Build the CompletionRequest for the LLM call.

        Extracted from ``_query_llm`` so it can be reused by streaming.

        Args:
            question: The user's question.
            context: Wiki articles retrieved as context.
            prior_turns: Prior conversation turns.

        Returns:
            A :class:`CompletionRequest` ready to send to the router.
        """
        context_text = "\n\n---\n\n".join([f"## {c['title']}\n\n{c['content']}" for c in context])

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

        return CompletionRequest(
            system=QA_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.QA,
        )

    async def _persist_query(
        self,
        request: QueryRequest,
        result: QueryResult,
        ctx: _PreparedContext,
        session: AsyncSession,
    ) -> tuple[Query, Conversation]:
        """Persist the Query row and handle file-back.

        Shared by ``answer()`` and the ``answer_stream()`` completion path.

        Args:
            request: Original query request.
            result: Parsed QA result from the LLM.
            ctx: Prepared context from ``_prepare_context()``.
            session: Async database session.

        Returns:
            Tuple of (the new Query row, the parent Conversation).
        """
        query_record = Query(
            question=request.question,
            answer=result.answer,
            confidence=result.confidence,
            source_article_ids=json.dumps(result.sources),
            related_article_ids=json.dumps(result.related_articles),
            conversation_id=ctx.conversation.id,
            turn_index=ctx.next_turn_index,
        )
        session.add(query_record)

        ctx.conversation.updated_at = utcnow_naive()
        session.add(ctx.conversation)

        filed_article: Article | None = None
        if request.file_back and result.confidence in ("high", "medium"):
            await session.flush()
            article, _ = await self._file_back_thread(ctx.conversation.id, session)
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
                    extra={"conversation_id": ctx.conversation.id},
                )
        except Exception:
            log.warning("activity log write failed", op="query")

        await session.refresh(query_record)
        await session.refresh(ctx.conversation)

        return query_record, ctx.conversation

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
        ctx = await self._prepare_context(request, session)

        if ctx.no_context_result is not None:
            result = ctx.no_context_result
        else:
            result = await self._query_llm(request.question, ctx.wiki_context, ctx.prior_turns, session)

        return await self._persist_query(request, result, ctx, session)

    async def answer_stream(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> AsyncIterator[str | tuple[Query, Conversation]]:
        """Stream LLM tokens, then yield the persisted (Query, Conversation) tuple.

        Yields text chunk strings during streaming. After all tokens have been
        yielded, yields a single ``(Query, Conversation)`` tuple as the final
        item. The caller (service layer) is responsible for constructing SSE
        events from these values.

        If wiki context is empty, yields the canned answer text as one chunk
        followed by the persisted tuple.

        Raises:
            RuntimeError: When all LLM providers fail.

        Args:
            request: The query request.
            session: Async database session.

        Yields:
            ``str`` text chunks, then a final ``tuple[Query, Conversation]``.
        """
        ctx = await self._prepare_context(request, session)

        if ctx.no_context_result is not None:
            result = ctx.no_context_result
            yield result.answer
            query_record, conversation = await self._persist_query(request, result, ctx, session)
            yield (query_record, conversation)
            return

        assert ctx.completion_request is not None
        stream_session = await self.router.stream_complete(ctx.completion_request)
        full_text_parts: list[str] = []
        async for chunk_text in stream_session:
            full_text_parts.append(chunk_text)
            yield chunk_text

        full_text = "".join(full_text_parts)

        # Log cost from the completed stream
        if stream_session.result is not None:
            resp = stream_session.result
            cost_entry = CostLog(
                provider=resp.provider_used,
                model=resp.model_used,
                task_type=TaskType.QA,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_usd=resp.cost_usd,
                latency_ms=resp.latency_ms,
            )
            session.add(cost_entry)
            await session.commit()

        # Parse the accumulated JSON
        try:
            content = full_text.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            data = json.loads(content)
            result = QueryResult(**data)
        except Exception as e:
            log.error("Failed to parse streamed QA response", error=str(e))
            result = QueryResult(
                answer="Error processing answer. Please try again.",
                confidence="low",
                sources=[],
                related_articles=[],
            )

        query_record, conversation = await self._persist_query(request, result, ctx, session)
        yield (query_record, conversation)

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
            return resolve_wiki_path(file_path).read_text(encoding="utf-8")
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
        request_obj = self._build_completion_request(question, context, prior_turns)

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

            # Store wiki-relative path in the DB
            relative_path = f"qa-answers/{slug}.md"
            article = Article(
                slug=slug,
                title=conversation.title,
                file_path=relative_path,
                summary=(queries[0].answer[:200] if queries else None),
                confidence=None,  # per #84 / Option 2 — Q&A confidence is on Query, not Article
                page_type=PageType.ANSWER,
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
        resolve_wiki_path(existing_article.file_path).write_text(markdown, encoding="utf-8")
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
