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

import asyncio
import functools
import json
from pathlib import Path

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.confidence import apply_decay
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleResponse,
    ArticleSource,
    ArticleSourceSummary,
    ArticleSummaryResponse,
    Backlink,
    BacklinkEntry,
    Concept,
    ConceptDetailResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    PageType,
    RelationType,
    Source,
    SourceResponse,
)
from wikimind.services.embedding import _SEARCH_AVAILABLE, get_embedding_service
from wikimind.storage import get_wiki_storage

log = structlog.get_logger()


def _effective_confidence(article: Article) -> float:
    """Decay an article's stored ``confidence_score`` based on staleness.

    Returns the base score unchanged when ``last_reinforced_at`` is unset
    (e.g. articles compiled before the field was introduced).
    """
    if article.last_reinforced_at is None:
        return article.confidence_score
    days = max(0, (utcnow_naive() - article.last_reinforced_at).days)
    return apply_decay(article.confidence_score, days)


def _first_concept(concept_ids_json: str | None) -> str | None:
    """Extract the first concept name from a JSON-encoded concept_ids field.

    Used to assign ``GraphNode.concept_cluster`` — the primary concept
    that colors the node in the knowledge graph (ADR-012).

    This is a legacy helper that still parses the JSON column for backward
    compatibility. New code should query the ``ArticleConcept`` join table.

    Args:
        concept_ids_json: Raw JSON string from ``Article.concept_ids``.

    Returns:
        The first concept name, or ``None`` if the field is empty/malformed.
    """
    items = _parse_source_ids(concept_ids_json)
    return items[0] if items else None


async def _read_article_content(file_path: str, user_id: str) -> str:
    """Read article markdown content from disk.

    Args:
        file_path: Relative path to the article markdown file.
        user_id: User ID for storage namespacing.

    Returns:
        The file content, or an empty string if the file cannot be read.
    """
    try:
        storage = get_wiki_storage(user_id)
        return await storage.read(file_path)
    except OSError:
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


async def _fetch_source_ids_from_join(session: AsyncSession, article_id: str) -> list[str]:
    """Fetch source IDs from the ArticleSource join table.

    Falls back to parsing the legacy JSON column if no join rows exist.
    """
    result = await session.execute(select(ArticleSource.source_id).where(ArticleSource.article_id == article_id))
    ids = [row[0] for row in result.all()]
    if ids:
        return ids
    # Fallback: read from legacy JSON column
    art_result = await session.execute(select(Article.source_ids).where(Article.id == article_id))
    row = art_result.first()
    return _parse_source_ids(row[0] if row else None)


