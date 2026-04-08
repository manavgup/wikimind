"""Tests for the QA agent."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from wikimind.config import QAConfig
from wikimind.engine import qa_agent as qa_mod
from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    CompletionResponse,
    Conversation,
    Provider,
    Query,
    QueryRequest,
    QueryResult,
)


def _agent(tmp_path) -> QAAgent:
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
        return QAAgent()


def test_read_article_content_missing(tmp_path) -> None:
    a = _agent(tmp_path)
    assert a._read_article_content("/no/such/file.md") is None


def test_read_article_content_ok(tmp_path) -> None:
    a = _agent(tmp_path)
    f = tmp_path / "x.md"
    f.write_text("hello", encoding="utf-8")
    assert a._read_article_content(str(f)) == "hello"


async def test_retrieve_context_scores(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    f1 = tmp_path / "a.md"
    f1.write_text("apple banana cherry", encoding="utf-8")
    f2 = tmp_path / "b.md"
    f2.write_text("nothing here", encoding="utf-8")
    art1 = Article(slug="a", title="A", file_path=str(f1))
    art2 = Article(slug="b", title="B", file_path=str(f2))
    db_session.add_all([art1, art2])
    await db_session.commit()
    ctx = await a._retrieve_context("apple banana", db_session)
    assert len(ctx) == 1
    assert ctx[0]["title"] == "A"


async def test_retrieve_context_skips_unreadable(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    art = Article(slug="x", title="X", file_path="/no/such/file")
    db_session.add(art)
    await db_session.commit()
    assert await a._retrieve_context("anything", db_session) == []


async def test_query_llm_success(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    fake_resp = CompletionResponse(
        content="{}",
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    a.router.complete = AsyncMock(return_value=fake_resp)
    a.router.parse_json_response = lambda r: {
        "answer": "yes",
        "confidence": "high",
        "sources": ["A"],
        "related_articles": [],
        "follow_up_questions": [],
    }
    res = await a._query_llm("Q?", [{"title": "A", "content": "C"}], [], db_session)
    assert res.answer == "yes"
    assert res.confidence == "high"


async def test_query_llm_parse_error_returns_fallback(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    fake_resp = CompletionResponse(
        content="bad",
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    a.router.complete = AsyncMock(return_value=fake_resp)
    a.router.parse_json_response = lambda r: (_ for _ in ()).throw(ValueError("bad"))
    res = await a._query_llm("Q?", [{"title": "A", "content": "C"}], [], db_session)
    assert res.confidence == "low"


async def test_file_back_creates_article(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    result = QueryResult(
        answer="ans",
        confidence="sourced",
        sources=["A"],
        related_articles=["R"],
        follow_up_questions=["Q1"],
    )
    article_id = await a._file_back("What is X?", result, db_session)
    assert article_id is not None


async def test_answer_no_context(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    with patch.object(a, "_retrieve_context", AsyncMock(return_value=[])):
        q, _conversation = await a.answer(QueryRequest(question="hello"), db_session)
    assert q.confidence == "low"


async def test_answer_with_context_and_file_back(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    # Patch _file_back to bypass enum lookup (qa file_back maps result.confidence
    # to ConfidenceLevel which doesn't include high/medium/low values).
    with (
        patch.object(a, "_retrieve_context", AsyncMock(return_value=[{"title": "T", "content": "C"}])),
        patch.object(
            a,
            "_query_llm",
            AsyncMock(return_value=QueryResult(answer="A", confidence="high", sources=[], related_articles=[])),
        ),
        patch.object(a, "_file_back", AsyncMock(return_value="art-1")),
    ):
        q, _conversation = await a.answer(QueryRequest(question="hi", file_back=True), db_session)
    assert q.filed_back is True
    assert q.filed_article_id == "art-1"


async def test_answer_with_context_no_file_back(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    qr = QueryResult(answer="A", confidence="low", sources=[], related_articles=[])
    with (
        patch.object(a, "_retrieve_context", AsyncMock(return_value=[{"title": "T", "content": "C"}])),
        patch.object(a, "_query_llm", AsyncMock(return_value=qr)),
    ):
        q, _conversation = await a.answer(QueryRequest(question="hi", file_back=True), db_session)
    assert q.filed_back is False


async def test_answer_creates_new_conversation_when_id_missing(db_session, tmp_path) -> None:
    """answer() with no conversation_id creates a new Conversation and returns turn 0."""
    with (
        patch.object(qa_mod, "get_llm_router"),
        patch.object(
            qa_mod,
            "get_settings",
            return_value=SimpleNamespace(
                data_dir=str(tmp_path),
                qa=QAConfig(),
            ),
        ),
    ):
        agent = QAAgent()

    with (
        patch.object(agent, "_retrieve_context", AsyncMock(return_value=[])),
    ):
        req = QueryRequest(question="What is the meaning of life?")
        query, conversation = await agent.answer(req, db_session)

    assert isinstance(conversation, Conversation)
    assert conversation.title == "What is the meaning of life?"
    assert query.conversation_id == conversation.id
    assert query.turn_index == 0


async def test_answer_appends_to_existing_conversation(db_session, tmp_path) -> None:
    """answer() with a conversation_id appends a new turn with the next turn_index."""
    conv = Conversation(
        id="conv-existing",
        title="prior question",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(conv)
    db_session.add(
        Query(
            id="q-prior",
            question="prior question",
            answer="prior answer",
            conversation_id="conv-existing",
            turn_index=0,
        )
    )
    await db_session.commit()

    with (
        patch.object(qa_mod, "get_llm_router"),
        patch.object(
            qa_mod,
            "get_settings",
            return_value=SimpleNamespace(
                data_dir=str(tmp_path),
                qa=QAConfig(),
            ),
        ),
    ):
        agent = QAAgent()

    with (
        patch.object(agent, "_retrieve_context", AsyncMock(return_value=[])),
    ):
        req = QueryRequest(question="follow-up question", conversation_id="conv-existing")
        query, conversation = await agent.answer(req, db_session)

    assert conversation.id == "conv-existing"
    assert query.conversation_id == "conv-existing"
    assert query.turn_index == 1


async def test_load_prior_turns_returns_in_order_capped_at_max(db_session, tmp_path) -> None:
    """_load_prior_turns returns at most qa.max_prior_turns_in_context, ordered by turn_index."""
    conv = Conversation(id="conv-x", title="t", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db_session.add(conv)

    for i in range(7):
        db_session.add(
            Query(
                id=f"q-{i}",
                question=f"q{i}",
                answer=f"a{i}",
                conversation_id="conv-x",
                turn_index=i,
            )
        )
    await db_session.commit()

    with (
        patch.object(qa_mod, "get_llm_router"),
        patch.object(
            qa_mod,
            "get_settings",
            return_value=SimpleNamespace(data_dir=str(tmp_path), qa=QAConfig(max_prior_turns_in_context=5)),
        ),
    ):
        agent = QAAgent()
        prior = await agent._load_prior_turns("conv-x", up_to_turn_index=7, session=db_session)

    assert len(prior) == 5
    assert [q.turn_index for q in prior] == [2, 3, 4, 5, 6]


async def test_answer_raises_404_when_conversation_id_unknown(db_session, tmp_path) -> None:
    """answer() raises HTTPException 404 when given a conversation_id that doesn't exist."""
    a = _agent(tmp_path)
    req = QueryRequest(question="follow-up", conversation_id="conv-does-not-exist")

    with pytest.raises(HTTPException) as exc_info:
        await a.answer(req, db_session)

    assert exc_info.value.status_code == 404
