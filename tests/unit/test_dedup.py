"""Tests for content-hash dedup at the ingest layer (issue #67).

Covers:
- TextAdapter / PDFAdapter dedup hits and misses
- Hash is stable across re-ingest of identical content
- Different content produces different hashes (no false positives)
- Compiler.save_article: same-provider replace, different-provider stack
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fitz
import pytest
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import Settings, get_settings
from wikimind.engine import compiler as compiler_module
from wikimind.engine.compiler import Compiler
from wikimind.ingest import service as ingest_service
from wikimind.ingest.service import (
    PDFAdapter,
    TextAdapter,
    compute_hash,
    find_source_by_hash,
    reconstruct_normalized_doc,
)
from wikimind.jobs import background as bg
from wikimind.models import (
    Article,
    CompilationResult,
    CompiledClaim,
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    Provider,
    Source,
    SourceType,
)
from wikimind.services import ingest as svc_ingest
from wikimind.services.ingest import IngestService
from wikimind.storage import get_raw_storage, get_wiki_storage, resolve_raw_path

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _build_pdf_bytes(pages: list[str]) -> bytes:
    """Build a tiny in-memory PDF with one page per string."""
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body)
    data = doc.tobytes()
    doc.close()
    return bytes(data)


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `get_settings().data_dir` at a tmp directory for one test."""
    fake_settings = Settings(data_dir=str(tmp_path), vision_enabled=False)
    monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(compiler_module, "get_settings", lambda: fake_settings)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()


def _sample_compilation_result(title: str = "Sample") -> CompilationResult:
    """Build a minimal CompilationResult that satisfies all required fields."""
    return CompilationResult(
        title=title,
        summary="A two-sentence summary. It exists for testing.",
        key_claims=[CompiledClaim(claim="The sky is blue", confidence=ConfidenceLevel.SOURCED)],
        concepts=["test-concept"],
        backlink_suggestions=[],
        open_questions=[],
        article_body="## Body\n\nSome markdown body content for the test." * 20,
    )


# ---------------------------------------------------------------------------
# compute_hash + find_source_by_hash unit tests
# ---------------------------------------------------------------------------


class TestComputeHash:
    """The hashing helper is deterministic and content-sensitive."""

    def test_identical_bytes_produce_identical_hash(self) -> None:
        a = compute_hash(b"hello world")
        b = compute_hash(b"hello world")
        assert a == b
        assert len(a) == 64  # SHA-256 hex

    def test_different_bytes_produce_different_hash(self) -> None:
        assert compute_hash(b"hello world") != compute_hash(b"hello world!")

    def test_one_byte_difference_produces_different_hash(self) -> None:
        assert compute_hash(b"abc") != compute_hash(b"abd")


class TestFindSourceByHash:
    """`find_source_by_hash` returns None when nothing matches."""

    async def test_returns_none_when_no_match(self, db_session) -> None:
        result = await find_source_by_hash(db_session, "deadbeef" * 8)
        assert result is None

    async def test_returns_source_when_present(self, db_session) -> None:
        digest = compute_hash(b"some content")
        source = Source(
            source_type=SourceType.TEXT,
            title="seed",
            content_hash=digest,
            status=IngestStatus.PROCESSING,
        )
        db_session.add(source)
        await db_session.commit()

        found = await find_source_by_hash(db_session, digest)
        assert found is not None
        assert found.id == source.id


# ---------------------------------------------------------------------------
# TextAdapter dedup behavior
# ---------------------------------------------------------------------------


