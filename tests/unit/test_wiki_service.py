"""Tests for the WikiService source-provenance enrichment."""

import json
from pathlib import Path

import pytest

from wikimind.models import Article, Source, SourceType
from wikimind.services.wiki import WikiService


async def _seed_article_with_sources(db_session, tmp_path: Path) -> tuple[Article, list[Source]]:
    """Create one article on disk and two persisted sources it references."""
    file_path = tmp_path / "test-article.md"
    file_path.write_text("# Test Article\n\nSome content about Langflow.", encoding="utf-8")

    pdf_source = Source(
        source_type=SourceType.PDF,
        title="20260312_MikeO_AILabsGeneralTalk",
        source_url=None,
    )
    url_source = Source(
        source_type=SourceType.URL,
        title="IBM Agentic AI Labs",
        source_url="https://example.com/ibm",
    )
    db_session.add(pdf_source)
    db_session.add(url_source)
    await db_session.flush()

    article = Article(
        slug="ibm-agentic-ai-labs",
        title="IBM Agentic AI Labs",
        file_path=str(file_path),
        summary="Summary about IBM Agentic AI Labs.",
        source_ids=json.dumps([pdf_source.id, url_source.id]),
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article, [pdf_source, url_source]


@pytest.mark.asyncio
class TestArticleProvenance:
    async def test_get_article_includes_full_source_provenance(self, db_session, tmp_path):
        article, sources = await _seed_article_with_sources(db_session, tmp_path)
        service = WikiService()

        response = await service.get_article(article.slug, db_session)

        assert response.slug == article.slug
        assert len(response.sources) == 2
        ids = {s.id for s in response.sources}
        assert ids == {sources[0].id, sources[1].id}

        pdf = next(s for s in response.sources if s.source_type == SourceType.PDF)
        assert pdf.title == "20260312_MikeO_AILabsGeneralTalk"
        assert pdf.source_url is None
        assert pdf.ingested_at is not None

        url = next(s for s in response.sources if s.source_type == SourceType.URL)
        assert url.source_url == "https://example.com/ibm"

    async def test_list_articles_includes_source_summaries(self, db_session, tmp_path):
        article, _sources = await _seed_article_with_sources(db_session, tmp_path)
        service = WikiService()

        results = await service.list_articles(db_session)

        assert len(results) == 1
        summary = results[0]
        assert summary.slug == article.slug
        assert len(summary.sources) == 2
        types = {s.source_type for s in summary.sources}
        assert types == {SourceType.PDF, SourceType.URL}
        # Lightweight summary does not expose ingested_at / source_url.
        assert all(s.title is not None for s in summary.sources)

    async def test_search_includes_source_summaries(self, db_session, tmp_path):
        article, _ = await _seed_article_with_sources(db_session, tmp_path)
        service = WikiService()

        results = await service.search("Langflow", db_session)

        assert len(results) == 1
        match = results[0]
        assert match.slug == article.slug
        assert len(match.sources) == 2

    async def test_get_article_handles_missing_sources_gracefully(self, db_session, tmp_path):
        """An article that references a deleted source still returns successfully."""
        file_path = tmp_path / "orphan.md"
        file_path.write_text("# Orphan", encoding="utf-8")
        article = Article(
            slug="orphan-article",
            title="Orphan Article",
            file_path=str(file_path),
            source_ids=json.dumps(["does-not-exist-uuid"]),
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article("orphan-article", db_session)

        assert response.slug == "orphan-article"
        assert response.sources == []

    async def test_get_article_handles_missing_source_ids_field(self, db_session, tmp_path):
        """An article with no source_ids JSON returns an empty sources list."""
        file_path = tmp_path / "no-sources.md"
        file_path.write_text("# No sources", encoding="utf-8")
        article = Article(
            slug="no-source-article",
            title="No Source Article",
            file_path=str(file_path),
            source_ids=None,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article("no-source-article", db_session)

        assert response.sources == []

    async def test_get_article_by_id_returns_article(self, db_session, tmp_path):
        """Fetching an article by its UUID id returns it."""
        file_path = tmp_path / "my-article.md"
        file_path.write_text("# My Article", encoding="utf-8")
        article = Article(
            slug="my-article",
            title="My Article",
            file_path=str(file_path),
        )
        db_session.add(article)
        await db_session.commit()
        await db_session.refresh(article)

        service = WikiService()
        result = await service.get_article(article.id, db_session)

        assert result.id == article.id
        assert result.slug == "my-article"

    async def test_get_article_by_slug_still_works(self, db_session, tmp_path):
        """Backward compat: slug lookup continues to work after the ID-first rewrite."""
        file_path = tmp_path / "legacy.md"
        file_path.write_text("# Legacy Bookmark", encoding="utf-8")
        article = Article(
            slug="legacy-bookmark",
            title="Legacy Bookmark",
            file_path=str(file_path),
        )
        db_session.add(article)
        await db_session.commit()
        await db_session.refresh(article)

        service = WikiService()
        result = await service.get_article("legacy-bookmark", db_session)

        assert result.slug == "legacy-bookmark"
