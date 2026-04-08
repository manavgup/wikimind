"""End-to-end integration test for the Q&A → file-back loop.

Regression coverage for issue #84: the previous implementation of
``QAAgent._file_back`` coerced ``QueryResult.confidence`` (one of
``"high" | "medium" | "low"``) into the ``ConfidenceLevel`` enum (whose
members are ``sourced/mixed/inferred/opinion``), which raised ``ValueError``
on the real file-back path. Existing unit tests in
``tests/unit/test_qa_agent.py`` mocked ``_file_back`` itself and never
exercised the bug.

This test wires the agent up against the real in-memory database, seeds an
Article so retrieval has something to find, and runs the full
``answer(file_back=True)`` path with only the LLM router mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine import qa_agent as qa_mod
from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    CompletionResponse,
    Provider,
    Query,
    QueryRequest,
)

_FAKE_QA_SETTINGS = SimpleNamespace(
    data_dir="/tmp",
    qa=SimpleNamespace(
        max_prior_turns_in_context=5,
        prior_answer_truncate_chars=500,
        conversation_title_max_chars=120,
    ),
)


async def test_ask_with_file_back_creates_article_end_to_end(
    db_session: AsyncSession,
    tmp_path,
) -> None:
    """``answer(file_back=True)`` must persist a Query and a filed Article.

    Exercises the real loop: retrieve context → query LLM (mocked at the
    router boundary) → persist Query row → file back as Article. Asserts
    that no exception is raised (regression for #84) and that the
    Query → Article linkage is intact in the DB.
    """
    # Seed an article so _retrieve_context returns a non-empty list and the
    # agent takes the _query_llm branch (not the empty-context shortcut).
    article_md = tmp_path / "knowledge.md"
    article_md.write_text(
        "# Knowledge\n\nThe wikimind project answers questions from sources.",
        encoding="utf-8",
    )
    seed = Article(
        slug="knowledge",
        title="Knowledge",
        file_path=str(article_md),
        summary="seed article",
    )
    db_session.add(seed)
    await db_session.commit()

    # Build a QAAgent with the LLM router and settings patched at construction
    # time, mirroring the helper used by tests/unit/test_qa_agent.py.
    with (
        patch.object(qa_mod, "get_llm_router"),
        patch.object(
            qa_mod,
            "get_settings",
            return_value=SimpleNamespace(
                data_dir=str(tmp_path),
                qa=SimpleNamespace(
                    max_prior_turns_in_context=5,
                    prior_answer_truncate_chars=500,
                    conversation_title_max_chars=120,
                ),
            ),
        ),
    ):
        agent = QAAgent()

    # Mock the router boundary: complete() returns an envelope, and
    # parse_json_response yields a canned QueryResult dict whose
    # confidence is "high" — the exact value that used to crash _file_back.
    fake_response = CompletionResponse(
        content="{}",
        provider_used=Provider.ANTHROPIC,
        model_used="test-model",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    agent.router.complete = AsyncMock(return_value=fake_response)
    agent.router.parse_json_response = lambda _resp: {
        "answer": "Yes, wikimind answers questions from sources.",
        "confidence": "high",
        "sources": ["Knowledge"],
        "related_articles": [],
        "follow_up_questions": [],
    }

    request = QueryRequest(
        question="Does wikimind answer questions from sources?",
        file_back=True,
    )

    # Real call — must not raise. Pre-fix this raised ValueError because
    # ConfidenceLevel("high") is not a member of the enum.
    # answer() now returns a tuple of (Query, Conversation).
    query, _ = await agent.answer(request, db_session)

    # Query row was persisted with the agent-confidence string preserved.
    assert query.id is not None
    assert query.confidence == "high"

    # File-back populated the linkage fields.
    assert query.filed_back is True
    assert query.filed_article_id is not None

    # The filed Article actually exists in the DB at the linked id.
    filed = await db_session.get(Article, query.filed_article_id)
    assert filed is not None
    assert filed.title == "Does wikimind answer questions from sources?"
    # Per Option 2: article-level confidence is left unset on filed-back
    # answers because Q&A confidence and Article confidence are different
    # concepts. The Query row carries the agent's confidence string instead.
    assert filed.confidence is None

    # Sanity: the Query row is queryable end-to-end via the session.
    fetched = (await db_session.execute(select(Query).where(Query.id == query.id))).scalar_one()
    assert fetched.filed_article_id == filed.id


async def test_multi_turn_conversation_includes_prior_context_in_prompt(
    db_session: AsyncSession,
) -> None:
    """Q1 establishes context. Q2 in the same conversation must include Q1 in the LLM prompt."""
    # Build the agent with patched router and settings
    with (
        patch.object(qa_mod, "get_llm_router"),
        patch.object(qa_mod, "get_settings", return_value=_FAKE_QA_SETTINGS),
    ):
        agent = QAAgent()

    # Capture every CompletionRequest passed to router.complete
    captured_requests: list = []

    async def _fake_complete(request, session):
        captured_requests.append(request)
        return '{"answer": "fake answer", "confidence": "high", "sources": [], "related_articles": [], "follow_up_questions": []}'

    agent.router.complete = AsyncMock(side_effect=_fake_complete)
    agent.router.parse_json_response = lambda _resp: {
        "answer": "fake answer",
        "confidence": "high",
        "sources": [],
        "related_articles": [],
        "follow_up_questions": [],
    }

    # Seed one Article so the empty-context shortcut is not taken
    seed = Article(
        id="art-multiturn",
        slug="seed-multiturn",
        title="Seed Article",
        file_path="/dev/null",
        summary="seed",
    )
    db_session.add(seed)
    await db_session.commit()

    # Stub _retrieve_context to avoid filesystem reads; return one item so
    # context is non-empty and _query_llm is called for both turns
    agent._retrieve_context = AsyncMock(return_value=[{"title": "Seed Article", "content": "seed content", "score": 1}])

    # Q1 — starts a new conversation
    _q1, conv = await agent.answer(QueryRequest(question="What is X?"), db_session)

    # Q2 — continues the same conversation
    _q2, _ = await agent.answer(
        QueryRequest(question="How does it work?", conversation_id=conv.id),
        db_session,
    )

    # Both LLM calls must have been captured
    assert len(captured_requests) == 2

    # Q1's prompt must NOT include the conversation block (no prior turns)
    first_user_msg = captured_requests[0].messages[0]["content"]
    assert "Conversation so far:" not in first_user_msg

    # The second call's user message must contain the Q1+A1 conversation block
    second_user_msg = captured_requests[1].messages[0]["content"]
    assert "Conversation so far:" in second_user_msg
    assert "Q1: What is X?" in second_user_msg
    assert "A1: fake answer" in second_user_msg
    assert "Current question: How does it work?" in second_user_msg
