"""Tests for core data models — enums, SQLModel tables, Pydantic schemas."""

from pathlib import Path

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.models import (
    Article,
    ConfidenceLevel,
    IngestStatus,
    Job,
    JobStatus,
    JobType,
    Provider,
    Source,
    SourceType,
)


class TestEnums:
    def test_source_type_values(self):
        assert SourceType.URL == "url"
        assert SourceType.PDF == "pdf"
        assert SourceType.YOUTUBE == "youtube"
        assert SourceType.TEXT == "text"

    def test_ingest_status_values(self):
        assert IngestStatus.PENDING == "pending"
        assert IngestStatus.COMPILED == "compiled"
        assert IngestStatus.FAILED == "failed"

    def test_confidence_level_values(self):
        assert ConfidenceLevel.SOURCED == "sourced"
        assert ConfidenceLevel.INFERRED == "inferred"
        assert ConfidenceLevel.OPINION == "opinion"

    def test_provider_values(self):
        assert Provider.ANTHROPIC == "anthropic"
        assert Provider.OPENAI == "openai"
        assert Provider.OPENAI_COMPATIBLE == "openai_compatible"
        assert Provider.OLLAMA == "ollama"

    def test_job_status_values(self):
        assert JobStatus.QUEUED == "queued"
        assert JobStatus.COMPLETE == "complete"


class TestSourceModel:
    def test_create_source(self):
        source = Source(source_type=SourceType.URL, source_url="https://example.com", user_id=TEST_USER_ID)
        assert source.source_type == SourceType.URL
        assert source.source_url == "https://example.com"
        assert source.status == IngestStatus.PENDING
        assert source.id is not None

    def test_source_defaults(self):
        source = Source(source_type=SourceType.TEXT, user_id=TEST_USER_ID)
        assert source.title is None
        assert source.author is None
        assert source.token_count is None
        assert source.error_message is None


class TestArticleModel:
    def test_create_article(self):
        article = Article(slug="test-article", title="Test Article", file_path="/wiki/test.md", user_id=TEST_USER_ID)
        assert article.slug == "test-article"
        assert article.title == "Test Article"
        assert article.id is not None


class TestJobModel:
    def test_create_job(self):
        job = Job(job_type=JobType.COMPILE_SOURCE, user_id=TEST_USER_ID)
        assert job.job_type == JobType.COMPILE_SOURCE
        assert job.status == JobStatus.QUEUED
        assert job.priority == 5


def test_source_has_original_true_when_pdf_sibling_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """has_original is True when a non-.txt sibling exists in raw/."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw" / TEST_USER_ID
    raw_dir.mkdir(parents=True)
    (raw_dir / "src-1.txt").write_text("text")
    (raw_dir / "src-1.pdf").write_bytes(b"%PDF")
    source = Source(id="src-1", source_type=SourceType.PDF, file_path="src-1.txt", user_id=TEST_USER_ID)
    assert source.has_original is True
    get_settings.cache_clear()


def test_source_has_original_false_for_text_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """has_original is False when only the .txt exists."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw" / TEST_USER_ID
    raw_dir.mkdir(parents=True)
    (raw_dir / "src-2.txt").write_text("text")
    source = Source(id="src-2", source_type=SourceType.TEXT, file_path="src-2.txt", user_id=TEST_USER_ID)
    assert source.has_original is False
    get_settings.cache_clear()


def test_source_has_original_false_when_no_file_path() -> None:
    """has_original is False when file_path is None."""
    source = Source(id="src-3", source_type=SourceType.TEXT, user_id=TEST_USER_ID)
    assert source.has_original is False


def test_source_has_original_scopes_by_user_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """has_original uses the correct user-scoped raw directory."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw" / "user-abc"
    raw_dir.mkdir(parents=True)
    (raw_dir / "src-4.txt").write_text("text")
    (raw_dir / "src-4.pdf").write_bytes(b"%PDF")

    source = Source(id="src-4", source_type=SourceType.PDF, file_path="src-4.txt", user_id="user-abc")
    assert source.has_original is True
    get_settings.cache_clear()
