"""Tests for the QueryService citation chain resolution and conversation export."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from wikimind.engine.conversation_serializer import serialize_conversation_to_markdown
from wikimind.models import (
    Article,
    Conversation,
    FileBackSelectionRequest,
    Query,
    QueryRequest,
    Source,
    SourceType,
    TurnSelection,
)
from wikimind.services.query import QueryService, _build_citations, _sanitize_filename


async def _seed(db_session, tmp_path: Path) -> tuple[Query, Article, Source]:
    """Persist a Source, an Article that references it, and a Query that cites the article."""
    file_path = tmp_path / "cited.md"
    file_path.write_text("# Cited\n\nClaim about IBM.", encoding="utf-8")

    source = Source(
        source_type=SourceType.PDF,
        title="20260312_MikeO_AILabsGeneralTalk",
        source_url=None,
    )
    db_session.add(source)
    await db_session.flush()

    article = Article(
        slug="ibm-agentic-ai-labs",
        title="IBM Agentic AI Labs",
        file_path=str(file_path),
        summary="A summary",
        source_ids=json.dumps([source.id]),
    )
    db_session.add(article)
    await db_session.flush()

    query = Query(
        question="What is IBM Agentic AI Labs?",
        answer="It is a research lab.",
        confidence="high",
        source_article_ids=json.dumps([article.title]),
        related_article_ids=json.dumps([]),
    )
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    return query, article, source


@pytest.mark.asyncio
class TestQueryCitations:
    async def test_build_citations_resolves_full_chain(self, db_session, tmp_path):
        query, article, source = await _seed(db_session, tmp_path)

        citations = await _build_citations(query, db_session)

        assert len(citations) == 1
        citation = citations[0]
        assert citation.article.slug == article.slug
        assert citation.article.title == article.title
        assert len(citation.sources) == 1
        assert citation.sources[0].id == source.id
        assert citation.sources[0].source_type == SourceType.PDF
        assert citation.sources[0].title == "20260312_MikeO_AILabsGeneralTalk"

    async def test_build_citations_skips_unknown_article_titles(self, db_session, tmp_path):
        """A Query that cites a title with no matching article yields no citations."""
        query = Query(
            question="What about Foo?",
            answer="Unknown.",
            confidence="low",
            source_article_ids=json.dumps(["No Such Article"]),
            related_article_ids=json.dumps([]),
        )
        db_session.add(query)
        await db_session.commit()

        citations = await _build_citations(query, db_session)
        assert citations == []

    async def test_build_citations_handles_empty_source_ids(self, db_session, tmp_path):
        """An article with no sources still appears in the citation list, with empty sources."""
        file_path = tmp_path / "empty-sources.md"
        file_path.write_text("# Empty", encoding="utf-8")
        article = Article(
            slug="empty-sources",
            title="Empty Sources Article",
            file_path=str(file_path),
            source_ids=None,
        )
        db_session.add(article)
        await db_session.flush()

        query = Query(
            question="Empty?",
            answer="Yes.",
            confidence="medium",
            source_article_ids=json.dumps([article.title]),
            related_article_ids=json.dumps([]),
        )
        db_session.add(query)
        await db_session.commit()

        citations = await _build_citations(query, db_session)
        assert len(citations) == 1
        assert citations[0].article.title == article.title
        assert citations[0].sources == []


async def _seed_conversation(db_session) -> tuple[Conversation, list[Query]]:
    """Persist a Conversation with two Q&A turns for export tests."""
    conv = Conversation(
        id="conv-export-1",
        title="Export Test Conversation",
        created_at=datetime(2026, 4, 8, 12, 0, 0),
        updated_at=datetime(2026, 4, 8, 12, 5, 0),
    )
    db_session.add(conv)
    await db_session.flush()

    q1 = Query(
        id="q-export-1",
        question="What is X?",
        answer="X is a thing.",
        confidence="high",
        source_article_ids=json.dumps(["Article One"]),
        related_article_ids=json.dumps([]),
        conversation_id="conv-export-1",
        turn_index=0,
        created_at=datetime(2026, 4, 8, 12, 0, 0),
    )
    q2 = Query(
        id="q-export-2",
        question="How does X work?",
        answer="X works by Y.",
        confidence="medium",
        source_article_ids=json.dumps([]),
        related_article_ids=json.dumps([]),
        conversation_id="conv-export-1",
        turn_index=1,
        created_at=datetime(2026, 4, 8, 12, 1, 0),
    )
    db_session.add_all([q1, q2])
    await db_session.commit()
    return conv, [q1, q2]


@pytest.mark.asyncio
class TestExportConversation:
    async def test_export_returns_markdown_content(self, db_session):
        """Export returns a Response with text/markdown content type."""
        await _seed_conversation(db_session)
        service = QueryService()

        response = await service.export_conversation("conv-export-1", db_session)

        assert response.media_type == "text/markdown"
        body = response.body.decode()
        assert "# Export Test Conversation" in body
        assert "## Q1: What is X?" in body
        assert "## Q2: How does X work?" in body

    async def test_export_has_content_disposition_header(self, db_session):
        """Export response includes a Content-Disposition header for download."""
        await _seed_conversation(db_session)
        service = QueryService()

        response = await service.export_conversation("conv-export-1", db_session)

        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]
        assert ".md" in response.headers["content-disposition"]

    async def test_export_is_read_only(self, db_session):
        """Export does not modify the conversation or query rows."""
        conv, queries = await _seed_conversation(db_session)
        service = QueryService()

        # Capture state before export
        conv_before_title = conv.title
        conv_before_filed = conv.filed_article_id
        q_before_filed = [q.filed_back for q in queries]

        await service.export_conversation("conv-export-1", db_session)

        # Refresh from DB to check no writes happened
        await db_session.refresh(conv)
        for q in queries:
            await db_session.refresh(q)

        assert conv.title == conv_before_title
        assert conv.filed_article_id == conv_before_filed
        assert [q.filed_back for q in queries] == q_before_filed

    async def test_export_404_for_nonexistent_conversation(self, db_session):
        """Export raises 404 for a conversation that doesn't exist."""
        service = QueryService()

        with pytest.raises(HTTPException) as exc_info:
            await service.export_conversation("nonexistent-id", db_session)

        assert exc_info.value.status_code == 404

    async def test_export_matches_serializer_output(self, db_session):
        """Exported markdown is byte-identical to calling the serializer directly."""
        conv, queries = await _seed_conversation(db_session)
        service = QueryService()

        response = await service.export_conversation("conv-export-1", db_session)
        exported = response.body.decode()

        expected = serialize_conversation_to_markdown(conv, queries)
        assert exported == expected


