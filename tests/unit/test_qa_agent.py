"""Tests for the QA agent."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from wikimind._datetime import utcnow_naive
from wikimind.config import QAConfig, get_settings
from wikimind.engine import qa_agent as qa_mod
from wikimind.engine.llm_router import StreamSession
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
from wikimind.storage import resolve_wiki_path


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


async def test_answer_no_context(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    with patch.object(a, "_retrieve_context", AsyncMock(return_value=[])):
        q, _conversation = await a.answer(QueryRequest(question="hello"), db_session)
    assert q.confidence == "low"


async def test_answer_with_context_and_file_back(db_session, tmp_path) -> None:
    a = _agent(tmp_path)
    fake_article = Article(id="art-1", slug="hi", title="hi", file_path="/fake/hi.md")
    with (
        patch.object(a, "_retrieve_context", AsyncMock(return_value=[{"title": "T", "content": "C"}])),
        patch.object(
            a,
            "_query_llm",
            AsyncMock(return_value=QueryResult(answer="A", confidence="high", sources=[], related_articles=[])),
        ),
        patch.object(a, "_file_back_thread", AsyncMock(return_value=(fake_article, False))),
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
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
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
    conv = Conversation(id="conv-x", title="t", created_at=utcnow_naive(), updated_at=utcnow_naive())
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


async def test_file_back_thread_creates_article_when_first_save(db_session, tmp_path, monkeypatch) -> None:
    """First file-back creates a new Article and sets Conversation.filed_article_id."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    conv = Conversation(
        id="c1",
        title="What is X?",
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db_session.add(conv)
    db_session.add(
        Query(
            id="q1",
            question="What is X?",
            answer="X is Y.",
            confidence="high",
            conversation_id="c1",
            turn_index=0,
        )
    )
    await db_session.commit()

    agent = _agent(tmp_path)
    article, was_update = await agent._file_back_thread("c1", db_session)
    await db_session.commit()  # single-commit pattern — test owns the commit

    assert was_update is False
    assert article.id is not None

    # Conversation.filed_article_id is now set
    refreshed = await db_session.get(Conversation, "c1")
    assert refreshed.filed_article_id == article.id

    # The .md file exists on disk
    assert resolve_wiki_path(article.file_path).exists()


