"""Tests for user_id scoping in service-layer queries, file paths, and ChromaDB."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.models import (
    Article,
    ArticleConcept,
    CompletionResponse,
    Concept,
    Conversation,
    FileBackSelectionRequest,
    Provider,
    Query,
    TurnSelection,
)
from wikimind.services.activity_log import append_log_entry
from wikimind.services.embedding import _SEARCH_AVAILABLE
from wikimind.services.query import QueryService
from wikimind.services.taxonomy import (
    rebuild_taxonomy,
    update_article_counts,
    upsert_concepts,
)
from wikimind.services.wiki_index import (
    generate_meta_health_page,
    regenerate_index_md,
)
from wikimind.storage import resolve_wiki_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Issue 3: Service-layer query scoping by user_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpsertConceptsUserScoping:
    """Concepts should be scoped by user_id."""

    async def test_creates_concept_with_user_id(self, db_session: AsyncSession) -> None:
        concepts = await upsert_concepts(["ML"], db_session, user_id="alice")
        assert len(concepts) == 1
        assert concepts[0].user_id == "alice"

    async def test_separate_concepts_per_user(self, db_session: AsyncSession) -> None:
        alice = await upsert_concepts(["ML"], db_session, user_id="alice")
        bob = await upsert_concepts(["ML"], db_session, user_id="bob")
        # Same name, different users — separate rows
        assert alice[0].id != bob[0].id

    async def test_idempotent_within_same_user(self, db_session: AsyncSession) -> None:
        first = await upsert_concepts(["ML"], db_session, user_id="alice")
        second = await upsert_concepts(["ML"], db_session, user_id="alice")
        assert first[0].id == second[0].id


@pytest.mark.asyncio
class TestUpdateArticleCountsUserScoping:
    """Article counts should only include the specified user's articles."""

    async def test_counts_only_own_articles(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        # Create concepts for each user
        await upsert_concepts(["ML"], db_session, user_id="alice")
        await upsert_concepts(["ML"], db_session, user_id="bob")

        # Create articles owned by different users
        fp1 = tmp_path / "alice.md"
        fp1.write_text("# Alice ML", encoding="utf-8")
        art_alice = Article(
            slug="alice-ml",
            title="Alice ML",
            file_path=str(fp1),
            user_id="alice",
        )
        fp2 = tmp_path / "bob.md"
        fp2.write_text("# Bob ML", encoding="utf-8")
        art_bob = Article(
            slug="bob-ml",
            title="Bob ML",
            file_path=str(fp2),
            user_id="bob",
        )
        db_session.add_all([art_alice, art_bob])
        await db_session.commit()
        await db_session.refresh(art_alice)
        await db_session.refresh(art_bob)

        db_session.add(ArticleConcept(article_id=art_alice.id, concept_name="ml"))
        db_session.add(ArticleConcept(article_id=art_bob.id, concept_name="ml"))
        await db_session.commit()

        # Update counts for alice only
        await update_article_counts(db_session, user_id="alice")

        result = await db_session.execute(select(Concept).where(Concept.user_id == "alice"))
        alice_concept = result.scalar_one()
        assert alice_concept.article_count == 1


@pytest.mark.asyncio
class TestRebuildTaxonomyUserScoping:
    """Taxonomy rebuild should only process the specified user's concepts."""

    async def test_rebuild_scopes_to_user(self, db_session: AsyncSession) -> None:
        await upsert_concepts(["ml", "nlp"], db_session, user_id="alice")
        await upsert_concepts(["biology"], db_session, user_id="bob")

        llm_response = json.dumps(
            [
                {"name": "ml", "parent": None},
                {"name": "nlp", "parent": "ml"},
            ]
        )
        fake_resp = CompletionResponse(
            content=llm_response,
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=fake_resp)
        mock_router.parse_json_response = lambda r: json.loads(r.content)

        with patch(
            "wikimind.services.taxonomy.get_llm_router",
            return_value=mock_router,
        ):
            await rebuild_taxonomy(db_session, user_id="alice")

        # Bob's concept should be untouched
        bob_result = await db_session.execute(select(Concept).where(Concept.user_id == "bob"))
        bob_concept = bob_result.scalar_one()
        assert bob_concept.parent_id is None
        assert bob_concept.name == "biology"


@pytest.mark.asyncio
class TestRegenerateIndexUserScoping:
    """Index regeneration should only include the specified user's articles."""

    async def test_index_filters_by_user(self, db_session: AsyncSession) -> None:
        a_alice = Article(
            slug="alice-art",
            title="Alice Article",
            file_path="/wiki/alice-art.md",
            user_id="alice",
        )
        a_bob = Article(
            slug="bob-art",
            title="Bob Article",
            file_path="/wiki/bob-art.md",
            user_id="bob",
        )
        db_session.add_all([a_alice, a_bob])
        await db_session.commit()

        await regenerate_index_md(db_session, user_id="alice")

        settings = get_settings()
        index_path = Path(settings.data_dir) / "wiki" / "alice" / "index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "[[alice-art]]" in content
        assert "[[bob-art]]" not in content

    async def test_index_path_scoped_by_user(self, db_session: AsyncSession) -> None:
        """Index file should be written under wiki/{user_id}/."""
        await regenerate_index_md(db_session, user_id="user123")

        settings = get_settings()
        index_path = Path(settings.data_dir) / "wiki" / "user123" / "index.md"
        assert index_path.exists()

    async def test_index_scoped_to_test_user(self, db_session: AsyncSession) -> None:
        """user_id='test-user' scopes index to wiki/test-user/."""
        await regenerate_index_md(db_session, user_id=TEST_USER_ID)

        settings = get_settings()
        index_path = Path(settings.data_dir) / "wiki" / TEST_USER_ID / "index.md"
        assert index_path.exists()


@pytest.mark.asyncio
class TestHealthPageUserScoping:
    """Health page should scope path and queries by user_id."""

    async def test_health_path_scoped_by_user(self, db_session: AsyncSession) -> None:
        rel = await generate_meta_health_page(db_session, user_id="alice")
        assert rel == "meta/wiki-health.md"

        settings = get_settings()
        health_path = Path(settings.data_dir) / "wiki" / "alice" / "meta" / "wiki-health.md"
        assert health_path.exists()

    async def test_health_filters_articles_by_user(
        self,
        db_session: AsyncSession,
    ) -> None:
        a_alice = Article(
            slug="alice-art",
            title="Alice Article",
            file_path="/wiki/alice-art.md",
            user_id="alice",
        )
        a_bob = Article(
            slug="bob-art",
            title="Bob Article",
            file_path="/wiki/bob-art.md",
            user_id="bob",
        )
        db_session.add_all([a_alice, a_bob])
        await db_session.commit()

        await generate_meta_health_page(db_session, user_id="alice")

        settings = get_settings()
        health_path = Path(settings.data_dir) / "wiki" / "alice" / "meta" / "wiki-health.md"
        content = health_path.read_text(encoding="utf-8")
        # Total should be 1 (only Alice's article)
        assert "| **Total** | **1** |" in content


# ---------------------------------------------------------------------------
# Issue 4: File system path scoping by user_id
# ---------------------------------------------------------------------------


class TestActivityLogPathScoping:
    """Activity log path should include user_id when provided."""

    def test_log_path_includes_user_id(self, tmp_path: Path) -> None:
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("ingest", "Test Source", user_id="alice")

        log_path = tmp_path / "wiki" / "alice" / "log.md"
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "ingest | Test Source" in content

    def test_log_path_scoped_to_test_user(self, tmp_path: Path) -> None:
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("ingest", "Test Source", user_id=TEST_USER_ID)

        log_path = tmp_path / "wiki" / TEST_USER_ID / "log.md"
        assert log_path.exists()

    def test_separate_logs_per_user(self, tmp_path: Path) -> None:
        with patch("wikimind.services.activity_log.get_settings") as mock_settings:
            mock_settings.return_value.data_dir = str(tmp_path)
            append_log_entry("ingest", "Alice Source", user_id="alice")
            append_log_entry("ingest", "Bob Source", user_id="bob")

        alice_log = tmp_path / "wiki" / "alice" / "log.md"
        bob_log = tmp_path / "wiki" / "bob" / "log.md"
        assert alice_log.exists()
        assert bob_log.exists()

        alice_content = alice_log.read_text(encoding="utf-8")
        bob_content = bob_log.read_text(encoding="utf-8")
        assert "Alice Source" in alice_content
        assert "Bob Source" not in alice_content
        assert "Bob Source" in bob_content


@pytest.mark.asyncio
class TestFileBackSelectionPathScoping:
    """file_back_selection should scope qa-answers path by user_id."""

    async def test_qa_answers_path_includes_user_id(
        self,
        db_session: AsyncSession,
    ) -> None:
        conv = Conversation(title="Test Conv", user_id="alice")
        db_session.add(conv)
        await db_session.commit()
        await db_session.refresh(conv)

        q = Query(
            question="What is X?",
            answer="X is Y.",
            conversation_id=conv.id,
            turn_index=0,
            user_id="alice",
        )
        db_session.add(q)
        await db_session.commit()
        await db_session.refresh(q)

        svc = QueryService()
        request = FileBackSelectionRequest(
            selections=[
                TurnSelection(
                    conversation_id=conv.id,
                    turn_indices=[0],
                ),
            ],
        )
        result = await svc.file_back_selection(
            request,
            db_session,
            user_id="alice",
        )

        # Verify the article stores a relative path and resolves under wiki/alice/
        art_result = await db_session.execute(select(Article).where(Article.id == result.article.id))
        article = art_result.scalar_one()
        assert article.file_path.startswith("qa-answers/")
        resolved = resolve_wiki_path(article.file_path, user_id="alice")
        assert "/alice/" in str(resolved)


# ---------------------------------------------------------------------------
# Issue 12: ChromaDB user_id scoping
# ---------------------------------------------------------------------------


class TestEmbeddingServiceUserScoping:
    """Embedding service should include user_id in metadata and filter on search."""

    @pytest.mark.skipif(
        not _SEARCH_AVAILABLE,
        reason="search extras not installed",
    )
    def test_embed_article_includes_user_id_metadata(self) -> None:
        from wikimind.services.embedding import EmbeddingService  # noqa: PLC0415

        with (
            patch.object(EmbeddingService, "__init__", lambda self: None),
            patch.object(
                EmbeddingService,
                "_encode",
                return_value=[[0.1, 0.2]],
            ),
        ):
            svc = EmbeddingService.__new__(EmbeddingService)
            svc._chunk_size = 500
            svc._chunk_overlap = 50
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            svc._collection = mock_collection

            svc.embed_article(
                "art-1",
                "Test",
                "Content here.",
                user_id="alice",
            )

            call_args = mock_collection.add.call_args
            metadatas = call_args.kwargs.get(
                "metadatas",
                call_args[1].get("metadatas"),
            )
            assert metadatas[0]["user_id"] == "alice"

    @pytest.mark.skipif(
        not _SEARCH_AVAILABLE,
        reason="search extras not installed",
    )
    def test_search_passes_user_id_filter(self) -> None:
        from wikimind.services.embedding import EmbeddingService  # noqa: PLC0415

        with (
            patch.object(EmbeddingService, "__init__", lambda self: None),
            patch.object(
                EmbeddingService,
                "_encode",
                return_value=[[0.1, 0.2]],
            ),
        ):
            svc = EmbeddingService.__new__(EmbeddingService)
            mock_collection = MagicMock()
            mock_collection.count.return_value = 5
            mock_collection.query.return_value = {
                "ids": [["art-1_chunk_0"]],
                "distances": [[0.2]],
                "metadatas": [
                    [
                        {
                            "article_id": "art-1",
                            "article_title": "Test",
                            "chunk_index": 0,
                            "user_id": "alice",
                        }
                    ]
                ],
                "documents": [["Some text"]],
            }
            svc._collection = mock_collection
            svc._min_score = 0.65

            svc.search("query text", limit=5, user_id="alice")

            call_kwargs = mock_collection.query.call_args.kwargs
            assert call_kwargs["where"] == {"user_id": "alice"}