class TestSanitizeFilename:
    def test_basic_title(self):
        assert _sanitize_filename("Hello World") == "Hello World"

    def test_special_characters_replaced(self):
        assert _sanitize_filename('What is "AI"?') == "What is -AI"

    def test_collapses_multiple_hyphens(self):
        assert _sanitize_filename("a!!!b") == "a-b"

    def test_strips_leading_trailing_hyphens(self):
        assert _sanitize_filename("!!!Hello!!!") == "Hello"

    def test_empty_title_returns_fallback(self):
        assert _sanitize_filename("") == "conversation"

    def test_all_special_returns_fallback(self):
        assert _sanitize_filename("!@#$%") == "conversation"

    def test_preserves_hyphens_and_underscores(self):
        assert _sanitize_filename("my-conversation_v2") == "my-conversation_v2"


# ---------------------------------------------------------------------------
# ask_stream tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAskStream:
    async def test_ask_stream_emits_chunk_and_done_events(self, db_session):
        """ask_stream() converts agent's str/tuple yields into SSE events."""
        # Seed a conversation + query so _build_citations has something to work with
        conv = Conversation(
            id="conv-stream-1",
            title="stream test",
        )
        db_session.add(conv)
        q = Query(
            id="q-stream-1",
            question="test",
            answer="hello",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-stream-1",
            turn_index=0,
        )
        db_session.add(q)
        await db_session.commit()
        await db_session.refresh(q)
        await db_session.refresh(conv)

        service = QueryService()

        async def _fake_stream(request, session):
            yield "hello "
            yield "world"
            yield (q, conv)

        with patch.object(service._qa_agent, "answer_stream", side_effect=_fake_stream):
            events = [event async for event in service.ask_stream(QueryRequest(question="test"), db_session)]

        # Should have 2 chunk events + 1 done event
        chunk_events = [e for e in events if e.startswith("event: chunk\n")]
        done_events = [e for e in events if e.startswith("event: done\n")]
        assert len(chunk_events) == 2
        assert len(done_events) == 1

        # Check chunk content
        first_chunk_data = json.loads(chunk_events[0].split("data: ", 1)[1].strip())
        assert first_chunk_data["text"] == "hello "

        # Check done event has AskResponse shape
        done_data = json.loads(done_events[0].split("data: ", 1)[1].strip())
        assert "query" in done_data
        assert "conversation" in done_data

    async def test_ask_stream_emits_error_on_failure(self, db_session):
        """ask_stream() emits an error event when the agent raises."""
        service = QueryService()

        async def _failing_stream(request, session):
            raise RuntimeError("provider dead")
            yield  # make it a generator  # pragma: no cover

        with patch.object(service._qa_agent, "answer_stream", side_effect=_failing_stream):
            events = [event async for event in service.ask_stream(QueryRequest(question="fail"), db_session)]

        error_events = [e for e in events if e.startswith("event: error\n")]
        assert len(error_events) == 1
        error_data = json.loads(error_events[0].split("data: ", 1)[1].strip())
        assert error_data["code"] == "stream_failed"


