"""Tests for service-layer modules: ingest, compiler, query, wiki services."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from wikimind.config import get_settings
from wikimind.models import (
    Article,
    Backlink,
    IngestStatus,
    Job,
    Query,
    QueryRequest,
    Source,
    SourceType,
)
from wikimind.services import (
    compiler as compiler_mod,
)
from wikimind.services import (
    ingest as ingest_mod,
)
from wikimind.services import (
    query as query_mod,
)
from wikimind.services import (
    wiki as wiki_mod,
)
from wikimind.services.compiler import CompilerService, get_compiler_service
from wikimind.services.ingest import IngestService, get_ingest_service
from wikimind.services.query import QueryService, get_query_service
from wikimind.services.wiki import WikiService, get_wiki_service

# ----- IngestService -----


async def test_ingest_service_url_error(db_session) -> None:
    svc = IngestService()
    svc._adapter = MagicMock()
    svc._adapter.ingest_url = AsyncMock(side_effect=ValueError("bad"))
    with pytest.raises(HTTPException):
        await svc.ingest_url("http://x", db_session)


async def test_ingest_service_url_success(db_session) -> None:
    svc = IngestService()
    src = Source(source_type=SourceType.URL, source_url="http://x", id="src1")
    svc._adapter = MagicMock()
    svc._adapter.ingest_url = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        gbc.return_value.schedule_compile = AsyncMock(return_value="job-1")
        result = await svc.ingest_url("http://x", db_session)
    assert result is src


async def test_ingest_service_pdf_and_text(db_session) -> None:
    svc = IngestService()
    src = Source(source_type=SourceType.PDF, id="s1")
    svc._adapter = MagicMock()
    svc._adapter.ingest_pdf = AsyncMock(return_value=src)
    svc._adapter.ingest_text = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        gbc.return_value.schedule_compile = AsyncMock(return_value="j")
        await svc.ingest_pdf(b"x", "f.pdf", db_session)
        await svc.ingest_text("c", "t", db_session)


# ----- IngestService: auto_compile=False short-circuits scheduling (issue #81) -----


async def test_ingest_service_url_auto_compile_false_skips_schedule(db_session) -> None:
    """auto_compile=False must NOT enqueue a compile job for URL ingest."""
    svc = IngestService()
    src = Source(source_type=SourceType.URL, source_url="http://x", id="src-url")
    svc._adapter = MagicMock()
    svc._adapter.ingest_url = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        schedule_compile = AsyncMock(return_value="job-1")
        gbc.return_value.schedule_compile = schedule_compile
        result = await svc.ingest_url("http://x", db_session, auto_compile=False)
    assert result is src
    schedule_compile.assert_not_awaited()


async def test_ingest_service_pdf_auto_compile_false_skips_schedule(db_session) -> None:
    """auto_compile=False must NOT enqueue a compile job for PDF ingest."""
    svc = IngestService()
    src = Source(source_type=SourceType.PDF, id="src-pdf")
    svc._adapter = MagicMock()
    svc._adapter.ingest_pdf = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        schedule_compile = AsyncMock(return_value="job-2")
        gbc.return_value.schedule_compile = schedule_compile
        result = await svc.ingest_pdf(b"x", "f.pdf", db_session, auto_compile=False)
    assert result is src
    schedule_compile.assert_not_awaited()


async def test_ingest_service_text_auto_compile_false_skips_schedule(db_session) -> None:
    """auto_compile=False must NOT enqueue a compile job for text ingest."""
    svc = IngestService()
    src = Source(source_type=SourceType.TEXT, id="src-text")
    svc._adapter = MagicMock()
    svc._adapter.ingest_text = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        schedule_compile = AsyncMock(return_value="job-3")
        gbc.return_value.schedule_compile = schedule_compile
        result = await svc.ingest_text("hello", "t", db_session, auto_compile=False)
    assert result is src
    schedule_compile.assert_not_awaited()


async def test_ingest_service_text_auto_compile_default_schedules(db_session) -> None:
    """Default behavior (auto_compile omitted) must still schedule a compile."""
    svc = IngestService()
    src = Source(source_type=SourceType.TEXT, id="src-default")
    svc._adapter = MagicMock()
    svc._adapter.ingest_text = AsyncMock(return_value=src)
    with patch("wikimind.services.ingest.get_background_compiler") as gbc:
        schedule_compile = AsyncMock(return_value="job-4")
        gbc.return_value.schedule_compile = schedule_compile
        await svc.ingest_text("hello", "t", db_session)
    schedule_compile.assert_awaited_once_with("src-default")


async def test_ingest_route_text_auto_compile_false_skips_schedule(client) -> None:
    """End-to-end: POST /ingest/text with auto_compile=False must not schedule."""
    fake_src = Source(source_type=SourceType.TEXT, id="route-text", title="x")
    svc = get_ingest_service()
    with (
        patch.object(svc, "_adapter") as adapter,
        patch("wikimind.services.ingest.get_background_compiler") as gbc,
    ):
        adapter.ingest_text = AsyncMock(return_value=fake_src)
        schedule_compile = AsyncMock(return_value="job-r1")
        gbc.return_value.schedule_compile = schedule_compile
        resp = await client.post(
            "/ingest/text",
            json={"content": "hello", "title": "x", "auto_compile": False},
        )
    assert resp.status_code == 200
    schedule_compile.assert_not_awaited()


async def test_ingest_route_url_auto_compile_false_skips_schedule(client) -> None:
    """End-to-end: POST /ingest/url with auto_compile=False must not schedule."""
    fake_src = Source(source_type=SourceType.URL, id="route-url", source_url="http://x")
    svc = get_ingest_service()
    with (
        patch.object(svc, "_adapter") as adapter,
        patch("wikimind.services.ingest.get_background_compiler") as gbc,
    ):
        adapter.ingest_url = AsyncMock(return_value=fake_src)
        schedule_compile = AsyncMock(return_value="job-r2")
        gbc.return_value.schedule_compile = schedule_compile
        resp = await client.post(
            "/ingest/url",
            json={"url": "http://x", "auto_compile": False},
        )
    assert resp.status_code == 200
    schedule_compile.assert_not_awaited()


async def test_ingest_route_pdf_auto_compile_false_skips_schedule(client) -> None:
    """End-to-end: POST /ingest/pdf?auto_compile=false must not schedule."""
    fake_src = Source(source_type=SourceType.PDF, id="route-pdf", title="f")
    svc = get_ingest_service()
    with (
        patch.object(svc, "_adapter") as adapter,
        patch("wikimind.services.ingest.get_background_compiler") as gbc,
    ):
        adapter.ingest_pdf = AsyncMock(return_value=fake_src)
        schedule_compile = AsyncMock(return_value="job-r3")
        gbc.return_value.schedule_compile = schedule_compile
        resp = await client.post(
            "/ingest/pdf?auto_compile=false",
            files={"file": ("doc.pdf", b"%PDF-1.4...", "application/pdf")},
        )
    assert resp.status_code == 200
    schedule_compile.assert_not_awaited()


async def test_ingest_service_list_sources(db_session) -> None:
    svc = IngestService()
    db_session.add(Source(source_type=SourceType.TEXT, title="t", status=IngestStatus.PENDING))
    await db_session.commit()
    result = await svc.list_sources(db_session)
    assert len(result) == 1
    result = await svc.list_sources(db_session, status="pending")
    assert len(result) == 1


async def test_ingest_service_get_source_missing(db_session) -> None:
    svc = IngestService()
    with pytest.raises(HTTPException):
        await svc.get_source("nope", db_session)


async def test_ingest_service_get_source_ok(db_session) -> None:
    svc = IngestService()
    s = Source(source_type=SourceType.TEXT, title="t")
    db_session.add(s)
    await db_session.commit()
    got = await svc.get_source(s.id, db_session)
    assert got.id == s.id


async def test_ingest_service_delete_source(db_session, tmp_path, monkeypatch) -> None:
    svc = IngestService()
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    raw = tmp_path / "raw"
    raw.mkdir()
    s = Source(source_type=SourceType.PDF, title="t", file_path=str(raw / "x.txt"))
    (raw / f"{s.id}.txt").write_text("content")
    (raw / f"{s.id}.pdf").write_bytes(b"x")
    s.file_path = str(raw / f"{s.id}.txt")
    db_session.add(s)
    await db_session.commit()
    result = await svc.delete_source(s.id, db_session)
    assert result["deleted"] == s.id


async def test_ingest_service_delete_missing(db_session) -> None:
    svc = IngestService()
    with pytest.raises(HTTPException):
        await svc.delete_source("nope", db_session)


def test_ingest_service_singleton() -> None:
    ingest_mod._ingest_service = None
    a = get_ingest_service()
    assert a is get_ingest_service()


# ----- CompilerService -----


async def test_compiler_service_list_jobs(db_session) -> None:
    svc = CompilerService()
    j = Job(job_type="compile_source", status="queued")
    db_session.add(j)
    await db_session.commit()
    jobs = await svc.list_jobs(db_session)
    assert len(jobs) == 1
    jobs = await svc.list_jobs(db_session, status="queued")
    assert len(jobs) == 1


async def test_compiler_service_get_job(db_session) -> None:
    svc = CompilerService()
    j = Job(job_type="compile_source", status="queued")
    db_session.add(j)
    await db_session.commit()
    got = await svc.get_job(j.id, db_session)
    assert got is not None


async def test_compiler_service_triggers() -> None:
    svc = CompilerService()
    with patch("wikimind.services.compiler.get_background_compiler") as gbc:
        gbc.return_value.schedule_compile = AsyncMock(return_value="j1")
        gbc.return_value.schedule_lint = AsyncMock(return_value="j2")
        a = await svc.trigger_compile("src")
        b = await svc.trigger_lint()
    assert a["status"] == "queued"
    assert b["status"] == "queued"
    r = await svc.trigger_reindex()
    assert r["status"] == "queued"


def test_compiler_service_singleton() -> None:
    compiler_mod._compiler_service = None
    assert get_compiler_service() is get_compiler_service()


# ----- QueryService -----


async def test_query_service_ask(db_session) -> None:
    svc = QueryService()
    fake_query = Query(
        question="q",
        answer="a",
        confidence="high",
        source_article_ids=json.dumps([]),
        related_article_ids=json.dumps([]),
    )
    db_session.add(fake_query)
    await db_session.commit()
    svc._qa_agent = MagicMock()
    svc._qa_agent.answer = AsyncMock(return_value=fake_query)
    resp = await svc.ask(QueryRequest(question="q"), db_session)
    assert resp.answer == "a"


async def test_query_service_history(db_session) -> None:
    svc = QueryService()
    db_session.add(
        Query(question="q", answer="a", confidence="high", source_article_ids="[]", related_article_ids="[]")
    )
    await db_session.commit()
    h = await svc.query_history(db_session)
    assert len(h) == 1


async def test_query_service_file_back_missing(db_session) -> None:
    svc = QueryService()
    with pytest.raises(HTTPException):
        await svc.file_back("nope", db_session)


async def test_query_service_file_back_ok(db_session) -> None:
    svc = QueryService()
    q = Query(
        question="q",
        answer="a",
        confidence="high",
        source_article_ids=json.dumps([]),
        related_article_ids=json.dumps([]),
    )
    db_session.add(q)
    await db_session.commit()
    svc._qa_agent = MagicMock()
    svc._qa_agent._file_back = AsyncMock(return_value="art-1")
    result = await svc.file_back(q.id, db_session)
    assert result["filed"] is True


def test_query_service_singleton() -> None:
    query_mod._query_service = None
    assert get_query_service() is get_query_service()


# ----- WikiService -----


async def test_wiki_list_articles(db_session, tmp_path) -> None:
    svc = WikiService()
    f = tmp_path / "a.md"
    f.write_text("body")
    db_session.add(Article(slug="a", title="A", file_path=str(f)))
    await db_session.commit()
    arts = await svc.list_articles(db_session)
    assert len(arts) == 1
    arts = await svc.list_articles(db_session, confidence="sourced")
    assert isinstance(arts, list)


async def test_wiki_get_article_missing(db_session) -> None:
    svc = WikiService()
    with pytest.raises(HTTPException):
        await svc.get_article("nope", db_session)


async def test_wiki_get_article_ok(db_session, tmp_path) -> None:
    svc = WikiService()
    f = tmp_path / "a.md"
    f.write_text("hello body")
    src = Source(source_type=SourceType.URL, title="src")
    db_session.add(src)
    await db_session.flush()
    art = Article(slug="a", title="A", file_path=str(f), source_ids=json.dumps([src.id]))
    db_session.add(art)
    await db_session.commit()
    resp = await svc.get_article("a", db_session)
    assert resp.title == "A"
    assert len(resp.sources) == 1


async def test_wiki_get_graph(db_session, tmp_path) -> None:
    svc = WikiService()
    f = tmp_path / "a.md"
    f.write_text("body")
    a1 = Article(slug="a", title="A", file_path=str(f))
    a2 = Article(slug="b", title="B", file_path=str(f))
    db_session.add_all([a1, a2])
    await db_session.flush()
    db_session.add(Backlink(source_article_id=a1.id, target_article_id=a2.id, context="x"))
    await db_session.commit()
    g = await svc.get_graph(db_session)
    assert len(g.nodes) == 2


async def test_wiki_search(db_session, tmp_path) -> None:
    svc = WikiService()
    f = tmp_path / "a.md"
    f.write_text("python is fun python rocks")
    db_session.add(Article(slug="a", title="Python", file_path=str(f)))
    db_session.add(Article(slug="b", title="Other", file_path=str(f)))
    await db_session.commit()
    results = await svc.search("python", db_session)
    assert len(results) >= 1


async def test_wiki_get_concepts(db_session) -> None:
    svc = WikiService()
    c = await svc.get_concepts(db_session)
    assert c == []


async def test_wiki_get_health_default(db_session) -> None:
    svc = WikiService()
    h = await svc.get_health(db_session)
    assert "total_articles" in h


async def test_wiki_get_health_from_file(db_session, tmp_path, monkeypatch) -> None:
    svc = WikiService()
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    meta = tmp_path / "wiki" / "_meta"
    meta.mkdir(parents=True)
    (meta / "health.json").write_text(json.dumps({"foo": "bar"}))
    h = await svc.get_health(db_session)
    assert h["foo"] == "bar"


def test_wiki_service_singleton() -> None:
    wiki_mod._wiki_service = None
    assert get_wiki_service() is get_wiki_service()
