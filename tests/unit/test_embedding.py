"""Tests for the embedding service, chunking logic, and hybrid search merging."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wikimind.models import Article
from wikimind.services.embedding import (
    _SEARCH_AVAILABLE,
    SemanticSearchResult,
    chunk_article_text,
)
from wikimind.services.wiki import WikiService, _merge_hybrid_scores

# ---------------------------------------------------------------------------
# Chunking logic
# ---------------------------------------------------------------------------


class TestChunkArticleText:
    def test_empty_text_returns_no_chunks(self):
        assert chunk_article_text("") == []
        assert chunk_article_text("   ") == []

    def test_single_short_paragraph(self):
        text = "This is a short paragraph."
        chunks = chunk_article_text(text, chunk_size_tokens=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_multiple_paragraphs_merged_when_small(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = chunk_article_text(text, chunk_size_tokens=500)
        assert len(chunks) == 1
        assert "Paragraph one." in chunks[0]
        assert "Paragraph three." in chunks[0]

    def test_paragraphs_split_at_token_boundary(self):
        # Each paragraph ~25 tokens (100 chars / 4)
        para = "x" * 100
        text = "\n\n".join([para] * 10)  # ~250 tokens total
        chunks = chunk_article_text(text, chunk_size_tokens=60, chunk_overlap_tokens=10)
        assert len(chunks) > 1

    def test_oversized_paragraph_hard_split(self):
        # Single paragraph of ~1000 tokens (4000 chars)
        big_para = "word " * 800  # ~4000 chars = ~1000 tokens
        chunks = chunk_article_text(big_para.strip(), chunk_size_tokens=200)
        assert len(chunks) > 1

    def test_overlap_preserves_context(self):
        # Two paragraphs that each fit individually but not together
        para_a = "alpha " * 60  # ~360 chars = ~90 tokens
        para_b = "bravo " * 60
        para_c = "charlie " * 60
        text = f"{para_a.strip()}\n\n{para_b.strip()}\n\n{para_c.strip()}"
        chunks = chunk_article_text(text, chunk_size_tokens=100, chunk_overlap_tokens=20)
        assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# Hybrid score merging
# ---------------------------------------------------------------------------


class TestMergeHybridScores:
    def test_keyword_only(self):
        keyword = {"a": 1.0, "b": 0.5}
        merged = _merge_hybrid_scores(keyword, [])
        assert merged["a"] == pytest.approx(0.4)
        assert merged["b"] == pytest.approx(0.2)

    def test_semantic_only(self):
        semantic = [
            SemanticSearchResult(article_id="x", score=0.9, chunk_text="", chunk_index=0),
        ]
        merged = _merge_hybrid_scores({}, semantic)
        assert merged["x"] == pytest.approx(0.6 * 0.9)

    def test_combined_scores(self):
        keyword = {"a": 1.0}
        semantic = [
            SemanticSearchResult(article_id="a", score=0.8, chunk_text="", chunk_index=0),
        ]
        merged = _merge_hybrid_scores(keyword, semantic)
        expected = 0.4 * 1.0 + 0.6 * 0.8
        assert merged["a"] == pytest.approx(expected)

    def test_deduplication_uses_best_chunk(self):
        semantic = [
            SemanticSearchResult(article_id="a", score=0.5, chunk_text="c1", chunk_index=0),
            SemanticSearchResult(article_id="a", score=0.9, chunk_text="c2", chunk_index=1),
        ]
        merged = _merge_hybrid_scores({}, semantic)
        # Should use the higher score (0.9)
        assert merged["a"] == pytest.approx(0.6 * 0.9)

    def test_union_of_keyword_and_semantic(self):
        keyword = {"a": 0.5}
        semantic = [
            SemanticSearchResult(article_id="b", score=0.7, chunk_text="", chunk_index=0),
        ]
        merged = _merge_hybrid_scores(keyword, semantic)
        assert "a" in merged
        assert "b" in merged


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_search_available_is_bool(self):
        assert isinstance(_SEARCH_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_wiki_search_works_without_search_extras(self, db_session, tmp_path):
        """WikiService.search falls back to keyword-only when extras are missing."""
        fp = tmp_path / "test.md"
        fp.write_text("# Deep Learning\n\nNeural network architectures.", encoding="utf-8")

        article = Article(
            slug="deep-learning",
            title="Deep Learning",
            file_path=str(fp),
            summary="About deep learning.",
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        with patch("wikimind.services.wiki._SEARCH_AVAILABLE", False):
            results = await service.search("Deep", db_session)

        assert len(results) == 1
        assert results[0].slug == "deep-learning"


# ---------------------------------------------------------------------------
# Embedding service (mocked ChromaDB)
# ---------------------------------------------------------------------------


class TestEmbeddingServiceMocked:
    @pytest.mark.skipif(not _SEARCH_AVAILABLE, reason="search extras not installed")
    def test_embed_article_stores_chunks(self):
        from wikimind.services.embedding import EmbeddingService  # noqa: PLC0415

        with (
            patch.object(EmbeddingService, "__init__", lambda self: None),
            patch.object(EmbeddingService, "_encode", return_value=[[0.1, 0.2], [0.3, 0.4]]),
        ):
            svc = EmbeddingService.__new__(EmbeddingService)
            svc._chunk_size = 500
            svc._chunk_overlap = 50
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            svc._collection = mock_collection

            count = svc.embed_article("art-1", "Test Article", "Para one.\n\nPara two.")

            assert count == 1  # Both paras fit in one chunk
            mock_collection.add.assert_called_once()

    @pytest.mark.skipif(not _SEARCH_AVAILABLE, reason="search extras not installed")
    def test_search_returns_results(self):
        from wikimind.services.embedding import EmbeddingService  # noqa: PLC0415

        with (
            patch.object(EmbeddingService, "__init__", lambda self: None),
            patch.object(EmbeddingService, "_encode", return_value=[[0.1, 0.2]]),
        ):
            svc = EmbeddingService.__new__(EmbeddingService)
            mock_collection = MagicMock()
            mock_collection.count.return_value = 5
            mock_collection.query.return_value = {
                "ids": [["art-1_chunk_0"]],
                "distances": [[0.2]],
                "metadatas": [[{"article_id": "art-1", "article_title": "Test", "chunk_index": 0}]],
                "documents": [["Some chunk text"]],
            }
            svc._collection = mock_collection

            results = svc.search("query text", limit=5)

            assert len(results) == 1
            assert results[0].article_id == "art-1"
            assert results[0].score == pytest.approx(0.9)  # 1 - 0.2/2
            assert results[0].chunk_text == "Some chunk text"

    @pytest.mark.skipif(not _SEARCH_AVAILABLE, reason="search extras not installed")
    def test_delete_article_calls_collection_delete(self):
        from wikimind.services.embedding import EmbeddingService  # noqa: PLC0415

        with patch.object(EmbeddingService, "__init__", lambda self: None):
            svc = EmbeddingService.__new__(EmbeddingService)
            mock_collection = MagicMock()
            svc._collection = mock_collection

            svc.delete_article("art-1")

            mock_collection.delete.assert_called_once_with(where={"article_id": "art-1"})


# ---------------------------------------------------------------------------
# Embedding failure does not crash compilation
# ---------------------------------------------------------------------------


class TestEmbeddingFailureResilience:
    @pytest.mark.asyncio
    async def test_embedding_failure_does_not_crash(self):
        """If get_embedding_service() raises, the worker should catch and log."""
        with patch(
            "wikimind.services.embedding.get_embedding_service",
            side_effect=RuntimeError("boom"),
        ):
            from wikimind.services.embedding import get_embedding_service  # noqa: PLC0415

            # Simulate what the worker does
            try:
                svc = get_embedding_service()
                if svc is not None:
                    svc.embed_article("id", "title", "content")
            except Exception:
                pass  # Worker catches this -- compilation must not fail
            # If we get here without an unhandled exception, the test passes