# ---------------------------------------------------------------------------
# file_back_selection tests
# ---------------------------------------------------------------------------


async def _seed_two_conversations(db_session) -> tuple[Conversation, Conversation, list[Query]]:
    """Seed two conversations with multiple turns each for file-back selection tests."""
    conv1 = Conversation(
        id="conv-sel-1",
        title="First Thread",
        created_at=datetime(2026, 4, 8, 12, 0, 0),
        updated_at=datetime(2026, 4, 8, 12, 5, 0),
    )
    conv2 = Conversation(
        id="conv-sel-2",
        title="Second Thread",
        created_at=datetime(2026, 4, 9, 10, 0, 0),
        updated_at=datetime(2026, 4, 9, 10, 5, 0),
    )
    db_session.add_all([conv1, conv2])
    await db_session.flush()

    queries = [
        Query(
            id="q-sel-1-0",
            question="Q1 from thread 1",
            answer="Answer 1-0.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-sel-1",
            turn_index=0,
        ),
        Query(
            id="q-sel-1-1",
            question="Q2 from thread 1",
            answer="Answer 1-1.",
            confidence="medium",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-sel-1",
            turn_index=1,
        ),
        Query(
            id="q-sel-1-2",
            question="Q3 from thread 1",
            answer="Answer 1-2.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-sel-1",
            turn_index=2,
        ),
        Query(
            id="q-sel-2-0",
            question="Q1 from thread 2",
            answer="Answer 2-0.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-sel-2",
            turn_index=0,
        ),
        Query(
            id="q-sel-2-1",
            question="Q2 from thread 2",
            answer="Answer 2-1.",
            confidence="medium",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="conv-sel-2",
            turn_index=1,
        ),
    ]
    db_session.add_all(queries)
    await db_session.commit()
    return conv1, conv2, queries


