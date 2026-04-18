"""Retrieve wiki articles, build the knowledge graph, and search content.

Centralizes all article retrieval, full-text search, concept taxonomy,
and health report generation so route handlers stay thin. Article and
search responses are enriched with source provenance so callers can
trace each compiled article back to its raw ingested sources.

When the ``[search]`` optional extras are installed (chromadb,
sentence-transformers), full-text search is enhanced with semantic
vector similarity and results are merged via configurable hybrid
scoring. Otherwise the service falls back to keyword-only search.
"""

import json
from pathlib import Path

import structlog
from fastapi import HTTPException
from sqlalchemy import literal_column
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.db_compat import is_sqlite, json_array_elements_subquery
from wikimind.models import (
    Article,
    ArticleResponse,
    ArticleSourceSummary,
    ArticleSummaryResponse,
    Backlink,
    BacklinkEntry,
    Concept,
    GraphEdge,
    GraphNode,
    GraphResponse,
    PageType,
    RelationType,
    Source,
    SourceResponse,
)
from wikimind.services.embedding import _SEARCH_AVAILABLE, get_embedding_service
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()


def _first_concept(concept_ids_json: str | None) -> str | None:
    """Extract the first concept name from a JSON-encoded concept_ids field.

    Used to assign ``GraphNode.concept_cluster`` — the primary concept
    that colors the node in the knowledge graph (ADR-012).

    Args:
        concept_ids_json: Raw JSON string from ``Article.concept_ids``.

    Returns:
        The first concept name, or ``None`` if the field is empty/malformed.
    """
    items = _parse_source_ids(concept_ids_json)
    return items[0] if items else None


