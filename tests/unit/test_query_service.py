"""Tests for the QueryService citation chain resolution."""

import json
from pathlib import Path

import pytest

from wikimind.models import Article, Query, Source, SourceType
from wikimind.services.query import _build_citations


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