@pytest.mark.asyncio
class TestFileBackSelection:
    async def test_partial_save_selected_turns(self, db_session):
        """Partial save: only selected turns from one conversation are filed."""
        await _seed_two_conversations(db_session)
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="conv-sel-1", turn_indices=[0, 2]),
            ],
        )
        result = await service.file_back_selection(request, db_session)

        assert "article" in result
        article_data = result["article"]
        assert article_data["title"] == "First Thread"  # defaults to first conv title

        # Verify the article was created on disk
        article = await db_session.get(Article, article_data["id"])
        assert article is not None
        content = Path(article.file_path).read_text(encoding="utf-8")
        assert "## Q1: Q1 from thread 1" in content
        assert "## Q2: Q3 from thread 1" in content
        # Q2 from thread 1 (turn_index=1) should NOT be present
        assert "Q2 from thread 1" not in content

    async def test_multi_thread_merge(self, db_session):
        """Multi-thread merge: turns from two conversations combined into one article."""
        await _seed_two_conversations(db_session)
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="conv-sel-1", turn_indices=[0]),
                TurnSelection(conversation_id="conv-sel-2", turn_indices=[0, 1]),
            ],
            title="Merged Research",
        )
        result = await service.file_back_selection(request, db_session)

        article_data = result["article"]
        assert article_data["title"] == "Merged Research"

        article = await db_session.get(Article, article_data["id"])
        content = Path(article.file_path).read_text(encoding="utf-8")
        assert "# Merged Research" in content
        assert "## Q1: Q1 from thread 1" in content
        assert "## Q2: Q1 from thread 2" in content
        assert "## Q3: Q2 from thread 2" in content

    async def test_marks_turns_as_filed_back(self, db_session):
        """Selected turns are marked filed_back=True with the article's id."""
        await _seed_two_conversations(db_session)
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="conv-sel-1", turn_indices=[0, 1]),
            ],
        )
        result = await service.file_back_selection(request, db_session)
        article_id = result["article"]["id"]

        # Refresh the selected queries
        res = await db_session.execute(select(Query).where(Query.conversation_id == "conv-sel-1"))
        queries = {q.turn_index: q for q in res.scalars().all()}

        assert queries[0].filed_back is True
        assert queries[0].filed_article_id == article_id
        assert queries[1].filed_back is True
        assert queries[1].filed_article_id == article_id
        # Turn 2 was not selected — should remain unfiled
        assert queries[2].filed_back is False

    async def test_404_for_nonexistent_conversation(self, db_session):
        """Raises 404 when a selection references a nonexistent conversation."""
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="nonexistent", turn_indices=[0]),
            ],
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.file_back_selection(request, db_session)
        assert exc_info.value.status_code == 404

    async def test_400_for_empty_selections(self, db_session):
        """Raises 400 when the selections list is empty."""
        service = QueryService()

        request = FileBackSelectionRequest(selections=[])
        with pytest.raises(HTTPException) as exc_info:
            await service.file_back_selection(request, db_session)
        assert exc_info.value.status_code == 400

    async def test_400_for_missing_turn_indices(self, db_session):
        """Raises 400 when requested turn indices don't exist."""
        await _seed_two_conversations(db_session)
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="conv-sel-1", turn_indices=[0, 99]),
            ],
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.file_back_selection(request, db_session)
        assert exc_info.value.status_code == 400
        assert "99" in str(exc_info.value.detail)

    async def test_custom_title_overrides_default(self, db_session):
        """Custom title appears in the article and file content."""
        await _seed_two_conversations(db_session)
        service = QueryService()

        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(conversation_id="conv-sel-1", turn_indices=[0]),
            ],
            title="My Custom Title",
        )
        result = await service.file_back_selection(request, db_session)

        assert result["article"]["title"] == "My Custom Title"
        article = await db_session.get(Article, result["article"]["id"])
        content = Path(article.file_path).read_text(encoding="utf-8")
        assert "# My Custom Title" in content
