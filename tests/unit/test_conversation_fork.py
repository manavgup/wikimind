"""Tests for conversation branching (fork-on-edit) — issue #89."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from wikimind.models import (
    AskResponse,
    Conversation,
    ForkRequest,
    Query,
    QueryResult,
)
from wikimind.services.query import (
    QueryService,
    _count_forks,
    _materialize_thread,
)


async def _seed_conversation_with_turns(
    db_session, conv_id: str = "conv-parent", num_turns: int = 3
) -> tuple[Conversation, list[Query]]:
    """Seed a conversation with multiple turns."""
    conv = Conversation(
        id=conv_id,
        title="Parent conversation",
        created_at=datetime(2026, 4, 10, 10, 0, 0),
        updated_at=datetime(2026, 4, 10, 10, 5, 0),
    )
    db_session.add(conv)
    await db_session.flush()

    queries = []
    for i in range(num_turns):
        q = Query(
            id=f"q-{conv_id}-{i}",
            question=f"Question {i + 1}?",
            answer=f"Answer {i + 1}.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id=conv_id,
            turn_index=i,
            created_at=datetime(2026, 4, 10, 10, i, 0),
        )
        queries.append(q)
    db_session.add_all(queries)
    await db_session.commit()
    return conv, queries


@pytest.mark.asyncio
class TestForkConversation:
    async def test_fork_creates_child_conversation(self, db_session):
        """Forking creates a new conversation with parent_conversation_id set."""
        parent, _queries = await _seed_conversation_with_turns(db_session)

        service = QueryService()
        fork_request = ForkRequest(turn_index=1, new_question="Different question?")

        mock_result = QueryResult(
            answer="Forked answer.",
            confidence="high",
            sources=[],
            related_articles=[],
        )

        with patch.object(service._qa_agent, "answer", new_callable=AsyncMock) as mock_answer:
            # Make the mock return a Query and Conversation
            async def _fake_answer(request, session):
                # Find the fork conversation that was just created
                result = await session.execute(
                    select(Conversation).where(Conversation.parent_conversation_id == parent.id)
                )
                fork_conv = result.scalars().first()
                assert fork_conv is not None

                q = Query(
                    question=request.question,
                    answer=mock_result.answer,
                    confidence=mock_result.confidence,
                    source_article_ids=json.dumps(mock_result.sources),
                    related_article_ids=json.dumps(mock_result.related_articles),
                    conversation_id=fork_conv.id,
                    turn_index=0,
                )
                session.add(q)
                await session.commit()
                await session.refresh(q)
                await session.refresh(fork_conv)
                return q, fork_conv

            mock_answer.side_effect = _fake_answer

            result = await service.fork_conversation(parent.id, fork_request, db_session)

        assert isinstance(result, AskResponse)
        assert result.conversation.parent_conversation_id == parent.id
        assert result.conversation.forked_at_turn_index == 1
        assert result.query.question == "Different question?"

    async def test_fork_404_for_nonexistent_parent(self, db_session):
        """Forking a nonexistent conversation raises 404."""
        service = QueryService()
        fork_request = ForkRequest(turn_index=0, new_question="Any question?")

        with pytest.raises(HTTPException) as exc_info:
            await service.fork_conversation("nonexistent-id", fork_request, db_session)

        assert exc_info.value.status_code == 404

    async def test_fork_400_for_negative_turn_index(self, db_session):
        """Forking with negative turn_index raises 400."""
        parent, _queries = await _seed_conversation_with_turns(db_session)
        service = QueryService()
        fork_request = ForkRequest(turn_index=-1, new_question="Bad index?")

        with pytest.raises(HTTPException) as exc_info:
            await service.fork_conversation(parent.id, fork_request, db_session)

        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
class TestCountForks:
    async def test_count_forks_zero_for_no_children(self, db_session):
        """A conversation with no forks returns count 0."""
        parent, _ = await _seed_conversation_with_turns(db_session)
        count = await _count_forks(parent.id, db_session)
        assert count == 0

    async def test_count_forks_with_children(self, db_session):
        """A conversation with forks returns the correct count."""
        parent, _ = await _seed_conversation_with_turns(db_session)

        # Create two forks
        fork1 = Conversation(
            id="fork-1",
            title="Fork 1",
            parent_conversation_id=parent.id,
            forked_at_turn_index=1,
        )
        fork2 = Conversation(
            id="fork-2",
            title="Fork 2",
            parent_conversation_id=parent.id,
            forked_at_turn_index=2,
        )
        db_session.add_all([fork1, fork2])
        await db_session.commit()

        count = await _count_forks(parent.id, db_session)
        assert count == 2


@pytest.mark.asyncio
class TestMaterializeThread:
    async def test_non_forked_conversation_returns_own_turns(self, db_session):
        """A non-forked conversation returns only its own turns."""
        conv, _queries = await _seed_conversation_with_turns(db_session)

        result = await _materialize_thread(conv, db_session)

        assert len(result) == 3
        assert [q.turn_index for q in result] == [0, 1, 2]

    async def test_forked_conversation_includes_ancestor_turns(self, db_session):
        """A forked conversation includes parent turns before the fork point."""
        _parent, _parent_queries = await _seed_conversation_with_turns(db_session, conv_id="parent-conv", num_turns=3)

        # Create a fork at turn_index=2 (shares turns 0, 1 from parent)
        fork_conv = Conversation(
            id="fork-conv",
            title="Forked conversation",
            parent_conversation_id="parent-conv",
            forked_at_turn_index=2,
        )
        db_session.add(fork_conv)
        await db_session.flush()

        # Add the fork's own turn
        fork_query = Query(
            id="q-fork-0",
            question="Forked question?",
            answer="Forked answer.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="fork-conv",
            turn_index=0,
        )
        db_session.add(fork_query)
        await db_session.commit()

        result = await _materialize_thread(fork_conv, db_session)

        # Should have parent turns 0,1 + fork turn 0 = 3 total
        assert len(result) == 3
        assert result[0].question == "Question 1?"
        assert result[1].question == "Question 2?"
        assert result[2].question == "Forked question?"

    async def test_deep_fork_chain_materializes_all_ancestors(self, db_session):
        """A fork-of-a-fork materializes the full ancestor chain."""
        # Grandparent: 3 turns
        _grandparent, _ = await _seed_conversation_with_turns(db_session, conv_id="grandparent", num_turns=3)

        # Parent fork at turn 2 (shares turns 0,1 from grandparent)
        parent_fork = Conversation(
            id="parent-fork",
            title="Parent fork",
            parent_conversation_id="grandparent",
            forked_at_turn_index=2,
        )
        db_session.add(parent_fork)
        await db_session.flush()

        parent_fork_query = Query(
            id="q-pf-0",
            question="Parent fork Q?",
            answer="Parent fork A.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="parent-fork",
            turn_index=0,
        )
        parent_fork_query2 = Query(
            id="q-pf-1",
            question="Parent fork Q2?",
            answer="Parent fork A2.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="parent-fork",
            turn_index=1,
        )
        db_session.add_all([parent_fork_query, parent_fork_query2])
        await db_session.flush()

        # Child fork at turn 1 of parent-fork (shares turn 0 from parent-fork)
        child_fork = Conversation(
            id="child-fork",
            title="Child fork",
            parent_conversation_id="parent-fork",
            forked_at_turn_index=1,
        )
        db_session.add(child_fork)
        await db_session.flush()

        child_fork_query = Query(
            id="q-cf-0",
            question="Child fork Q?",
            answer="Child fork A.",
            confidence="high",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="child-fork",
            turn_index=0,
        )
        db_session.add(child_fork_query)
        await db_session.commit()

        result = await _materialize_thread(child_fork, db_session)

        # grandparent turns 0,1 + parent-fork turn 0 + child-fork turn 0 = 4
        assert len(result) == 4
        assert result[0].question == "Question 1?"  # grandparent turn 0
        assert result[1].question == "Question 2?"  # grandparent turn 1
        assert result[2].question == "Parent fork Q?"  # parent-fork turn 0
        assert result[3].question == "Child fork Q?"  # child-fork turn 0


@pytest.mark.asyncio
class TestGetConversationWithFork:
    async def test_get_forked_conversation_materializes_thread(self, db_session):
        """get_conversation on a fork returns the full materialized thread."""
        _parent, _ = await _seed_conversation_with_turns(db_session, conv_id="parent-gc", num_turns=3)

        fork_conv = Conversation(
            id="fork-gc",
            title="Fork for get_conversation",
            parent_conversation_id="parent-gc",
            forked_at_turn_index=2,
        )
        db_session.add(fork_conv)
        await db_session.flush()

        fork_query = Query(
            id="q-fgc-0",
            question="Forked Q?",
            answer="Forked A.",
            confidence="medium",
            source_article_ids=json.dumps([]),
            related_article_ids=json.dumps([]),
            conversation_id="fork-gc",
            turn_index=0,
        )
        db_session.add(fork_query)
        await db_session.commit()

        service = QueryService()
        detail = await service.get_conversation("fork-gc", db_session)

        # Should have parent turns 0,1 + fork turn 0 = 3
        assert len(detail.queries) == 3
        assert detail.conversation.parent_conversation_id == "parent-gc"
        assert detail.conversation.forked_at_turn_index == 2

    async def test_get_parent_includes_fork_count(self, db_session):
        """get_conversation on a parent returns fork_count."""
        _parent, _ = await _seed_conversation_with_turns(db_session, conv_id="parent-fc", num_turns=2)

        fork_conv = Conversation(
            id="fork-fc",
            title="Fork for count",
            parent_conversation_id="parent-fc",
            forked_at_turn_index=1,
        )
        db_session.add(fork_conv)
        await db_session.commit()

        service = QueryService()
        detail = await service.get_conversation("parent-fc", db_session)

        assert detail.conversation.fork_count == 1