def _read_article_content(file_path: str) -> str:
    """Read article markdown content from disk.

    Args:
        file_path: Absolute path to the article markdown file.

    Returns:
        The file content, or an empty string if the file cannot be read.
    """
    try:
        return resolve_wiki_path(file_path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_source_ids(raw: str | None) -> list[str]:
    """Parse the JSON-encoded ``Article.source_ids`` field into a list of IDs.

    Returns an empty list when the field is missing, empty, or malformed.
    Malformed values are logged but never raised so a single broken record
    cannot break listing or search responses.

    Args:
        raw: Raw JSON string stored on :attr:`Article.source_ids`.

    Returns:
        List of source UUID strings (possibly empty).
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Failed to parse Article.source_ids JSON", raw=raw)
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


async def _fetch_sources(session: AsyncSession, source_ids: list[str]) -> list[Source]:
    """Fetch :class:`Source` records for a list of source IDs, preserving order.

    Missing rows (e.g. a source was deleted after the article was compiled)
    are silently dropped — callers receive only the sources that still
    exist in the database.

    Args:
        session: Async database session.
        source_ids: List of source UUIDs to fetch.

    Returns:
        Source records in the same order as ``source_ids``, with any
        missing IDs omitted.
    """
    if not source_ids:
        return []
    result = await session.execute(select(Source).where(Source.id.in_(source_ids)))  # type: ignore[attr-defined]
    by_id = {s.id: s for s in result.scalars().all()}
    return [by_id[sid] for sid in source_ids if sid in by_id]


def _to_source_response(source: Source) -> SourceResponse:
    """Project a :class:`Source` row into the API-facing :class:`SourceResponse`."""
    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
        source_url=source.source_url,
        ingested_at=source.ingested_at,
    )


def _to_source_summary(source: Source) -> ArticleSourceSummary:
    """Project a :class:`Source` row into the lightweight summary form."""
    return ArticleSourceSummary(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
    )


async def _build_article_summary(article: Article, session: AsyncSession) -> ArticleSummaryResponse:
    """Build an :class:`ArticleSummaryResponse` for list and search payloads.

    Args:
        article: The article ORM row.
        session: Async database session used to fetch the article's sources.

    Returns:
        Summary response with a minimal source list attached.
    """
    source_ids = _parse_source_ids(article.source_ids)
    sources = await _fetch_sources(session, source_ids)
    backlink_count = len(article.backlinks_in) + len(article.backlinks_out)
    return ArticleSummaryResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        confidence=article.confidence,
        linter_score=article.linter_score,
        page_type=PageType(article.page_type),
        sources=[_to_source_summary(s) for s in sources],
        source_count=len(sources),
        backlink_count=backlink_count,
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


KEYWORD_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6


def _merge_hybrid_scores(
    keyword_scores: dict[str, float],
    semantic_results: list,
) -> dict[str, float]:
    """Merge keyword and semantic scores into a single ranked score map.

    Each article receives a combined score:
        ``KEYWORD_WEIGHT * keyword_score + SEMANTIC_WEIGHT * best_semantic_score``

    Semantic results may contain multiple chunks per article; only the
    highest-scoring chunk per article is used.

    Args:
        keyword_scores: Mapping of article_id to normalised keyword score [0, 1].
        semantic_results: List of :class:`SemanticSearchResult` from ChromaDB.

    Returns:
        Mapping of article_id to combined hybrid score.
    """
    # Best semantic score per article
    semantic_by_article: dict[str, float] = {}
    for sr in semantic_results:
        current = semantic_by_article.get(sr.article_id, 0.0)
        if sr.score > current:
            semantic_by_article[sr.article_id] = sr.score

    all_ids = set(keyword_scores) | set(semantic_by_article)
    merged: dict[str, float] = {}
    for aid in all_ids:
        kw = keyword_scores.get(aid, 0.0)
        sem = semantic_by_article.get(aid, 0.0)
        merged[aid] = KEYWORD_WEIGHT * kw + SEMANTIC_WEIGHT * sem

    return merged


class WikiService:
    """Provide article retrieval, search, graph building, and health reporting."""

    async def list_articles(
        self,
        session: AsyncSession,
        concept: str | None = None,
        confidence: str | None = None,
        page_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ArticleSummaryResponse]:
        """List wiki articles with optional filtering by concept, confidence, or page_type.

        Each returned summary embeds a lightweight list of source
        descriptors so callers can show provenance directly in listing
        views without fetching the full article.

        Args:
            session: Async database session.
            concept: Optional concept name to filter by. Uses SQLite
                ``json_each()`` to unnest ``Article.concept_ids`` and
                match against the requested concept name.
            confidence: Optional confidence level filter.
            page_type: Optional page type filter (source, concept, answer, index, meta).
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of :class:`ArticleSummaryResponse` records with sources
            populated.
        """
        query = select(Article).offset(offset).limit(limit)
        if concept:
            settings = get_settings()
            dialect = "sqlite" if is_sqlite(settings.database_url) else "postgresql"
            from_clause, value_ref = json_array_elements_subquery(dialect, "article", "concept_ids")
            query = query.where(
                literal_column("article.id").in_(
                    select(literal_column("article.id")).select_from(from_clause).where(value_ref == concept)
                )
            )
        if confidence:
            query = query.where(Article.confidence == confidence)
        if page_type:
            query = query.where(Article.page_type == page_type)
        result = await session.execute(query)
        articles = list(result.scalars().all())
        return [await _build_article_summary(a, session) for a in articles]

    async def get_article(self, id_or_slug: str, session: AsyncSession) -> ArticleResponse:
        """Retrieve a full article by ID or slug.

        Tries the article's UUID first (resolved wikilinks travel by ID
        via the ``[text](/wiki/<id>)`` markdown format). Falls back to
        slug lookup for backward compatibility with external bookmarks
        and the human-facing URL bar.

        The returned response embeds full :class:`SourceResponse` records
        for every raw source the article was compiled from. Sources that
        no longer exist in the database (e.g. deleted after compilation)
        are silently omitted.

        Args:
            id_or_slug: Either an ``Article.id`` UUID or an ``Article.slug``.
            session: Async database session.

        Returns:
            :class:`ArticleResponse` with content, backlink, and source data.

        Raises:
            HTTPException: If no article matches either lookup.
        """
        # Try ID first
        result = await session.execute(select(Article).where(Article.id == id_or_slug))
        article = result.scalar_one_or_none()
        if article is None:
            # Fall back to slug
            result = await session.execute(select(Article).where(Article.slug == id_or_slug))
            article = result.scalar_one_or_none()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        # Resolve incoming backlinks (articles that link TO this one)
        bl_in_result = await session.execute(
            select(Backlink.source_article_id, Article.title, Article.slug, Backlink.relation_type, Backlink.resolution)  # type: ignore[call-overload]
            .join(Article, Article.id == Backlink.source_article_id)  # type: ignore[arg-type]
            .where(Backlink.target_article_id == article.id)
        )
        backlinks_in = [
            BacklinkEntry(id=row[0], title=row[1], slug=row[2], relation_type=row[3], resolution=row[4])
            for row in bl_in_result.all()
        ]

        # Resolve outgoing backlinks (articles this one links TO)
        bl_out_result = await session.execute(
            select(Backlink.target_article_id, Article.title, Article.slug, Backlink.relation_type, Backlink.resolution)  # type: ignore[call-overload]
            .join(Article, Article.id == Backlink.target_article_id)  # type: ignore[arg-type]
            .where(Backlink.source_article_id == article.id)
        )
        backlinks_out = [
            BacklinkEntry(id=row[0], title=row[1], slug=row[2], relation_type=row[3], resolution=row[4])
            for row in bl_out_result.all()
        ]

        source_ids = _parse_source_ids(article.source_ids)
        sources = await _fetch_sources(session, source_ids)

        concepts = _parse_source_ids(article.concept_ids)

        return ArticleResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            summary=article.summary,
            confidence=article.confidence,
            linter_score=article.linter_score,
            page_type=article.page_type,
            concepts=concepts,
            backlinks_in=backlinks_in,
            backlinks_out=backlinks_out,
            content=_read_article_content(article.file_path),
            sources=[_to_source_response(s) for s in sources],
            created_at=article.created_at,
            updated_at=article.updated_at,
        )

    async def get_graph(self, session: AsyncSession) -> GraphResponse:
        """Build the full knowledge graph from articles and backlinks.

        Args:
            session: Async database session.

        Returns:
            GraphResponse containing nodes and edges.
        """
        # Backlinks are eager-loaded via selectin on Article.backlinks_out
        articles_result = await session.execute(select(Article))
        articles = articles_result.scalars().all()

        all_backlinks: list[Backlink] = []
        for a in articles:
            all_backlinks.extend(a.backlinks_out)

        connection_counts: dict[str, int] = {}
        for bl in all_backlinks:
            connection_counts[bl.source_article_id] = connection_counts.get(bl.source_article_id, 0) + 1
            connection_counts[bl.target_article_id] = connection_counts.get(bl.target_article_id, 0) + 1

        nodes = [
            GraphNode(
                id=a.id,
                label=a.title,
                concept_cluster=_first_concept(a.concept_ids),
                connection_count=connection_counts.get(a.id, 0),
                confidence=a.confidence,
            )
            for a in articles
        ]

        edges = [
            GraphEdge(
                source=bl.source_article_id,
                target=bl.target_article_id,
                context=bl.context,
                relation_type=RelationType(bl.relation_type),
                resolution=bl.resolution if bl.relation_type == "contradicts" else None,
            )
            for bl in all_backlinks
        ]

        return GraphResponse(nodes=nodes, edges=edges)

    async def search(
        self,
        q: str,
        session: AsyncSession,
        limit: int = 20,
    ) -> list[ArticleSummaryResponse]:
        """Hybrid search across wiki article titles and content.

        When semantic search extras are installed, combines keyword
        substring matching (weight 0.4) with ChromaDB vector similarity
        (weight 0.6). Falls back to keyword-only search otherwise.

        Returned summaries embed lightweight source descriptors so users
        can see at a glance which raw source(s) each matched article was
        compiled from.

        Args:
            q: Search query string (minimum 2 characters).
            session: Async database session.
            limit: Maximum number of results.

        Returns:
            Matching articles as :class:`ArticleSummaryResponse` records,
            ordered by relevance score.
        """
        keyword_scores = self._keyword_search(q, session)
        keyword_scores_map = await keyword_scores

        if _SEARCH_AVAILABLE:
            embedding_service = get_embedding_service()
            if embedding_service is not None:
                try:
                    semantic_results = embedding_service.search(q, limit=limit)
                    merged = _merge_hybrid_scores(keyword_scores_map, semantic_results)
                except Exception:
                    log.warning("Semantic search failed, falling back to keyword-only")
                    merged = keyword_scores_map
            else:
                merged = keyword_scores_map
        else:
            merged = keyword_scores_map

        # Sort by combined score descending
        ranked_ids = sorted(merged, key=merged.get, reverse=True)[:limit]  # type: ignore[arg-type]

        # Fetch article objects in ranked order
        if not ranked_ids:
            return []

        result = await session.execute(select(Article).where(Article.id.in_(ranked_ids)))  # type: ignore[attr-defined]
        articles_by_id = {a.id: a for a in result.scalars().all()}
        ordered = [articles_by_id[aid] for aid in ranked_ids if aid in articles_by_id]

        return [await _build_article_summary(a, session) for a in ordered]

    async def _keyword_search(
        self,
        q: str,
        session: AsyncSession,
    ) -> dict[str, float]:
        """Run keyword substring matching and return normalised scores by article id.

        Scores are normalised to [0, 1] so they can be combined with
        semantic similarity scores in the hybrid merge.

        Args:
            q: Search query string.
            session: Async database session.

        Returns:
            Mapping of article_id to normalised keyword score.
        """
        result = await session.execute(select(Article))
        all_articles = result.scalars().all()

        q_lower = q.lower()
        raw_scores: dict[str, int] = {}
        for article in all_articles:
            content = _read_article_content(article.file_path)
            if q_lower in article.title.lower() or q_lower in content.lower():
                score = 10 if q_lower in article.title.lower() else 0
                score += content.lower().count(q_lower)
                raw_scores[article.id] = score

        if not raw_scores:
            return {}

        max_score = max(raw_scores.values())
        if max_score == 0:
            return {aid: 0.0 for aid in raw_scores}

        return {aid: s / max_score for aid, s in raw_scores.items()}

    async def get_concepts(
        self,
        session: AsyncSession,
        include_empty: bool = True,
    ) -> list[Concept]:
        """Retrieve the concept taxonomy tree.

        Args:
            session: Async database session.
            include_empty: If False, exclude concepts with article_count == 0.

        Returns:
            List of Concept records.
        """
        query = select(Concept)
        if not include_empty:
            query = query.where(Concept.article_count > 0)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_health(self, session: AsyncSession) -> dict:
        """Return the latest wiki health report from the linter.

        If no linter run has been performed yet, returns a stub report
        with the current article count and a prompt to run the linter.

        Args:
            session: Async database session.

        Returns:
            Health report dict.
        """
        settings = get_settings()
        health_path = Path(settings.data_dir) / "wiki" / "_meta" / "health.json"

        if health_path.exists():
            return json.loads(health_path.read_text())

        articles_result = await session.execute(select(Article))
        articles = articles_result.scalars().all()

        return {
            "generated_at": None,
            "total_articles": len(articles),
            "total_sources": 0,
            "message": "Run the linter to generate a health report",
        }


_wiki_service: WikiService | None = None


def get_wiki_service() -> WikiService:
    """Return a singleton WikiService instance for FastAPI dependency injection."""
    global _wiki_service
    if _wiki_service is None:
        _wiki_service = WikiService()
    return _wiki_service
