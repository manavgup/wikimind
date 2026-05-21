"""Citation service — resolves compiled claims to their source spans.

Provides the data layer for span-level citations: given an article,
returns its compiled claims together with the source spans that anchor
each claim to a precise location in the original source document.
"""

import json

import structlog
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleCitationsResponse,
    ArticleClaimsResponse,
    ClaimCitationResponse,
    ClaimConfidenceResponse,
    CompiledClaim,
    SourceSpan,
    SourceSpanResponse,
)
from wikimind.services.wiki import WikiService

log = structlog.get_logger()


class CitationService:
    """Resolve compiled claims to their anchored source spans."""

    async def get_article_citations(
        self,
        id_or_slug: str,
        session: AsyncSession,
        *,
        user_id: str,
        wiki_service: WikiService,
    ) -> ArticleCitationsResponse:
        """Return all claims for an article with their linked source spans.

        Args:
            id_or_slug: Article UUID or slug.
            session: Async database session.
            user_id: Owner scope.
            wiki_service: WikiService for article resolution.

        Returns:
            ArticleCitationsResponse with claims and their source spans.

        Raises:
            NotFoundError: If the article does not exist for this user.
        """
        article_id = await wiki_service._resolve_article_id(id_or_slug, session, user_id)
        if article_id is None:
            msg = f"Article not found: {id_or_slug}"
            raise NotFoundError(msg)

        # Fetch article title
        article_row = (
            await session.execute(select(Article.title).where(Article.id == article_id, Article.user_id == user_id))
        ).first()
        article_title = article_row[0] if article_row else ""

        # Fetch all claims for this article
        claims_stmt = (
            select(CompiledClaim)
            .where(
                CompiledClaim.article_id == article_id,
                CompiledClaim.user_id == user_id,
            )
            .order_by(col(CompiledClaim.created_at))
        )
        claims = (await session.execute(claims_stmt)).scalars().all()

        # Collect all span IDs across claims for a single batch query
        all_span_ids: set[str] = set()
        for claim in claims:
            span_ids = json.loads(claim.source_span_ids) if claim.source_span_ids else []
            all_span_ids.update(span_ids)

        # Batch-fetch all referenced spans
        spans_by_id: dict[str, SourceSpan] = {}
        if all_span_ids:
            spans_stmt = select(SourceSpan).where(
                col(SourceSpan.id).in_(list(all_span_ids)),
                SourceSpan.user_id == user_id,
            )
            spans = (await session.execute(spans_stmt)).scalars().all()
            spans_by_id = {s.id: s for s in spans}

        # Build response
        claim_responses: list[ClaimCitationResponse] = []
        for claim in claims:
            span_ids = json.loads(claim.source_span_ids) if claim.source_span_ids else []
            source_ids = json.loads(claim.source_ids) if claim.source_ids else []
            span_responses = [
                SourceSpanResponse(
                    id=span.id,
                    source_id=span.source_id,
                    locator_kind=span.locator_kind,
                    locator=span.locator,
                    text=span.text,
                    fingerprint=span.fingerprint,
                    created_at=span.created_at,
                )
                for sid in span_ids
                if (span := spans_by_id.get(sid)) is not None
            ]
            claim_responses.append(
                ClaimCitationResponse(
                    id=claim.id,
                    text=claim.text,
                    confidence_level=claim.confidence_level,
                    confidence_score=claim.confidence_score,
                    source_ids=source_ids,
                    source_spans=span_responses,
                )
            )

        return ArticleCitationsResponse(
            article_id=article_id,
            article_title=article_title,
            claims=claim_responses,
        )

    async def get_article_claims(
        self,
        id_or_slug: str,
        session: AsyncSession,
        *,
        user_id: str,
        wiki_service: WikiService,
    ) -> ArticleClaimsResponse:
        """Return all persisted claims for an article with confidence scores.

        Unlike ``get_article_citations``, this endpoint focuses on the
        confidence scoring rather than source span anchoring (issue #465).

        Args:
            id_or_slug: Article UUID or slug.
            session: Async database session.
            user_id: Owner scope.
            wiki_service: WikiService for article resolution.

        Returns:
            ArticleClaimsResponse with claims and their confidence scores.

        Raises:
            NotFoundError: If the article does not exist for this user.
        """
        article_id = await wiki_service._resolve_article_id(id_or_slug, session, user_id)
        if article_id is None:
            msg = f"Article not found: {id_or_slug}"
            raise NotFoundError(msg)

        # Fetch article title and confidence_score
        article_row = (
            await session.execute(
                select(Article.title, Article.confidence_score).where(
                    Article.id == article_id,
                    Article.user_id == user_id,
                )
            )
        ).first()
        article_title = article_row[0] if article_row else ""
        article_confidence_score = article_row[1] if article_row else 0.5

        # Fetch all claims for this article
        claims_stmt = (
            select(CompiledClaim)
            .where(
                CompiledClaim.article_id == article_id,
                CompiledClaim.user_id == user_id,
            )
            .order_by(col(CompiledClaim.created_at))
        )
        claims = (await session.execute(claims_stmt)).scalars().all()

        claim_responses: list[ClaimConfidenceResponse] = []
        for claim in claims:
            source_ids = json.loads(claim.source_ids) if claim.source_ids else []
            claim_responses.append(
                ClaimConfidenceResponse(
                    id=claim.id,
                    text=claim.text,
                    confidence_level=claim.confidence_level,
                    confidence_score=claim.confidence_score,
                    source_ids=source_ids,
                    last_reinforced_at=claim.last_reinforced_at,
                    created_at=claim.created_at,
                )
            )

        return ArticleClaimsResponse(
            article_id=article_id,
            article_title=article_title,
            article_confidence_score=article_confidence_score,
            claims=claim_responses,
        )
