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

import functools
import json
import re

import structlog
from fastapi import HTTPException
from slugify import slugify
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.confidence import apply_decay, compute_staleness
from wikimind.errors import NotFoundError
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleRelationshipsResponse,
    ArticleResponse,
    ArticleSource,
    ArticleSourceSummary,
    ArticleSummaryResponse,
    Backlink,
    BacklinkEntry,
    Concept,
    ConceptDetailResponse,
    Contradiction,
    ContradictionResolution,
    ContradictionStatus,
    CreateStubResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HealthSummaryResponse,
    Job,
    JobStatus,
    JobType,
    PageType,
    RecompileResponse,
    ReinforcementEvent,
    RelationshipEdge,
    RelationType,
    ResolveContradictionResponse,
    Source,
    SourceResponse,
    WikiHealthReport,
    WikilinkMatch,
)
from wikimind.services.embedding import _SEARCH_AVAILABLE, get_embedding_service
from wikimind.services.tags import get_tag_service
from wikimind.storage import get_wiki_storage, read_article_content

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


def _staleness_score(article: Article) -> float:
    """Compute the staleness score for an article.

    Returns ``1.0`` when ``last_reinforced_at`` is unset (legacy articles
    treated as maximally stale).
    """
    if article.last_reinforced_at is None:
        return 1.0
    days = (utcnow_naive() - article.last_reinforced_at).total_seconds() / 86400
    settings = get_settings()
    return compute_staleness(days, decay_rate=settings.staleness.decay_rate)


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
    result = await session.exec(select(Source).where(Source.id.in_(source_ids)))  # type: ignore[attr-defined]
    by_id = {s.id: s for s in result.all()}
    return [by_id[sid] for sid in source_ids if sid in by_id]


async def _fetch_source_ids_from_join(session: AsyncSession, article_id: str) -> list[str]:
    """Fetch source IDs from the ArticleSource join table.

    Falls back to parsing the legacy JSON column if no join rows exist.
    """
    result = await session.exec(select(ArticleSource.source_id).where(ArticleSource.article_id == article_id))
    ids = list(result.all())
    if ids:
        return ids
    # Fallback: read from legacy JSON column
    art_result = await session.exec(select(Article.source_ids).where(Article.id == article_id))
    val = art_result.first()
    return _parse_source_ids(val)


async def _fetch_concept_names_from_join(session: AsyncSession, article_id: str) -> list[str]:
    """Fetch concept names from the ArticleConcept join table.

    Falls back to parsing the legacy JSON column if no join rows exist.
    """
    result = await session.exec(select(ArticleConcept.concept_name).where(ArticleConcept.article_id == article_id))
    names = list(result.all())
    if names:
        return names
    # Fallback: read from legacy JSON column
    art_result = await session.exec(select(Article.concept_ids).where(Article.id == article_id))
    val = art_result.first()
    return _parse_source_ids(val)


