"""Tests for core data models — enums, SQLModel tables, Pydantic schemas."""

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
        assert Provider.OLLAMA == "ollama"

    def test_job_status_values(self):
        assert JobStatus.QUEUED == "queued"
        assert JobStatus.COMPLETE == "complete"


class TestSourceModel:
    def test_create_source(self):
        source = Source(source_type=SourceType.URL, source_url="https://example.com")
        assert source.source_type == SourceType.URL
        assert source.source_url == "https://example.com"
        assert source.status == IngestStatus.PENDING
        assert source.id is not None

    def test_source_defaults(self):
        source = Source(source_type=SourceType.TEXT)
        assert source.title is None
        assert source.author is None
        assert source.token_count is None
        assert source.error_message is None


class TestArticleModel:
    def test_create_article(self):
        article = Article(slug="test-article", title="Test Article", file_path="/wiki/test.md")
        assert article.slug == "test-article"
        assert article.title == "Test Article"
        assert article.id is not None


class TestJobModel:
    def test_create_job(self):
        job = Job(job_type=JobType.COMPILE_SOURCE)
        assert job.job_type == JobType.COMPILE_SOURCE
        assert job.status == JobStatus.QUEUED
        assert job.priority == 5