class TestTextAdapterDedup:
    """Pasting the same text twice yields a single Source row."""

    async def test_second_ingest_returns_existing_source(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        adapter = TextAdapter()
        body = "The mitochondrion is the powerhouse of the cell."

        first, _ = await adapter.ingest(body, "Bio note", db_session)
        second, _ = await adapter.ingest(body, "Bio note again", db_session)

        assert first.id == second.id
        assert first.content_hash == compute_hash(body.encode("utf-8"))

    async def test_different_text_creates_separate_sources(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        adapter = TextAdapter()

        first, _ = await adapter.ingest("Content one", "A", db_session)
        second, _ = await adapter.ingest("Content two", "A", db_session)

        assert first.id != second.id
        assert first.content_hash != second.content_hash

    async def test_dedup_hit_does_not_overwrite_disk_files(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        """A dedup hit must not touch the cached `.txt` file."""
        adapter = TextAdapter()
        body = "Stable text content."

        first, _ = await adapter.ingest(body, "first", db_session)
        text_path = resolve_raw_path(first.file_path)
        first_mtime = text_path.stat().st_mtime_ns

        second, _ = await adapter.ingest(body, "second", db_session)

        assert second.id == first.id
        assert text_path.stat().st_mtime_ns == first_mtime


# ---------------------------------------------------------------------------
# PDFAdapter dedup behavior
# ---------------------------------------------------------------------------


class TestPDFAdapterDedup:
    """Re-uploading the same PDF returns the existing Source."""

    async def test_same_pdf_dedupes(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)
        adapter = PDFAdapter()
        pdf_bytes = _build_pdf_bytes(["Identical PDF content"])

        first, _ = await adapter.ingest(pdf_bytes, "doc.pdf", db_session)
        second, _ = await adapter.ingest(pdf_bytes, "doc-renamed.pdf", db_session)

        assert first.id == second.id
        assert first.content_hash == compute_hash(pdf_bytes)

    async def test_different_pdfs_do_not_dedupe(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)
        adapter = PDFAdapter()
        first_pdf = _build_pdf_bytes(["Page A"])
        second_pdf = _build_pdf_bytes(["Page B"])

        first, _ = await adapter.ingest(first_pdf, "a.pdf", db_session)
        second, _ = await adapter.ingest(second_pdf, "b.pdf", db_session)

        assert first.id != second.id
        assert first.content_hash != second.content_hash


# ---------------------------------------------------------------------------
# reconstruct_normalized_doc — used on dedup hits
# ---------------------------------------------------------------------------


class TestReconstructNormalizedDoc:
    """The dedup-hit return path rebuilds a NormalizedDocument from disk."""

    async def test_rebuilds_from_cached_text(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        adapter = TextAdapter()
        body = "Cached body content."
        source, _ = await adapter.ingest(body, "title", db_session)

        doc = reconstruct_normalized_doc(source)

        assert doc.raw_source_id == source.id
        assert doc.clean_text == body
        assert doc.title == "title"
        assert doc.chunks  # at least one chunk

    def test_raises_when_file_path_missing(self) -> None:
        source = Source(source_type=SourceType.TEXT, title="x", file_path=None)
        with pytest.raises(ValueError, match="no file_path"):
            reconstruct_normalized_doc(source)


# ---------------------------------------------------------------------------
# Compiler.save_article — replace vs stack by provider
# ---------------------------------------------------------------------------


class TestCompilerSaveArticle:
    """Same provider replaces in place; different providers stack."""

    async def _seed_source(self, session) -> Source:
        source = Source(
            source_type=SourceType.TEXT,
            title="Seed",
            status=IngestStatus.PROCESSING,
            content_hash="seedhash",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        return source

    async def test_first_compile_creates_article_with_provider(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        source = await self._seed_source(db_session)
        compiler = Compiler()
        compiler._last_provider_used = Provider.ANTHROPIC

        article = await compiler.save_article(_sample_compilation_result(), source, db_session)

        assert article.provider == Provider.ANTHROPIC
        assert article.title == "Sample"
        assert source.status == IngestStatus.COMPILED

    async def test_same_provider_replaces_in_place(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        source = await self._seed_source(db_session)
        compiler = Compiler()
        compiler._last_provider_used = Provider.ANTHROPIC

        first = await compiler.save_article(
            _sample_compilation_result(title="First Title"),
            source,
            db_session,
        )
        first_id = first.id
        first_slug = first.slug

        # Re-compile with the same provider — should replace, not stack
        second = await compiler.save_article(
            _sample_compilation_result(title="Second Title"),
            source,
            db_session,
        )

        assert second.id == first_id
        assert second.slug == first_slug  # slug stable across replace
        assert second.title == "Second Title"
        assert second.provider == Provider.ANTHROPIC

        # Only one article in DB
        result = await db_session.execute(select(Article))
        assert len(result.scalars().all()) == 1

    async def test_different_provider_stacks_as_separate_article(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        source = await self._seed_source(db_session)
        compiler = Compiler()

        compiler._last_provider_used = Provider.ANTHROPIC
        anthropic_article = await compiler.save_article(
            _sample_compilation_result(title="Anthropic Take"),
            source,
            db_session,
        )

        compiler._last_provider_used = Provider.OPENAI
        openai_article = await compiler.save_article(
            _sample_compilation_result(title="OpenAI Take"),
            source,
            db_session,
        )

        assert anthropic_article.id != openai_article.id
        assert anthropic_article.slug != openai_article.slug
        assert anthropic_article.provider == Provider.ANTHROPIC
        assert openai_article.provider == Provider.OPENAI

        result = await db_session.execute(select(Article))
        assert len(result.scalars().all()) == 2

    async def test_no_tracked_provider_falls_back_to_create(
        self,
        db_session,
        isolated_data_dir: Path,
    ) -> None:
        """When `_last_provider_used` is None we always create."""
        source = await self._seed_source(db_session)
        compiler = Compiler()
        compiler._last_provider_used = None

        first = await compiler.save_article(_sample_compilation_result(), source, db_session)
        # Reset compiler state, save again — should NOT replace because we
        # can't match by provider.
        compiler._last_provider_used = None
        second = await compiler.save_article(
            _sample_compilation_result(title="Second"),
            source,
            db_session,
        )

        assert first.id != second.id
        assert first.provider is None
        assert second.provider is None


# ---------------------------------------------------------------------------
# compile() captures the provider from the LLM response
# ---------------------------------------------------------------------------


class TestServiceSkipsEnqueueOnDedupHit:
    """`IngestService` must skip compile-scheduling when dedup hits an existing source.

    Re-running the compiler on the same content with the same provider would
    produce identical output and waste LLM tokens — that's the whole point of
    content-hash dedup.
    """

    async def test_skips_compile_when_source_already_compiled(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seed the DB with an already-compiled source whose hash matches the
        # content we are about to ingest, so the adapter dedup hit path fires.
        body = "already compiled body"
        digest = compute_hash(body.encode("utf-8"))
        text_path = isolated_data_dir / "raw" / "seed.txt"
        text_path.write_text(body, encoding="utf-8")

        existing = Source(
            source_type=SourceType.TEXT,
            title="seed",
            content_hash=digest,
            status=IngestStatus.COMPILED,
            compiled_at=utcnow_naive(),
            file_path=str(text_path),
        )
        db_session.add(existing)
        await db_session.commit()

        # Capture every schedule_compile call so we can assert it never happens.
        calls: list[str] = []

        async def fake_schedule(source_id: str) -> str:
            calls.append(source_id)
            return "fake-job"

        fake_compiler = MagicMock()
        fake_compiler.schedule_compile = AsyncMock(side_effect=fake_schedule)
        monkeypatch.setattr(bg, "get_background_compiler", lambda: fake_compiler)
        monkeypatch.setattr(svc_ingest, "get_background_compiler", lambda: fake_compiler)

        service = IngestService()
        result = await service.ingest_text(body, title="dup", session=db_session)

        # Dedup hit returned the existing already-compiled source unchanged.
        assert result.id == existing.id
        # And no compile was scheduled — the whole point of dedup.
        assert calls == [], f"expected no schedule_compile calls, got {calls}"

    async def test_schedules_compile_for_fresh_source(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sanity check: a NEW (non-dedup) ingest still schedules a compile."""
        calls: list[str] = []

        async def fake_schedule(source_id: str) -> str:
            calls.append(source_id)
            return "fake-job"

        fake_compiler = MagicMock()
        fake_compiler.schedule_compile = AsyncMock(side_effect=fake_schedule)
        monkeypatch.setattr(bg, "get_background_compiler", lambda: fake_compiler)
        monkeypatch.setattr(svc_ingest, "get_background_compiler", lambda: fake_compiler)

        service = IngestService()
        result = await service.ingest_text("brand new content", title="x", session=db_session)

        assert calls == [result.id]


class TestCompilerProviderTracking:
    """`Compiler.compile` records the provider used for the most recent call."""

    async def test_compile_sets_last_provider_used(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        compiler = Compiler()

        fake_response = MagicMock()
        fake_response.provider_used = Provider.OPENAI
        fake_response.content = (
            '{"title": "T", "summary": "S1. S2.", "key_claims": [], '
            '"concepts": [], "backlink_suggestions": [], "open_questions": [], '
            '"article_body": "body"}'
        )

        compiler.router = MagicMock()
        compiler.router.complete = AsyncMock(return_value=fake_response)
        compiler.router.parse_json_response = MagicMock(
            return_value={
                "title": "T",
                "summary": "S1. S2.",
                "key_claims": [],
                "concepts": [],
                "backlink_suggestions": [],
                "open_questions": [],
                "article_body": "body",
            }
        )

        doc = NormalizedDocument(
            raw_source_id="x",
            clean_text="hello",
            title="T",
            estimated_tokens=1,
        )
        await compiler.compile(doc, db_session)

        assert compiler._last_provider_used == Provider.OPENAI