async def _fetch_concepts_for_articles(
    session: AsyncSession,
    article_ids: list[str],
) -> dict[str, list[str]]:
    """Batch-fetch concept names for multiple articles from the join table.

    Returns a dict mapping article ID to the list of concept names.
    """
    result: dict[str, list[str]] = {aid: [] for aid in article_ids}
    if not article_ids:
        return result
    ac_result = await session.execute(
        select(ArticleConcept.article_id, ArticleConcept.concept_name).where(
            ArticleConcept.article_id.in_(article_ids)  # type: ignore[attr-defined]
        )
    )
    for row in ac_result.all():
        result[row[0]].append(row[1])
    return result


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
    tag_service = get_tag_service()
    tags = await tag_service.get_tags_for_article(session, article.id)
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
        confidence_score=article.confidence_score,
        effective_confidence=_effective_confidence(article),
        staleness_score=_staleness_score(article),
        concepts=concepts,
        tags=tags,
        source_ids=source_ids,
        user_id=article.user_id,
        manually_edited=article.manually_edited,
        is_stub=article.is_stub,
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
        article_ids: list[str] | None = None,
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
            article_ids: Optional list of article IDs to restrict results to.

        Returns:
            List of :class:`ArticleSummaryResponse` records with sources
            populated.
        """
        # Short-circuit: if article_ids filter is an empty list, return early
        if article_ids is not None and len(article_ids) == 0:
            return []
        query = select(Article).where(Article.user_id == user_id).offset(offset).limit(limit)
        if article_ids is not None:
            query = query.where(
                Article.id.in_(article_ids)  # type: ignore[attr-defined]
            )
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
        id_stmt = select(Article).where(Article.id == id_or_slug, Article.user_id == user_id)
        result = await session.execute(id_stmt)
        article = result.scalar_one_or_none()
        if article is None:
            # Fall back to slug
            slug_stmt = select(Article).where(Article.slug == id_or_slug, Article.user_id == user_id)
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

        tag_service = get_tag_service()
        tags = await tag_service.get_tags_for_article(session, article.id)

        return ArticleResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            summary=article.summary,
            confidence=article.confidence,
            linter_score=article.linter_score,
            confidence_score=article.confidence_score,
            effective_confidence=_effective_confidence(article),
            staleness_score=_staleness_score(article),
            page_type=article.page_type,
            concepts=concepts,
            tags=tags,
            backlinks_in=backlinks_in,
            backlinks_out=backlinks_out,
            content=await read_article_content(article.file_path, user_id=article.user_id),
            sources=[_to_source_response(s) for s in sources],
            created_at=article.created_at,
            updated_at=article.updated_at,
            manually_edited=article.manually_edited,
            edited_at=article.edited_at,
            is_stub=article.is_stub,
        )

    async def edit_article(
        self,
        id_or_slug: str,
        session: AsyncSession,
        user_id: str,
        content: str | None = None,
        title: str | None = None,
    ) -> ArticleResponse:
        """Manually edit an article's content and/or title.

        Writes the new content to the article's markdown file and updates
        the database record. Sets ``manually_edited=True`` and records
        ``edited_at`` so that recompilation can respect user edits.

        Args:
            id_or_slug: Article UUID or slug.
            session: Async database session.
            user_id: Authenticated user ID (must be the article owner).
            content: New markdown content (optional).
            title: New title (optional).

        Returns:
            Updated :class:`ArticleResponse`.

        Raises:
            NotFoundError: If the article does not exist for this user.
        """
        # No-op: nothing to change — return the article as-is without
        # poisoning the manually_edited flag.
        if content is None and title is None:
            return await self.get_article(id_or_slug, session, user_id=user_id)

        # Look up article by ID first, then slug
        id_stmt = select(Article).where(Article.id == id_or_slug)
        id_stmt = id_stmt.where(Article.user_id == user_id)
        result = await session.execute(id_stmt)
        article = result.scalar_one_or_none()
        if article is None:
            slug_stmt = select(Article).where(Article.slug == id_or_slug)
            slug_stmt = slug_stmt.where(Article.user_id == user_id)
            result = await session.execute(slug_stmt)
            article = result.scalar_one_or_none()
        if not article:
            msg = "Article not found"
            raise NotFoundError(msg)

        now = utcnow_naive()

        if content is not None:
            storage = get_wiki_storage(user_id)
            await storage.write(article.file_path, content)

        if title is not None:
            article.title = title

        article.manually_edited = True
        article.edited_at = now
        article.updated_at = now
        session.add(article)
        await session.commit()

        return await self.get_article(id_or_slug, session, user_id=user_id)

    async def _resolve_article_id(
        self,
        id_or_slug: str,
        session: AsyncSession,
        user_id: str,
    ) -> str | None:
        """Resolve an article id-or-slug reference to its canonical UUID id.

        Tries id-match first, then falls back to slug. Returns ``None`` when
        no article matches under the given user scope.
        """
        if not id_or_slug:
            return None
        id_stmt = select(Article.id).where(Article.id == id_or_slug, Article.user_id == user_id)
        row = (await session.execute(id_stmt)).first()
        if row is not None:
            return row[0]
        slug_stmt = select(Article.id).where(Article.slug == id_or_slug, Article.user_id == user_id)
        row = (await session.execute(slug_stmt)).first()
        return row[0] if row is not None else None

    async def get_random_article(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> ArticleSummaryResponse:
        """Return a random article belonging to the user.

        Args:
            session: Async database session.
            user_id: User ID to scope the query.

        Returns:
            A randomly selected article summary.

        Raises:
            NotFoundError: If the user has no articles.
        """
        query = select(Article).where(Article.user_id == user_id).order_by(func.random()).limit(1)
        result = await session.execute(query)
        article = result.scalar_one_or_none()
        if not article:
            msg = "No articles found"
            raise NotFoundError(msg)
        return await _build_article_summary(article, session)

    async def get_graph(
        self,
        session: AsyncSession,
        user_id: str,
        relation_type: RelationType | None = None,
        from_article: str | None = None,
        to_article: str | None = None,
    ) -> GraphResponse:
        """Build the knowledge graph, optionally filtered by relation type and endpoints.

        Filters compose with AND semantics and are pushed down into the SQL
        query so we never load and discard rows in Python.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.
            relation_type: If set, return only edges of this relation type.
            from_article: Optional source article id or slug. Resolved to an
                id under the same user scope.
            to_article: Optional target article id or slug. Resolved to an
                id under the same user scope.

        Returns:
            GraphResponse containing nodes (all visible articles for the
            user) and edges that satisfy every supplied filter.
        """
        # Resolve from/to references (id or slug) to canonical article ids.
        from_id: str | None = None
        to_id: str | None = None
        if from_article:
            from_id = await self._resolve_article_id(from_article, session, user_id)
            if from_id is None:
                # No such article — no edges can match.
                return GraphResponse(nodes=[], edges=[])
        if to_article:
            to_id = await self._resolve_article_id(to_article, session, user_id)
            if to_id is None:
                return GraphResponse(nodes=[], edges=[])

        # Push every filter into a single SQL query against Backlink.
        bl_stmt = select(Backlink).where(Backlink.user_id == user_id)
        if relation_type is not None:
            bl_stmt = bl_stmt.where(Backlink.relation_type == relation_type.value)
        if from_id is not None:
            bl_stmt = bl_stmt.where(Backlink.source_article_id == from_id)
        if to_id is not None:
            bl_stmt = bl_stmt.where(Backlink.target_article_id == to_id)
        bl_result = await session.execute(bl_stmt)
        backlinks = list(bl_result.scalars().all())

        # Articles for node list — full set per user scope so the graph
        # remains visually consistent across edge filters.
        graph_stmt = select(Article).where(Article.user_id == user_id)
        articles_result = await session.execute(graph_stmt)
        articles = articles_result.scalars().all()

        connection_counts: dict[str, int] = {}
        for bl in backlinks:
            connection_counts[bl.source_article_id] = connection_counts.get(bl.source_article_id, 0) + 1
            connection_counts[bl.target_article_id] = connection_counts.get(bl.target_article_id, 0) + 1

        # Batch-load all concept names per article from the join table so
        # the frontend can filter on every concept, not just the primary one.
        concepts_by_article = await _fetch_concepts_for_articles(session, [a.id for a in articles])

        nodes = [
            GraphNode(
                id=a.id,
                label=a.title,
                concept_cluster=_first_concept(a.concept_ids),
                concepts=concepts_by_article.get(a.id, []),
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
            for bl in backlinks
        ]

        return GraphResponse(nodes=nodes, edges=edges)

    async def get_relationships(
        self,
        id_or_slug: str,
        session: AsyncSession,
        user_id: str,
    ) -> ArticleRelationshipsResponse:
        """Return typed relationships for a single article, grouped by direction.

        Args:
            id_or_slug: Article UUID or slug.
            session: Async database session.
            user_id: User scope for both the article lookup and the joined
                article rows on the other side of each edge.

        Returns:
            :class:`ArticleRelationshipsResponse` with ``incoming`` and
            ``outgoing`` maps from relation type to edge lists.

        Raises:
            NotFoundError: If the article does not exist for this user.
        """
        article_id = await self._resolve_article_id(id_or_slug, session, user_id)
        if article_id is None:
            msg = "Article not found"
            raise NotFoundError(msg)

        # Outgoing: this article is the source. Join target Article for metadata.
        out_stmt = (
            select(  # type: ignore[call-overload]
                Backlink.target_article_id,
                Article.slug,
                Article.title,
                Backlink.relation_type,
                Backlink.context,
                Backlink.resolution,
            )
            .join(Article, Article.id == Backlink.target_article_id)
            .where(Backlink.source_article_id == article_id, Article.user_id == user_id)
        )
        out_rows = (await session.execute(out_stmt)).all()

        # Incoming: this article is the target. Join source Article for metadata.
        in_stmt = (
            select(  # type: ignore[call-overload]
                Backlink.source_article_id,
                Article.slug,
                Article.title,
                Backlink.relation_type,
                Backlink.context,
                Backlink.resolution,
            )
            .join(Article, Article.id == Backlink.source_article_id)
            .where(Backlink.target_article_id == article_id, Article.user_id == user_id)
        )
        in_rows = (await session.execute(in_stmt)).all()

        outgoing: dict[str, list[RelationshipEdge]] = {}
        for other_id, other_slug, other_title, rel, ctx, resolution in out_rows:
            edge = RelationshipEdge(
                article_id=other_id,
                slug=other_slug,
                title=other_title,
                relation_type=RelationType(rel),
                context=ctx,
                resolution=resolution,
            )
            outgoing.setdefault(rel, []).append(edge)

        incoming: dict[str, list[RelationshipEdge]] = {}
        for other_id, other_slug, other_title, rel, ctx, resolution in in_rows:
            edge = RelationshipEdge(
                article_id=other_id,
                slug=other_slug,
                title=other_title,
                relation_type=RelationType(rel),
                context=ctx,
                resolution=resolution,
            )
            incoming.setdefault(rel, []).append(edge)

        return ArticleRelationshipsResponse(incoming=incoming, outgoing=outgoing)

    async def refresh_article(
        self,
        id_or_slug: str,
        session: AsyncSession,
        user_id: str,
    ) -> Article:
        """Mark an article as "still current" via a manual refresh.

        Creates a ``manual_refresh`` :class:`ReinforcementEvent`, updates
        ``Article.last_reinforced_at``, and returns the updated article.

        Args:
            id_or_slug: Article UUID or slug.
            session: Async database session.
            user_id: User ID performing the refresh.

        Returns:
            The updated :class:`Article` instance.

        Raises:
            NotFoundError: If the article does not exist for this user.
        """
        article_id = await self._resolve_article_id(id_or_slug, session, user_id)
        if article_id is None:
            msg = "Article not found"
            raise NotFoundError(msg)

        article = await session.get(Article, article_id)
        if article is None:
            msg = "Article not found"
            raise NotFoundError(msg)

        now = utcnow_naive()
        article.last_reinforced_at = now
        session.add(article)

        event = ReinforcementEvent(
            article_id=article.id,
            event_type="manual_refresh",
            occurred_at=now,
            user_id=user_id,
        )
        session.add(event)

        await session.commit()
        await session.refresh(article)
        return article

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

        result = await session.exec(select(Article).where(Article.id.in_(ranked_ids)))  # type: ignore[attr-defined]
        articles_by_id = {a.id: a for a in result.all()}
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
        kw_stmt = select(Article).where(Article.user_id == user_id)
        result = await session.execute(kw_stmt)
        all_articles = result.scalars().all()

        q_lower = q.lower()
        raw_scores: dict[str, int] = {}
        for article in all_articles:
            content = await read_article_content(article.file_path, user_id=article.user_id)
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
        query = select(Concept).where(Concept.user_id == user_id)
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
        query = select(Concept).where(Concept.name == name, Concept.user_id == user_id)
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
    ) -> WikiHealthReport:
        """Return the latest wiki health report from the linter.

        If no linter run has been performed yet, returns a stub report
        with the current article count and a prompt to run the linter.

        Args:
            session: Async database session.
            user_id: Optional user ID for path scoping.

        Returns:
            Typed WikiHealthReport.
        """
        storage = get_wiki_storage(user_id)
        health_relative = "_meta/health.json"

        if await storage.exists(health_relative):
            content = await storage.read(health_relative)
            return WikiHealthReport(**json.loads(content))

        article_stmt = select(Article).where(Article.user_id == user_id)
        articles_result = await session.execute(article_stmt)
        articles = articles_result.scalars().all()

        return WikiHealthReport(
            generated_at=None,
            total_articles=len(articles),
            total_sources=0,
            message="Run the linter to generate a health report",
        )

    async def _generate_unique_slug(
        self,
        title: str,
        session: AsyncSession,
        user_id: str,
    ) -> str:
        """Generate a URL-safe slug from a title, avoiding collisions per user.

        Tries the base slug first; if it already exists for this user,
        appends ``-2``, ``-3``, etc. until a unique value is found.
        """
        base = slugify(title, max_length=80)
        candidate = base
        suffix = 2
        while True:
            existing = (
                (
                    await session.execute(
                        select(Article).where(
                            Article.slug == candidate,
                            Article.user_id == user_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1

    async def create_stub_article(
        self,
        title: str,
        body_markdown: str,
        session: AsyncSession,
        user_id: str,
    ) -> CreateStubResponse:
        """Create a stub wiki article.

        A stub is a user-created placeholder page for a concept that has
        no compiled source yet. The article is written to disk as a minimal
        markdown file and stored in the database with ``is_stub=True``.

        Args:
            title: Article title.
            body_markdown: Optional body markdown content.
            session: Async database session.
            user_id: Owner user ID.

        Returns:
            :class:`CreateStubResponse` with the new article's id, slug, and title.
        """
        slug = await self._generate_unique_slug(title, session, user_id)

        # Write markdown file to disk
        relative_path = f"stubs/{slug}.md"
        storage = get_wiki_storage(user_id)
        content = f'---\ntitle: "{title}"\nslug: {slug}\npage_type: source\nis_stub: true\n---\n\n'
        if body_markdown:
            content += body_markdown
        await storage.write(relative_path, content)

        # Create database record
        article = Article(
            slug=slug,
            title=title,
            file_path=relative_path,
            page_type=PageType.SOURCE,
            is_stub=True,
            user_id=user_id,
        )
        session.add(article)
        await session.commit()
        await session.refresh(article)

        return CreateStubResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            is_stub=True,
        )

    async def resolve_wikilinks(
        self,
        query: str,
        session: AsyncSession,
        user_id: str,
        limit: int = 10,
    ) -> list[WikilinkMatch]:
        """Search articles by partial title for wikilink autocomplete.

        Case-insensitive partial match against article titles.

        Args:
            query: Partial title string to search for.
            session: Async database session.
            user_id: User scope.
            limit: Maximum number of matches to return.

        Returns:
            List of matching :class:`WikilinkMatch` entries.
        """
        # Strip [[ ]] wrapper if present
        q = query.strip().strip("[").strip("]").strip()
        if not q:
            return []

        stmt = (
            select(Article)
            .where(Article.user_id == user_id)
            .where(func.lower(Article.title).contains(q.lower()))
            .order_by(Article.title)
            .limit(limit)
        )
        result = await session.execute(stmt)
        articles = result.scalars().all()
        return [
            WikilinkMatch(
                id=a.id,
                slug=a.slug,
                title=a.title,
                is_stub=a.is_stub,
            )
            for a in articles
        ]

    async def process_wikilinks(
        self,
        markdown: str,
        session: AsyncSession,
        user_id: str,
    ) -> str:
        """Resolve ``[[article title]]`` patterns in markdown content.

        Finds all ``[[...]]`` patterns and replaces them:
        - If a matching article exists: ``[title](/wiki/articles/{slug})``
        - If no match: leaves the ``[[title]]`` as-is (the frontend renders
          these as red/stub links).

        Args:
            markdown: Raw markdown content.
            session: Async database session.
            user_id: User scope.

        Returns:
            Markdown with resolved wikilinks replaced by standard links.
        """
        pattern = re.compile(r"\[\[([^\]]+)\]\]")
        matches = pattern.findall(markdown)
        if not matches:
            return markdown

        # Load all articles for this user once
        stmt = select(Article).where(Article.user_id == user_id)
        result = await session.execute(stmt)
        all_articles = list(result.scalars().all())

        by_lower: dict[str, Article] = {}
        for article in all_articles:
            lower_key = article.title.lower()
            if lower_key not in by_lower:
                by_lower[lower_key] = article

        def replace_wikilink(match: re.Match) -> str:
            title = match.group(1).strip()
            target = by_lower.get(title.lower())
            if target is not None:
                return f"[{title}](/wiki/articles/{target.slug})"
            # Leave unresolved — frontend renders as red link
            return match.group(0)

        return pattern.sub(replace_wikilink, markdown)

    async def get_health_summary(
        self,
        session: AsyncSession,
        user_id: str,
        linter_service: object,
    ) -> HealthSummaryResponse:
        """Return a lightweight health summary from the latest lint report.

        Falls back to a stub response with the article count when no lint
        report exists or the linter service raises.

        Args:
            session: Async database session.
            user_id: User scope.
            linter_service: A LinterService instance (typed as object to
                avoid circular imports).

        Returns:
            :class:`HealthSummaryResponse`.
        """
        try:
            detail = await linter_service.get_latest(session, user_id=user_id)  # type: ignore[attr-defined]
            return HealthSummaryResponse(
                generated_at=detail.report.generated_at,
                total_articles=detail.report.article_count,
                total_findings=detail.report.total_findings,
                contradictions_count=detail.report.contradictions_count,
                orphans_count=detail.report.orphans_count,
                status=detail.report.status,
            )
        except (HTTPException, SQLAlchemyError):
            count_result = await session.execute(select(func.count()).select_from(Article))
            return HealthSummaryResponse(
                total_articles=count_result.scalar() or 0,
                message="Run the linter to generate a health report",
            )

    async def resolve_legacy_contradiction(
        self,
        source_id: str,
        target_id: str,
        resolution: str,
        resolution_note: str | None,
        session: AsyncSession,
        user_id: str,
    ) -> ResolveContradictionResponse:
        """Resolve a contradiction via the deprecated backlink-based endpoint.

        Updates matching Backlink records and forwards the resolution to the
        Contradiction table (single source of truth).

        Args:
            source_id: Source article ID.
            target_id: Target article ID.
            resolution: Resolution string (must be a valid ContradictionResolution value).
            resolution_note: Optional note explaining the resolution.
            session: Async database session.
            user_id: User performing the resolution.

        Returns:
            :class:`ResolveContradictionResponse`.

        Raises:
            HTTPException: 422 if resolution is invalid, 404 if no backlink found.
        """
        valid = {r.value for r in ContradictionResolution}
        if resolution not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"resolution must be one of {sorted(valid)}",
            )

        # Check both directions — the finding's article_a/article_b order may not
        # match the backlink's source/target order.
        backlinks: list[Backlink] = []
        for src, tgt in [(source_id, target_id), (target_id, source_id)]:
            result = await session.execute(
                select(Backlink).where(
                    Backlink.source_article_id == src,
                    Backlink.target_article_id == tgt,
                    Backlink.relation_type == RelationType.CONTRADICTS,
                )
            )
            bl = result.scalars().first()
            if bl:
                backlinks.append(bl)
        if not backlinks:
            raise HTTPException(status_code=404, detail="Contradiction backlink not found")

        now = utcnow_naive()
        for bl in backlinks:
            bl.resolution = resolution
            bl.resolution_note = resolution_note
            bl.resolved_at = now
            bl.resolved_by = "user"
            session.add(bl)

        # Forward resolution to the Contradiction table (single source of truth)
        ids = sorted([source_id, target_id])
        ctr_result = await session.execute(
            select(Contradiction).where(
                Contradiction.user_id == user_id,
                Contradiction.status == ContradictionStatus.ACTIVE,
                Contradiction.article_a_id.in_(ids),  # type: ignore[attr-defined]
                Contradiction.article_b_id.in_(ids),  # type: ignore[attr-defined]
            )
        )
        for ctr in ctr_result.scalars().all():
            ctr.status = ContradictionStatus.RESOLVED
            ctr.resolution = resolution
            ctr.resolved_at = now
            ctr.resolved_by = user_id
            session.add(ctr)

        await session.commit()

        return ResolveContradictionResponse(
            resolved=True,
            source_id=source_id,
            target_id=target_id,
            resolution=resolution,
        )

    async def recompile_article(
        self,
        article_id: str,
        session: AsyncSession,
        user_id: str,
        mode: str | None = None,
        force: bool = False,
    ) -> RecompileResponse:
        """Schedule an async recompilation job for an article.

        If the article has been manually edited (``manually_edited=True``),
        raises 409 Conflict unless ``force=True``. When forced, the manual
        edits flag is cleared before recompilation.

        Args:
            article_id: Article UUID to recompile.
            session: Async database session.
            user_id: Owner user ID.
            mode: "source" or "concept" (auto-detected from page_type if None).
            force: If True, overwrite manual edits.

        Returns:
            :class:`RecompileResponse` with status and job_id.

        Raises:
            HTTPException: 404 if article not found, 409 if manually edited
                without force, 422 if mode is invalid.
        """
        valid_modes = {"source", "concept"}
        page_type_to_mode = {
            PageType.SOURCE: "source",
            PageType.CONCEPT: "concept",
            PageType.ANSWER: "source",
            PageType.INDEX: "source",
            PageType.META: "source",
            PageType.SYNTHESIS: "source",
        }

        if mode is not None and mode not in valid_modes:
            raise HTTPException(
                status_code=422,
                detail=f"mode must be one of {sorted(valid_modes)} or null",
            )

        result = await session.exec(select(Article).where(Article.id == article_id, Article.user_id == user_id))
        article = result.one_or_none()
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")

        if article.manually_edited and not force:
            raise HTTPException(
                status_code=409,
                detail="Article has manual edits. Use force=true to overwrite.",
            )

        # Clear manual edit flag when force-recompiling
        if article.manually_edited and force:
            article.manually_edited = False
            article.edited_at = None
            session.add(article)
            await session.commit()

        effective_mode = mode or page_type_to_mode.get(PageType(article.page_type), "source")

        job = Job(
            job_type=JobType.RECOMPILE_ARTICLE,
            status=JobStatus.QUEUED,
            source_id=article_id,
            user_id=user_id,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        compiler = get_background_compiler()
        await compiler.schedule_recompile(article_id, effective_mode, job.id, user_id=user_id)

        return RecompileResponse(status="scheduled", job_id=job.id)


@functools.lru_cache(maxsize=1)
def get_wiki_service() -> WikiService:
    """Return a singleton WikiService instance for FastAPI dependency injection."""
    return WikiService()
