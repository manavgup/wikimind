"""Tests for greenlet_spawn fix -- concept compilation uses separate session."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.engine.concept_compiler import ConceptCompiler
from wikimind.models import Article, Backlink, PageType, RelationType


@pytest.mark.asyncio
async def test_synthesizes_link_skips_existing(db_session: AsyncSession):
    """_create_synthesizes_links should not create duplicate Backlinks."""
    a1 = Article(
        id=str(uuid.uuid4()),
        slug="concept-test",
        title="Concept",
        file_path="/tmp/c.md",
        page_type=PageType.CONCEPT,
    )
    a2 = Article(
        id=str(uuid.uuid4()),
        slug="source-test",
        title="Source",
        file_path="/tmp/s.md",
        page_type=PageType.SOURCE,
    )
    db_session.add_all([a1, a2])

    # Pre-create a synthesizes link
    bl = Backlink(
        source_article_id=a1.id,
        target_article_id=a2.id,
        relation_type=RelationType.SYNTHESIZES,
        context="existing",
    )
    db_session.add(bl)
    await db_session.commit()

    compiler = ConceptCompiler()
    # Should NOT raise IntegrityError or create a duplicate
    await compiler._create_synthesizes_links(a1.id, [a2.id], db_session)

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == a1.id,
            Backlink.target_article_id == a2.id,
        )
    )
    links = list(result.scalars().all())
    assert len(links) == 1  # No duplicate


@pytest.mark.asyncio
async def test_related_to_link_skips_existing(db_session: AsyncSession):
    """_create_related_to_links should not create duplicate Backlinks."""
    a1 = Article(
        id=str(uuid.uuid4()),
        slug="concept-a",
        title="Concept A",
        file_path="/tmp/a.md",
        page_type=PageType.CONCEPT,
    )
    a2 = Article(
        id=str(uuid.uuid4()),
        slug="concept-b",
        title="Concept B",
        file_path="/tmp/b.md",
        page_type=PageType.CONCEPT,
    )
    db_session.add_all([a1, a2])

    # Pre-create a related_to link in one direction
    bl = Backlink(
        source_article_id=a1.id,
        target_article_id=a2.id,
        relation_type=RelationType.RELATED_TO,
        context="existing",
    )
    db_session.add(bl)
    await db_session.commit()

    compiler = ConceptCompiler()
    await compiler._create_related_to_links(a1, ["concept-b"], db_session)

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == a1.id,
            Backlink.target_article_id == a2.id,
        )
    )
    links = list(result.scalars().all())
    assert len(links) == 1  # No duplicate in forward direction
