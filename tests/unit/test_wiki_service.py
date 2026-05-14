"""Tests for the WikiService source-provenance enrichment."""

import json
from pathlib import Path

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    BacklinkEntry,
    Concept,
    RelationType,
    Source,
    SourceType,
)
from wikimind.services.wiki import WikiService


def _wiki_root() -> Path:
    """Return the wiki storage root for TEST_USER_ID and ensure it exists."""
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki" / TEST_USER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _seed_article_with_sources(db_session, tmp_path: Path) -> tuple[Article, list[Source]]:
    """Create one article on disk and two persisted sources it references."""
    wiki = _wiki_root()
    (wiki / "test-article.md").write_text("# Test Article\n\nSome content about Langflow.", encoding="utf-8")

    pdf_source = Source(
        source_type=SourceType.PDF,
        title="20260312_MikeO_AILabsGeneralTalk",
        source_url=None,
        user_id=TEST_USER_ID,
    )
    url_source = Source(
        source_type=SourceType.URL,
        title="IBM Agentic AI Labs",
        source_url="https://example.com/ibm",
        user_id=TEST_USER_ID,
    )
    db_session.add(pdf_source)
    db_session.add(url_source)
    await db_session.flush()

    article = Article(
        slug="ibm-agentic-ai-labs",
        title="IBM Agentic AI Labs",
        file_path="test-article.md",
        summary="Summary about IBM Agentic AI Labs.",
        source_ids=json.dumps([pdf_source.id, url_source.id]),
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    db_session.add(ArticleSource(article_id=article.id, source_id=pdf_source.id, user_id=TEST_USER_ID))
    db_session.add(ArticleSource(article_id=article.id, source_id=url_source.id, user_id=TEST_USER_ID))
    await db_session.commit()
    return article, [pdf_source, url_source]


@pytest.mark.asyncio
class TestArticleProvenance:
    async def test_get_article_includes_full_source_provenance(self, db_session, tmp_path):
        article, sources = await _seed_article_with_sources(db_session, tmp_path)
        service = WikiService()

        response = await service.get_article(article.slug, db_session, user_id=TEST_USER_ID)

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

        results = await service.list_articles(db_session, user_id=TEST_USER_ID)

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

        results = await service.search("Langflow", db_session, user_id=TEST_USER_ID)

        assert len(results) == 1
        match = results[0]
        assert match.slug == article.slug
        assert len(match.sources) == 2

    async def test_get_article_handles_missing_sources_gracefully(self, db_session, tmp_path):
        """An article that references a deleted source still returns successfully."""
        wiki = _wiki_root()
        (wiki / "orphan.md").write_text("# Orphan", encoding="utf-8")
        article = Article(
            slug="orphan-article",
            title="Orphan Article",
            file_path="orphan.md",
            source_ids=json.dumps(["does-not-exist-uuid"]),
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article("orphan-article", db_session, user_id=TEST_USER_ID)

        assert response.slug == "orphan-article"
        assert response.sources == []

    async def test_get_article_handles_missing_source_ids_field(self, db_session, tmp_path):
        """An article with no source_ids JSON returns an empty sources list."""
        wiki = _wiki_root()
        (wiki / "no-sources.md").write_text("# No sources", encoding="utf-8")
        article = Article(
            slug="no-source-article",
            title="No Source Article",
            file_path="no-sources.md",
            source_ids=None,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article("no-source-article", db_session, user_id=TEST_USER_ID)

        assert response.sources == []

    async def test_get_article_by_id_returns_article(self, db_session, tmp_path):
        """Fetching an article by its UUID id returns it."""
        wiki = _wiki_root()
        (wiki / "my-article.md").write_text("# My Article", encoding="utf-8")
        article = Article(
            slug="my-article",
            title="My Article",
            file_path="my-article.md",
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()
        await db_session.refresh(article)

        service = WikiService()
        result = await service.get_article(article.id, db_session, user_id=TEST_USER_ID)

        assert result.id == article.id
        assert result.slug == "my-article"

    async def test_get_article_by_slug_still_works(self, db_session, tmp_path):
        """Backward compat: slug lookup continues to work after the ID-first rewrite."""
        wiki = _wiki_root()
        (wiki / "legacy.md").write_text("# Legacy Bookmark", encoding="utf-8")
        article = Article(
            slug="legacy-bookmark",
            title="Legacy Bookmark",
            file_path="legacy.md",
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()
        await db_session.refresh(article)

        service = WikiService()
        result = await service.get_article("legacy-bookmark", db_session, user_id=TEST_USER_ID)

        assert result.slug == "legacy-bookmark"


@pytest.mark.asyncio
class TestBacklinkEntries:
    async def test_get_article_returns_backlink_entries_with_title_and_slug(self, db_session, tmp_path):
        """backlinks_in and backlinks_out are BacklinkEntry objects with id, title, slug."""
        wiki = _wiki_root()
        # Create three articles: A links to B, C links to B
        (wiki / "article-a.md").write_text("# Article A", encoding="utf-8")
        (wiki / "article-b.md").write_text("# Article B", encoding="utf-8")
        (wiki / "article-c.md").write_text("# Article C", encoding="utf-8")

        article_a = Article(slug="article-a", title="Article A", file_path="article-a.md", user_id=TEST_USER_ID)
        article_b = Article(slug="article-b", title="Article B", file_path="article-b.md", user_id=TEST_USER_ID)
        article_c = Article(slug="article-c", title="Article C", file_path="article-c.md", user_id=TEST_USER_ID)
        db_session.add_all([article_a, article_b, article_c])
        await db_session.flush()

        # A -> B and C -> B
        bl_ab = Backlink(source_article_id=article_a.id, target_article_id=article_b.id, user_id=TEST_USER_ID)
        bl_cb = Backlink(source_article_id=article_c.id, target_article_id=article_b.id, user_id=TEST_USER_ID)
        # B -> A
        bl_ba = Backlink(source_article_id=article_b.id, target_article_id=article_a.id, user_id=TEST_USER_ID)
        db_session.add_all([bl_ab, bl_cb, bl_ba])
        await db_session.commit()

        service = WikiService()
        response = await service.get_article(article_b.id, db_session, user_id=TEST_USER_ID)

        # backlinks_in: A and C link to B
        assert len(response.backlinks_in) == 2
        in_ids = {bl.id for bl in response.backlinks_in}
        assert in_ids == {article_a.id, article_c.id}
        for bl in response.backlinks_in:
            assert isinstance(bl, BacklinkEntry)
            assert bl.title in ("Article A", "Article C")
            assert bl.slug in ("article-a", "article-c")

        # backlinks_out: B links to A
        assert len(response.backlinks_out) == 1
        assert response.backlinks_out[0].id == article_a.id
        assert response.backlinks_out[0].title == "Article A"
        assert response.backlinks_out[0].slug == "article-a"

    async def test_get_article_skips_deleted_backlink_targets(self, db_session, tmp_path):
        """Backlinks referencing a deleted article are silently dropped."""
        wiki = _wiki_root()
        (wiki / "survivor.md").write_text("# Survivor", encoding="utf-8")

        article = Article(slug="survivor", title="Survivor", file_path="survivor.md", user_id=TEST_USER_ID)
        db_session.add(article)
        await db_session.flush()

        # Insert a backlink whose source article does not exist.
        # The JOIN will naturally exclude it because there's no matching Article row.
        ghost_id = "00000000-0000-0000-0000-000000000000"
        bl = Backlink(source_article_id=ghost_id, target_article_id=article.id, user_id=TEST_USER_ID)
        db_session.add(bl)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article(article.id, db_session, user_id=TEST_USER_ID)

        # The ghost backlink is dropped because the JOIN excludes missing articles
        assert response.backlinks_in == []

    async def test_get_article_empty_backlinks(self, db_session, tmp_path):
        """An article with no backlinks returns empty BacklinkEntry lists."""
        wiki = _wiki_root()
        (wiki / "lonely.md").write_text("# Lonely", encoding="utf-8")

        article = Article(slug="lonely", title="Lonely", file_path="lonely.md", user_id=TEST_USER_ID)
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article(article.id, db_session, user_id=TEST_USER_ID)

        assert response.backlinks_in == []
        assert response.backlinks_out == []


@pytest.mark.asyncio
class TestConceptPopulation:
    async def test_get_article_populates_concepts_from_concept_ids(self, db_session, tmp_path):
        """ArticleResponse.concepts is populated from Article.concept_ids JSON."""
        wiki = _wiki_root()
        (wiki / "ml-article.md").write_text("# ML Article", encoding="utf-8")

        article = Article(
            slug="ml-article",
            title="ML Article",
            file_path="ml-article.md",
            concept_ids=json.dumps(["Machine Learning", "Deep Learning"]),
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article(article.id, db_session, user_id=TEST_USER_ID)

        assert response.concepts == ["Machine Learning", "Deep Learning"]

    async def test_get_article_returns_empty_concepts_when_none(self, db_session, tmp_path):
        """ArticleResponse.concepts is [] when concept_ids is None."""
        wiki = _wiki_root()
        (wiki / "no-concepts.md").write_text("# No Concepts", encoding="utf-8")

        article = Article(
            slug="no-concepts",
            title="No Concepts",
            file_path="no-concepts.md",
            concept_ids=None,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        response = await service.get_article(article.id, db_session, user_id=TEST_USER_ID)

        assert response.concepts == []

    async def test_graph_populates_concept_cluster(self, db_session, tmp_path):
        """GraphNode.concept_cluster is the first concept from concept_ids."""
        fp = tmp_path / "graph-article.md"
        fp.write_text("# Graph Article", encoding="utf-8")

        article = Article(
            slug="graph-article",
            title="Graph Article",
            file_path=str(fp),
            concept_ids=json.dumps(["AI", "Machine Learning"]),
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID)

        assert len(graph.nodes) == 1
        assert graph.nodes[0].concept_cluster == "AI"

    async def test_graph_concept_cluster_none_when_no_concepts(self, db_session, tmp_path):
        """GraphNode.concept_cluster is None when concept_ids is empty or None."""
        fp = tmp_path / "plain-article.md"
        fp.write_text("# Plain", encoding="utf-8")

        article = Article(
            slug="plain-article",
            title="Plain Article",
            file_path=str(fp),
            concept_ids=None,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID)

        assert len(graph.nodes) == 1
        assert graph.nodes[0].concept_cluster is None

    async def test_get_concepts_include_empty_false_filters(self, db_session):
        """get_concepts with include_empty=False excludes zero-count concepts."""
        populated = Concept(name="populated", article_count=3, user_id=TEST_USER_ID)
        empty = Concept(name="empty", article_count=0, user_id=TEST_USER_ID)
        db_session.add_all([populated, empty])
        await db_session.commit()

        service = WikiService()
        all_concepts = await service.get_concepts(db_session, include_empty=True, user_id=TEST_USER_ID)
        assert len(all_concepts) == 2

        non_empty = await service.get_concepts(db_session, include_empty=False, user_id=TEST_USER_ID)
        assert len(non_empty) == 1
        assert non_empty[0].name == "populated"


@pytest.mark.asyncio
class TestConceptFiltering:
    """Tests for list_articles concept filtering via json_each()."""

    async def test_list_articles_filters_by_concept(self, db_session, tmp_path):
        """Articles are filtered when a concept name is passed."""
        fp_ml = tmp_path / "ml.md"
        fp_ml.write_text("# ML", encoding="utf-8")
        fp_db = tmp_path / "db.md"
        fp_db.write_text("# DB", encoding="utf-8")

        ml_article = Article(
            slug="ml-article",
            title="ML Article",
            file_path=str(fp_ml),
            concept_ids=json.dumps(["Machine Learning", "AI"]),
            user_id=TEST_USER_ID,
        )
        db_article = Article(
            slug="db-article",
            title="DB Article",
            file_path=str(fp_db),
            concept_ids=json.dumps(["Databases"]),
            user_id=TEST_USER_ID,
        )
        db_session.add_all([ml_article, db_article])
        await db_session.commit()
        await db_session.refresh(ml_article)
        await db_session.refresh(db_article)
        db_session.add(ArticleConcept(article_id=ml_article.id, concept_name="Machine Learning"))
        db_session.add(ArticleConcept(article_id=ml_article.id, concept_name="AI"))
        db_session.add(ArticleConcept(article_id=db_article.id, concept_name="Databases"))
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, concept="Machine Learning", user_id=TEST_USER_ID)

        assert len(results) == 1
        assert results[0].slug == "ml-article"

    async def test_list_articles_no_concept_returns_all(self, db_session, tmp_path):
        """Without a concept filter, all articles are returned."""
        fp_a = tmp_path / "a.md"
        fp_a.write_text("# A", encoding="utf-8")
        fp_b = tmp_path / "b.md"
        fp_b.write_text("# B", encoding="utf-8")

        db_session.add_all(
            [
                Article(
                    slug="a",
                    title="A",
                    file_path=str(fp_a),
                    concept_ids=json.dumps(["AI"]),
                    user_id=TEST_USER_ID,
                ),
                Article(
                    slug="b",
                    title="B",
                    file_path=str(fp_b),
                    concept_ids=json.dumps(["Databases"]),
                    user_id=TEST_USER_ID,
                ),
            ]
        )
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, user_id=TEST_USER_ID)

        assert len(results) == 2

    async def test_list_articles_concept_filter_excludes_null_concept_ids(self, db_session, tmp_path):
        """Articles with null concept_ids are excluded when filtering by concept."""
        fp = tmp_path / "no-concepts.md"
        fp.write_text("# No Concepts", encoding="utf-8")

        db_session.add(
            Article(
                slug="no-concepts",
                title="No Concepts",
                file_path=str(fp),
                concept_ids=None,
                user_id=TEST_USER_ID,
            )
        )
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, concept="AI", user_id=TEST_USER_ID)

        assert len(results) == 0

    async def test_list_articles_concept_filter_with_confidence(self, db_session, tmp_path):
        """Concept and confidence filters work together."""
        fp_a = tmp_path / "sourced.md"
        fp_a.write_text("# Sourced", encoding="utf-8")
        fp_b = tmp_path / "inferred.md"
        fp_b.write_text("# Inferred", encoding="utf-8")

        sourced_art = Article(
            slug="sourced-ai",
            title="Sourced AI",
            file_path=str(fp_a),
            concept_ids=json.dumps(["AI"]),
            confidence="sourced",
            user_id=TEST_USER_ID,
        )
        inferred_art = Article(
            slug="inferred-ai",
            title="Inferred AI",
            file_path=str(fp_b),
            concept_ids=json.dumps(["AI"]),
            confidence="inferred",
            user_id=TEST_USER_ID,
        )
        db_session.add_all([sourced_art, inferred_art])
        await db_session.commit()
        await db_session.refresh(sourced_art)
        await db_session.refresh(inferred_art)
        db_session.add(ArticleConcept(article_id=sourced_art.id, concept_name="AI"))
        db_session.add(ArticleConcept(article_id=inferred_art.id, concept_name="AI"))
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(
            db_session,
            concept="AI",
            confidence="sourced",
            user_id=TEST_USER_ID,
        )

        assert len(results) == 1
        assert results[0].slug == "sourced-ai"

    async def test_list_articles_concept_no_match(self, db_session, tmp_path):
        """A concept that no article has returns an empty list."""
        fp = tmp_path / "ml.md"
        fp.write_text("# ML", encoding="utf-8")

        ml_art = Article(
            slug="ml",
            title="ML",
            file_path=str(fp),
            concept_ids=json.dumps(["Machine Learning"]),
            user_id=TEST_USER_ID,
        )
        db_session.add(ml_art)
        await db_session.commit()
        await db_session.refresh(ml_art)
        db_session.add(ArticleConcept(article_id=ml_art.id, concept_name="Machine Learning"))
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, concept="Quantum Computing", user_id=TEST_USER_ID)

        assert len(results) == 0


@pytest.mark.asyncio
class TestArticleSummaryCounts:
    """Tests for source_count and backlink_count on ArticleSummaryResponse."""

    async def test_source_count_populated(self, db_session, tmp_path):
        """source_count reflects the number of resolved sources."""
        _article, _sources = await _seed_article_with_sources(db_session, tmp_path)
        service = WikiService()

        results = await service.list_articles(db_session, user_id=TEST_USER_ID)

        assert len(results) == 1
        assert results[0].source_count == 2

    async def test_backlink_count_populated(self, db_session, tmp_path):
        """backlink_count reflects both incoming and outgoing backlinks."""
        fp_a = tmp_path / "a.md"
        fp_a.write_text("# A", encoding="utf-8")
        fp_b = tmp_path / "b.md"
        fp_b.write_text("# B", encoding="utf-8")

        article_a = Article(slug="a", title="A", file_path=str(fp_a), user_id=TEST_USER_ID)
        article_b = Article(slug="b", title="B", file_path=str(fp_b), user_id=TEST_USER_ID)
        db_session.add_all([article_a, article_b])
        await db_session.flush()

        bl = Backlink(source_article_id=article_a.id, target_article_id=article_b.id, user_id=TEST_USER_ID)
        db_session.add(bl)
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, user_id=TEST_USER_ID)

        by_slug = {r.slug: r for r in results}
        # article_a has 1 outgoing backlink
        assert by_slug["a"].backlink_count == 1
        # article_b has 1 incoming backlink
        assert by_slug["b"].backlink_count == 1

    async def test_zero_counts_when_no_sources_or_backlinks(self, db_session, tmp_path):
        """source_count and backlink_count default to 0."""
        fp = tmp_path / "lonely.md"
        fp.write_text("# Lonely", encoding="utf-8")

        db_session.add(
            Article(
                slug="lonely",
                title="Lonely",
                file_path=str(fp),
                user_id=TEST_USER_ID,
            )
        )
        await db_session.commit()

        service = WikiService()
        results = await service.list_articles(db_session, user_id=TEST_USER_ID)

        assert len(results) == 1
        assert results[0].source_count == 0
        assert results[0].backlink_count == 0


@pytest.mark.asyncio
class TestTypedGraphFiltering:
    """Tests for issue #423 — typed-edge filters on get_graph + get_relationships."""

    async def _seed(self, db_session, tmp_path: Path) -> None:
        for slug, title in [("art-a", "A"), ("art-b", "B"), ("art-c", "C")]:
            fp = tmp_path / f"{slug}.md"
            fp.write_text(f"# {title}", encoding="utf-8")
            db_session.add(
                Article(id=slug.replace("art-", "id-"), slug=slug, title=title, file_path=str(fp), user_id=TEST_USER_ID)
            )
        await db_session.commit()
        db_session.add(
            Backlink(
                source_article_id="id-a",
                target_article_id="id-b",
                relation_type=RelationType.REFERENCES,
                user_id=TEST_USER_ID,
            )
        )
        db_session.add(
            Backlink(
                source_article_id="id-a",
                target_article_id="id-c",
                relation_type=RelationType.CONTRADICTS,
                context="conflict",
                user_id=TEST_USER_ID,
            )
        )
        db_session.add(
            Backlink(
                source_article_id="id-b",
                target_article_id="id-c",
                relation_type=RelationType.SUPERSEDES,
                user_id=TEST_USER_ID,
            )
        )
        await db_session.commit()

    async def test_resolve_article_id_returns_none_when_empty(self, db_session):
        service = WikiService()
        assert await service._resolve_article_id("", db_session, TEST_USER_ID) is None

    async def test_resolve_article_id_by_id(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        assert await service._resolve_article_id("id-a", db_session, TEST_USER_ID) == "id-a"

    async def test_resolve_article_id_by_slug(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        assert await service._resolve_article_id("art-a", db_session, TEST_USER_ID) == "id-a"

    async def test_resolve_article_id_unknown(self, db_session):
        service = WikiService()
        assert await service._resolve_article_id("does-not-exist", db_session, TEST_USER_ID) is None

    async def test_get_graph_filter_by_relation_type(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, relation_type=RelationType.CONTRADICTS)
        assert len(graph.edges) == 1
        assert graph.edges[0].relation_type == RelationType.CONTRADICTS

    async def test_get_graph_filter_by_from_id(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, from_article="id-a")
        assert len(graph.edges) == 2

    async def test_get_graph_filter_by_from_slug(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, from_article="art-a")
        assert len(graph.edges) == 2

    async def test_get_graph_filter_by_to(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, to_article="id-c")
        assert len(graph.edges) == 2

    async def test_get_graph_filter_by_to_slug(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, to_article="art-c")
        assert len(graph.edges) == 2

    async def test_get_graph_unknown_from_returns_empty(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, from_article="missing")
        assert graph.edges == []
        assert graph.nodes == []

    async def test_get_graph_unknown_to_returns_empty(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(db_session, user_id=TEST_USER_ID, to_article="missing")
        assert graph.edges == []
        assert graph.nodes == []

    async def test_get_graph_compose_and(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        graph = await service.get_graph(
            db_session,
            user_id=TEST_USER_ID,
            from_article="id-a",
            relation_type=RelationType.CONTRADICTS,
        )
        assert len(graph.edges) == 1
        assert graph.edges[0].source == "id-a"
        assert graph.edges[0].target == "id-c"

    async def test_get_relationships_groups_outgoing(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        rels = await service.get_relationships("id-a", db_session, user_id=TEST_USER_ID)
        assert rels.incoming == {}
        assert set(rels.outgoing.keys()) == {"references", "contradicts"}
        assert rels.outgoing["references"][0].article_id == "id-b"
        assert rels.outgoing["references"][0].slug == "art-b"
        assert rels.outgoing["contradicts"][0].article_id == "id-c"

    async def test_get_relationships_groups_incoming_by_slug(self, db_session, tmp_path):
        await self._seed(db_session, tmp_path)
        service = WikiService()
        rels = await service.get_relationships("art-c", db_session, user_id=TEST_USER_ID)
        assert rels.outgoing == {}
        assert set(rels.incoming.keys()) == {"contradicts", "supersedes"}

    async def test_get_relationships_404_when_missing(self, db_session):
        service = WikiService()
        with pytest.raises(NotFoundError):
            await service.get_relationships("missing", db_session, user_id=TEST_USER_ID)
