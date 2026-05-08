"""Tests for the conversation crystallization service and API endpoint."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.errors import NotFoundError, QueryError
from wikimind.models import (
    Article,
    CompletionResponse,
    Conversation,
    PageType,
    Provider,
    Query,
)
from wikimind.services.crystallization import crystallize_conversation


async def _seed_conversation(
    db_session,
    conv_id: str = "conv-crystal-1",
    user_id: str = TEST_USER_ID,
    turn_count: int = 3,
) -> tuple[Conversation, list[Query]]:
    """Seed a conversation with multiple Q&A turns for crystallization tests."""
    conv = Conversation(
        id=conv_id,
        title="Research on LLM Agents",
        created_at=datetime(2026, 5, 1, 10, 0, 0),
        updated_at=datetime(2026, 5, 1, 10, 15, 0),
        user_id=user_id,
    )
    db_session.add(conv)
    await db_session.flush()

    queries = []
    qa_pairs = [
        ("What are LLM agents?", "LLM agents are autonomous systems that use language models."),
        ("How do they handle memory?", "They use context windows and external memory stores."),
        ("What are the limitations?", "Key limitations include hallucination and cost."),
    ]
    for i in range(min(turn_count, len(qa_pairs))):
        q = Query(
            id=f"q-crystal-{conv_id}-{i}",
            question=qa_pairs[i][0],
            answer=qa_pairs[i][1],
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id=conv_id,
            turn_index=i,
            user_id=user_id,
        )
        queries.append(q)
    db_session.add_all(queries)
    await db_session.commit()
    return conv, queries


_MOCK_CRYSTALLIZE_RESPONSE = json.dumps(
    {
        "title": "LLM Agents: Capabilities and Limitations",
        "research_question": "What are LLM agents and what are their limitations?",
        "key_findings": [
            "LLM agents are autonomous systems powered by language models",
            "They rely on context windows and external memory for state",
            "Key limitations include hallucination and operational cost",
        ],
        "explored_but_inconclusive": [
            "Long-term memory architectures remain an open question",
        ],
        "sources_consulted": [
            "Direct conversation synthesis",
        ],
        "article_body": (
            "## Overview\n\n"
            "LLM agents represent a new paradigm in AI systems. "
            "They combine large language models with tool use and planning capabilities "
            "to accomplish complex tasks autonomously.\n\n"
            "## Memory and State\n\n"
            "These agents handle memory through context windows and external stores. "
            "The context window provides short-term working memory, while vector databases "
            "and other persistence layers provide long-term recall.\n\n"
            "## Limitations\n\n"
            "Despite their capabilities, LLM agents face significant challenges. "
            "Hallucination remains a core issue where agents generate plausible but "
            "incorrect information. Operational costs can be substantial due to the "
            "number of LLM calls required for complex reasoning chains."
        ),
    }
)


def _mock_completion_response() -> CompletionResponse:
    """Build a mock CompletionResponse for crystallization."""
    return CompletionResponse(
        content=_MOCK_CRYSTALLIZE_RESPONSE,
        provider_used=Provider.MOCK,
        model_used="mock-model",
        input_tokens=500,
        output_tokens=300,
        cost_usd=0.01,
        latency_ms=100,
    )


@pytest.mark.asyncio
class TestCrystallizeConversation:
    async def test_crystallize_creates_synthesis_article(self, db_session):
        """Crystallization creates an Article with page_type=synthesis."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            result = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)

        assert result.title == "LLM Agents: Capabilities and Limitations"
        assert result.turns_distilled == 3
        assert result.article_id is not None
        assert result.article_slug is not None

        # Verify article in DB
        article = await db_session.get(Article, result.article_id)
        assert article is not None
        assert article.page_type == PageType.SYNTHESIS
        assert article.user_id == TEST_USER_ID

    async def test_crystallize_writes_markdown_to_disk(self, db_session, tmp_path):
        """Crystallization writes a markdown file under the synthesis directory."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            result = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)

        article = await db_session.get(Article, result.article_id)
        assert article.file_path.startswith("synthesis/")

    async def test_crystallize_article_metadata(self, db_session):
        """The created article has correct metadata fields."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            result = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)

        article = await db_session.get(Article, result.article_id)
        assert article.summary is not None
        assert article.page_type == PageType.SYNTHESIS

    async def test_crystallize_404_nonexistent_conversation(self, db_session):
        """Raises NotFoundError for a conversation that does not exist."""
        with pytest.raises(NotFoundError) as exc_info:
            await crystallize_conversation("nonexistent-id", db_session, user_id=TEST_USER_ID)
        assert exc_info.value.status_code == 404

    async def test_crystallize_404_wrong_user(self, db_session):
        """Raises NotFoundError when conversation belongs to a different user."""
        await _seed_conversation(db_session, user_id="user-a")

        with pytest.raises(NotFoundError) as exc_info:
            await crystallize_conversation("conv-crystal-1", db_session, user_id="user-b")
        assert exc_info.value.status_code == 404

    async def test_crystallize_empty_conversation(self, db_session):
        """Raises QueryError when conversation has no turns."""
        conv = Conversation(
            id="conv-empty",
            title="Empty Conversation",
            user_id=TEST_USER_ID,
        )
        db_session.add(conv)
        await db_session.commit()

        with pytest.raises(QueryError) as exc_info:
            await crystallize_conversation("conv-empty", db_session, user_id=TEST_USER_ID)
        assert exc_info.value.status_code == 400

    async def test_crystallize_sets_crystallized_article_id(self, db_session):
        """Crystallization sets conversation.crystallized_article_id for idempotency."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            result = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)

        conv = await db_session.get(Conversation, "conv-crystal-1")
        assert conv.crystallized_article_id == result.article_id

    async def test_crystallize_idempotent(self, db_session):
        """Calling crystallize twice returns the same article without a second LLM call."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            result1 = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)
            result2 = await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)

        assert result1.article_id == result2.article_id
        assert result1.article_slug == result2.article_slug
        # LLM should only be called once — the second call is a no-op
        assert mock_router.complete.await_count == 1

    async def test_crystallize_llm_failure(self, db_session):
        """Raises QueryError when LLM returns unparseable response."""
        await _seed_conversation(db_session)

        mock_router = MagicMock()
        bad_response = CompletionResponse(
            content="not json at all",
            provider_used=Provider.MOCK,
            model_used="mock-model",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            latency_ms=50,
        )
        mock_router.complete = AsyncMock(return_value=bad_response)
        mock_router.parse_json_response.side_effect = ValueError("bad json")

        with (
            patch(
                "wikimind.services.crystallization.get_llm_router",
                return_value=mock_router,
            ),
            pytest.raises(QueryError),
        ):
            await crystallize_conversation("conv-crystal-1", db_session, user_id=TEST_USER_ID)


@pytest.mark.asyncio
class TestCrystallizeEndpoint:
    async def test_crystallize_endpoint_returns_200(self, client, db_session):
        """POST /query/conversations/{id}/crystallize returns 200 with article data."""
        await _seed_conversation(db_session, conv_id="conv-ep-1", user_id=ANONYMOUS_USER_ID)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_completion_response())
        mock_router.parse_json_response.return_value = json.loads(_MOCK_CRYSTALLIZE_RESPONSE)

        with patch(
            "wikimind.services.crystallization.get_llm_router",
            return_value=mock_router,
        ):
            resp = await client.post("/query/conversations/conv-ep-1/crystallize")

        assert resp.status_code == 200
        data = resp.json()
        assert "article_id" in data
        assert "article_slug" in data
        assert "title" in data
        assert data["turns_distilled"] == 3

    async def test_crystallize_endpoint_404_nonexistent(self, client):
        """POST /query/conversations/{id}/crystallize returns 404 for missing conversation."""
        resp = await client.post("/query/conversations/nonexistent/crystallize")
        assert resp.status_code == 404