async def _fetch_concept_names_from_join(session: AsyncSession, article_id: str) -> list[str]:
    """Fetch concept names from the ArticleConcept join table.

    Falls back to parsing the legacy JSON column if no join rows exist.
    """
    result = await session.execute(select(ArticleConcept.concept_name).where(ArticleConcept.article_id == article_id))
    names = [row[0] for row in result.all()]
    if names:
        return names
    # Fallback: read from legacy JSON column
    art_result = await session.execute(select(Article.concept_ids).where(Article.id == article_id))
    row = art_result.first()
    return _parse_source_ids(row[0] if row else None)


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
    source_ids = await _fetch_source_ids_from_join(session, article.id)
    concepts = await _fetch_concept_names_from_join(session, article.id)
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
        concepts=concepts,
        source_ids=source_ids,
        user_id=article.user_id,
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
        user_id: str,
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
            user_id: Optional user ID filter.

        Returns:
            List of :class:`ArticleSummaryResponse` records with sources
            populated.
        """
        query = select(Article).offset(offset).limit(limit)
        if user_id:
            query = query.where(Article.user_id == user_id)
        if concept:
            query = query.where(
                Article.id.in_(  # type: ignore[attr-defined]
                    select(ArticleConcept.article_id).where(ArticleConcept.concept_name == concept)
                )
            )
        if confidence:
            query = query.where(Article.confidence == confidence)
        if page_type:
            query = query.where(Article.page_type == page_type)
        result = await session.execute(query)
        articles = list(result.scalars().all())
        return [await _build_article_summary(a, session) for a in articles]

    async def get_article(self, id_or_slug: str, session: AsyncSession, user_id: str) -> ArticleResponse:
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
            user_id: Optional user ID filter.

        Returns:
            :class:`ArticleResponse` with content, backlink, and source data.

        Raises:
            NotFoundError: If no article matches either lookup.
        """
        # Try ID first
        id_stmt = select(Article).where(Article.id == id_or_slug)
        if user_id:
            id_stmt = id_stmt.where(Article.user_id == user_id)
        result = await session.execute(id_stmt)
        article = result.scalar_one_or_none()
        if article is None:
            # Fall back to slug
            slug_stmt = select(Article).where(Article.slug == id_or_slug)
            if user_id:
                slug_stmt = slug_stmt.where(Article.user_id == user_id)
            result = await session.execute(slug_stmt)
            article = result.scalar_one_or_none()
        if not article:
            msg = "Article not found"
            raise NotFoundError(msg)

        # Resolve incoming backlinks (articles that link TO this one)
        bl_in_result = await session.execute(
            select(Backlink.source_article_id, Article.title, Article.slug, Backlink.relation_type, Backlink.resolution)  # type: ignore[call-overload]
            .join(Article, Article.id == Backlink.source_article_id)
            .where(Backlink.target_article_id == article.id)
        )
        backlinks_in = [
            BacklinkEntry(id=row[0], title=row[1], slug=row[2], relation_type=row[3], resolution=row[4])
            for row in bl_in_result.all()
        ]

        # Resolve outgoing backlinks (articles this one links TO)
        bl_out_result = await session.execute(
            select(Backlink.target_article_id, Article.title, Article.slug, Backlink.relation_type, Backlink.resolution)  # type: ignore[call-overload]
            .join(Article, Article.id == Backlink.target_article_id)
            .where(Backlink.source_article_id == article.id)
        )
        backlinks_out = [
            BacklinkEntry(id=row[0], title=row[1], slug=row[2], relation_type=row[3], resolution=row[4])
            for row in bl_out_result.all()
        ]

        source_ids = await _fetch_source_ids_from_join(session, article.id)
        sources = await _fetch_sources(session, source_ids)

        concepts = await _fetch_concept_names_from_join(session, article.id)

        return ArticleResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            summary=article.summary,
            confidence=article.confidence,
            linter_score=article.linter_score,
            confidence_score=article.confidence_score,
            effective_confidence=_effective_confidence(article),
            page_type=article.page_type,
            concepts=concepts,
            backlinks_in=backlinks_in,
            backlinks_out=backlinks_out,
            content=await _read_article_content(article.file_path, user_id=article.user_id),
            sources=[_to_source_response(s) for s in sources],
            created_at=article.created_at,
            updated_at=article.updated_at,
        )

    async def get_graph(self, session: AsyncSession, user_id: str) -> GraphResponse:
        """Build the full knowledge graph from articles and backlinks.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            GraphResponse containing nodes and edges.
        """
        # Backlinks are eager-loaded via selectin on Article.backlinks_out
        graph_stmt = select(Article)
        if user_id:
            graph_stmt = graph_stmt.where(Article.user_id == user_id)
        articles_result = await session.execute(graph_stmt)
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
                confidence_score=a.confidence_score,
                effective_confidence=_effective_confidence(a),
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
        user_id: str,
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
            user_id: Optional user ID filter.

        Returns:
            Matching articles as :class:`ArticleSummaryResponse` records,
            ordered by relevance score.
        """
        keyword_scores = self._keyword_search(q, session, user_id=user_id)
        keyword_scores_map = await keyword_scores

        if _SEARCH_AVAILABLE:
            embedding_service = get_embedding_service()
            if embedding_service is not None:
                try:
                    semantic_results = embedding_service.search(
                        q,
                        limit=limit,
                        user_id=user_id,
                    )
                    merged = _merge_hybrid_scores(keyword_scores_map, semantic_results)
                except (RuntimeError, ValueError, OSError):
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
        user_id: str,
    ) -> dict[str, float]:
        """Run keyword substring matching and return normalised scores by article id.

        Scores are normalised to [0, 1] so they can be combined with
        semantic similarity scores in the hybrid merge.

        Args:
            q: Search query string.
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            Mapping of article_id to normalised keyword score.
        """
        kw_stmt = select(Article)
        if user_id:
            kw_stmt = kw_stmt.where(Article.user_id == user_id)
        result = await session.execute(kw_stmt)
        all_articles = result.scalars().all()

        q_lower = q.lower()
        raw_scores: dict[str, int] = {}
        for article in all_articles:
            content = await _read_article_content(article.file_path, user_id=article.user_id)
            if q_lower in article.title.lower() or q_lower in content.lower():
                score = 10 if q_lower in article.title.lower() else 0
                score += content.lower().count(q_lower)
                raw_scores[article.id] = score

        if not raw_scores:
            return {}

        max_score = max(raw_scores.values())
        if max_score == 0:
            return dict.fromkeys(raw_scores, 0.0)

        return {aid: s / max_score for aid, s in raw_scores.items()}

    async def get_concepts(
        self,
        session: AsyncSession,
        user_id: str,
        include_empty: bool = True,
    ) -> list[Concept]:
        """Retrieve the concept taxonomy tree.

        Args:
            session: Async database session.
            include_empty: If False, exclude concepts with article_count == 0.
            user_id: Optional user ID filter.

        Returns:
            List of Concept records.
        """
        query = select(Concept)
        if user_id:
            query = query.where(Concept.user_id == user_id)
        if not include_empty:
            query = query.where(Concept.article_count > 0)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_concept(
        self,
        name: str,
        session: AsyncSession,
        user_id: str,
    ) -> ConceptDetailResponse:
        """Retrieve a concept by name with its linked articles.

        Args:
            name: Concept name (case-sensitive).
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            ConceptDetailResponse with concept fields and linked articles list.

        Raises:
            NotFoundError: If concept not found.
        """
        query = select(Concept).where(Concept.name == name)
        if user_id:
            query = query.where(Concept.user_id == user_id)
        result = await session.execute(query)
        concept = result.scalar_one_or_none()
        if not concept:
            msg = f"Concept not found: {name}"
            raise NotFoundError(msg)

        articles = await self.list_articles(session=session, concept=name, user_id=user_id)
        return ConceptDetailResponse(
            id=concept.id,
            name=concept.name,
            description=concept.description,
            article_count=concept.article_count,
            parent_id=concept.parent_id,
            concept_kind=concept.concept_kind,
            created_at=concept.created_at,
            articles=articles,
        )

    async def get_concept_articles(
        self,
        name: str,
        session: AsyncSession,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ArticleSummaryResponse]:
        """List articles tagged with a specific concept.

        Args:
            name: Concept name to filter by.
            session: Async database session.
            limit: Max results.
            offset: Pagination offset.
            user_id: Optional user ID filter.

        Returns:
            List of article summaries for the concept.
        """
        return await self.list_articles(
            session=session,
            concept=name,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )

    async def get_health(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> dict:
        """Return the latest wiki health report from the linter.

        If no linter run has been performed yet, returns a stub report
        with the current article count and a prompt to run the linter.

        Args:
            session: Async database session.
            user_id: Optional user ID for path scoping.

        Returns:
            Health report dict.
        """
        settings = get_settings()
        health_dir = Path(settings.data_dir) / "wiki"
        if user_id:
            health_dir = health_dir / user_id
        health_path = health_dir / "_meta" / "health.json"

        if await asyncio.to_thread(health_path.exists):
            content = await asyncio.to_thread(health_path.read_text)
            return json.loads(content)

        article_stmt = select(Article)
        if user_id:
            article_stmt = article_stmt.where(Article.user_id == user_id)
        articles_result = await session.execute(article_stmt)
        articles = articles_result.scalars().all()

        return {
            "generated_at": None,
            "total_articles": len(articles),
            "total_sources": 0,
            "message": "Run the linter to generate a health report",
        }


@functools.lru_cache(maxsize=1)
def get_wiki_service() -> WikiService:
    """Return a singleton WikiService instance for FastAPI dependency injection."""
    return WikiService()