async def test_file_back_thread_updates_in_place_on_second_save(db_session, tmp_path, monkeypatch) -> None:
    """Second file-back overwrites the existing Article in place and returns was_update=True."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    conv = Conversation(
        id="c2",
        title="What is Y?",
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db_session.add(conv)
    db_session.add(
        Query(
            id="q1",
            question="What is Y?",
            answer="Y is Z.",
            confidence="high",
            conversation_id="c2",
            turn_index=0,
        )
    )
    await db_session.commit()

    agent = _agent(tmp_path)
    first_article, _ = await agent._file_back_thread("c2", db_session)
    await db_session.commit()  # single-commit pattern — test owns the commit
    first_id = first_article.id
    first_path = first_article.file_path

    # Add another turn to the conversation
    db_session.add(
        Query(
            id="q2",
            question="follow-up",
            answer="more.",
            confidence="high",
            conversation_id="c2",
            turn_index=1,
        )
    )
    await db_session.commit()

    second_article, was_update = await agent._file_back_thread("c2", db_session)
    await db_session.commit()  # single-commit pattern — test owns the commit

    assert was_update is True
    assert second_article.id == first_id  # same article
    assert second_article.file_path == first_path  # same file path

    # The file content now reflects both turns
    content = resolve_wiki_path(first_path).read_text()
    assert "Q1: What is Y?" in content
    assert "Q2: follow-up" in content


async def test_file_back_thread_uses_uuid_slug_so_identical_titles_coexist(db_session, tmp_path, monkeypatch) -> None:
    """Two conversations with identical titles must produce distinct Articles (distinct slugs).

    Regression test for the slug-collision bug: previously the slug was derived
    from slugify(title), so two conversations titled "What is X?" would produce
    the same slug and the second file-back would crash on the unique constraint.
    The fix uses conversation.id as the slug, which is guaranteed unique.
    """
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Create two Conversations with IDENTICAL titles
    conv_a = Conversation(
        id="conv-aaa",
        title="What is machine learning?",
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    conv_b = Conversation(
        id="conv-bbb",
        title="What is machine learning?",  # same title!
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db_session.add(conv_a)
    db_session.add(conv_b)
    db_session.add(
        Query(
            id="q-a",
            question="What is machine learning?",
            answer="First answer",
            conversation_id="conv-aaa",
            turn_index=0,
        )
    )
    db_session.add(
        Query(
            id="q-b",
            question="What is machine learning?",
            answer="Second answer",
            conversation_id="conv-bbb",
            turn_index=0,
        )
    )
    await db_session.commit()

    agent = _agent(tmp_path)

    article_a, _ = await agent._file_back_thread("conv-aaa", db_session)
    await db_session.commit()  # single-commit pattern — test owns the commit

    article_b, _ = await agent._file_back_thread("conv-bbb", db_session)
    await db_session.commit()

    # Both articles exist with distinct slugs
    assert article_a.slug == "conv-aaa"
    assert article_b.slug == "conv-bbb"
    assert article_a.slug != article_b.slug
    assert article_a.id != article_b.id
    assert article_a.file_path != article_b.file_path

    # Both files exist on disk
    assert resolve_wiki_path(article_a.file_path).exists()
    assert resolve_wiki_path(article_b.file_path).exists()

    # The first article's content mentions the first answer
    content_a = resolve_wiki_path(article_a.file_path).read_text()
    assert "First answer" in content_a


# ---------------------------------------------------------------------------
# Streaming tests
# ---------------------------------------------------------------------------

_MOCK_QA_JSON = json.dumps(
    {
        "answer": "Streamed answer.",
        "confidence": "high",
        "sources": ["A"],
        "related_articles": [],
        "follow_up_questions": [],
    }
)


def _stream_session(content: str) -> StreamSession:
    """Build a StreamSession that yields content in 10-char chunks."""

    async def _gen():
        for i in range(0, len(content), 10):
            yield content[i : i + 10]
        session.result = CompletionResponse(
            content=content,
            provider_used=Provider.ANTHROPIC,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )

    session = StreamSession(_chunks=_gen())
    return session


async def test_answer_stream_no_context_yields_text_and_tuple(db_session, tmp_path) -> None:
    """answer_stream() with no wiki context yields canned answer text + (Query, Conversation)."""
    a = _agent(tmp_path)
    with patch.object(a, "_retrieve_context", AsyncMock(return_value=[])):
        items = [item async for item in a.answer_stream(QueryRequest(question="hello"), db_session)]

    # First item: the canned answer text string
    assert isinstance(items[0], str)
    assert "No relevant articles" in items[0]

    # Second item: the (Query, Conversation) tuple
    assert isinstance(items[1], tuple)
    query_record, conversation = items[1]
    assert isinstance(query_record, Query)
    assert isinstance(conversation, Conversation)
    assert query_record.confidence == "low"


async def test_answer_stream_with_context_yields_chunks_and_tuple(db_session, tmp_path) -> None:
    """answer_stream() with wiki context streams text chunks then yields (Query, Conversation)."""
    a = _agent(tmp_path)
    with patch.object(
        a,
        "_retrieve_context",
        AsyncMock(return_value=[{"title": "T", "content": "C"}]),
    ):
        a.router.stream_complete = AsyncMock(return_value=_stream_session(_MOCK_QA_JSON))

        items = [item async for item in a.answer_stream(QueryRequest(question="hello"), db_session)]

    # All items except the last should be strings (text chunks)
    text_chunks = [i for i in items if isinstance(i, str)]
    tuples = [i for i in items if isinstance(i, tuple)]
    assert len(text_chunks) > 0
    assert len(tuples) == 1

    # Concatenated text should equal the mock JSON
    assert "".join(text_chunks) == _MOCK_QA_JSON

    # The final tuple contains persisted Query and Conversation
    query_record, _conversation = tuples[0]
    assert query_record.answer == "Streamed answer."
    assert query_record.confidence == "high"


async def test_answer_stream_persists_query_after_completion(db_session, tmp_path) -> None:
    """answer_stream() persists a Query row after the stream finishes."""
    a = _agent(tmp_path)
    with patch.object(
        a,
        "_retrieve_context",
        AsyncMock(return_value=[{"title": "T", "content": "C"}]),
    ):
        a.router.stream_complete = AsyncMock(return_value=_stream_session(_MOCK_QA_JSON))

        items = [item async for item in a.answer_stream(QueryRequest(question="stream persist test"), db_session)]

    # Extract the final tuple
    final = next(i for i in items if isinstance(i, tuple))
    query_record, _conversation = final

    # The query was persisted with the streamed answer
    assert query_record.answer == "Streamed answer."
    assert query_record.confidence == "high"
    assert query_record.id is not None


async def test_answer_stream_raises_on_stream_failure(db_session, tmp_path) -> None:
    """answer_stream() raises when stream_complete raises (caller handles error)."""
    a = _agent(tmp_path)
    with patch.object(
        a,
        "_retrieve_context",
        AsyncMock(return_value=[{"title": "T", "content": "C"}]),
    ):
        a.router.stream_complete = AsyncMock(side_effect=RuntimeError("all providers dead"))

        with pytest.raises(RuntimeError, match="all providers dead"):
            async for _ in a.answer_stream(QueryRequest(question="will fail"), db_session):
                pass
