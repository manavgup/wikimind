"""End-to-end wikilink resolution proof (issue #95).

Steps:
    1. Seed an existing article "Existing Target".
    2. Drive the compiler's save path with a mock CompilationResult
       whose backlink_suggestions includes "Existing Target" (should
       resolve) and "Nonexistent Topic" (should stay unresolved).
    3. Assert a Backlink row exists pointing new -> target.
    4. Assert the rendered markdown has [Existing Target](/wiki/<id>).
    5. Assert the /wiki/articles/{id} route returns the new article
       (verifies the ID-first lookup works end-to-end).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.engine.compiler import Compiler
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompiledClaim,
    ConfidenceLevel,
    IngestStatus,
    Source,
    SourceType,
)
from wikimind.storage import resolve_wiki_path


@pytest.mark.asyncio
async def test_wikilink_resolution_end_to_end(
    db_session: AsyncSession,
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    # 1. Seed an existing target article
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-target",
        title="Existing Target",
        file_path=str(tmp_path / "existing-target.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)

    # Seed a Source the compiler will mark as COMPILED
    source = Source(
        id=str(uuid.uuid4()),
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.PROCESSING,
        ingested_at=utcnow_naive(),
    )
    db_session.add(source)
    await db_session.commit()

    # 2. Drive the save path
    compiler = Compiler()
    result = CompilationResult(
        title="New Compiled Article",
        summary="Two sentence summary. For integration test.",
        key_claims=[
            CompiledClaim(claim="test claim", confidence=ConfidenceLevel.SOURCED),
        ],
        concepts=["test"],
        backlink_suggestions=["Existing Target", "Nonexistent Topic"],
        open_questions=["test?"],
        article_body="## Body\n\nTest body content with enough text.",
    )
    article = await compiler.save_article(result, source, db_session)

    # 3. Backlink row exists
    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].target_article_id == target.id

    # 4. Markdown has the resolved link by ID and the unresolved bracket
    content = resolve_wiki_path(article.file_path).read_text()
    assert f"[Existing Target](/wiki/{target.id})" in content
    assert "[[Nonexistent Topic]]" in content

    # 5. ID-first lookup via the HTTP route
    response = await client.get(f"/wiki/articles/{article.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == article.id
    assert payload["title"] == "New Compiled Article"
    assert f"[Existing Target](/wiki/{target.id})" in payload["content"]

    # Slug-based lookup still works (backward compat)
    response_by_slug = await client.get(f"/wiki/articles/{article.slug}")
    assert response_by_slug.status_code == 200
    assert response_by_slug.json()["id"] == article.id
