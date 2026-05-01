"""Tests for custom exception hierarchy."""

from wikimind.errors import (
    CompilationError,
    ConfigError,
    IngestError,
    NotFoundError,
    PermissionDeniedError,
    QueryError,
    UpstreamError,
    WikiMindError,
)


class TestWikiMindError:
    """Tests for the base WikiMindError."""

    def test_default_message(self):
        exc = WikiMindError()
        assert exc.message == "An unexpected error occurred"

    def test_custom_message(self):
        exc = WikiMindError("something broke")
        assert exc.message == "something broke"
        assert str(exc) == "something broke"

    def test_default_code(self):
        assert WikiMindError.code == "wikimind_error"

    def test_default_status_code(self):
        assert WikiMindError.status_code == 500


class TestIngestError:
    """Tests for IngestError."""

    def test_code(self):
        assert IngestError.code == "ingest_failed"

    def test_status_code(self):
        assert IngestError.status_code == 400

    def test_is_wikimind_error(self):
        assert issubclass(IngestError, WikiMindError)


class TestCompilationError:
    """Tests for CompilationError."""

    def test_code(self):
        assert CompilationError.code == "compilation_failed"

    def test_status_code(self):
        assert CompilationError.status_code == 500

    def test_is_wikimind_error(self):
        assert issubclass(CompilationError, WikiMindError)


class TestQueryError:
    """Tests for QueryError."""

    def test_code(self):
        assert QueryError.code == "query_failed"

    def test_status_code(self):
        assert QueryError.status_code == 400

    def test_is_wikimind_error(self):
        assert issubclass(QueryError, WikiMindError)


class TestConfigError:
    """Tests for ConfigError."""

    def test_code(self):
        assert ConfigError.code == "config_error"

    def test_status_code(self):
        assert ConfigError.status_code == 500

    def test_is_wikimind_error(self):
        assert issubclass(ConfigError, WikiMindError)


class TestNotFoundError:
    """Tests for NotFoundError."""

    def test_code(self):
        assert NotFoundError.code == "not_found"

    def test_status_code(self):
        assert NotFoundError.status_code == 404

    def test_is_wikimind_error(self):
        assert issubclass(NotFoundError, WikiMindError)

    def test_custom_message(self):
        exc = NotFoundError("Article not found")
        assert exc.message == "Article not found"
        assert str(exc) == "Article not found"


class TestPermissionDeniedError:
    """Tests for PermissionDeniedError."""

    def test_code(self):
        assert PermissionDeniedError.code == "permission_denied"

    def test_status_code(self):
        assert PermissionDeniedError.status_code == 403

    def test_is_wikimind_error(self):
        assert issubclass(PermissionDeniedError, WikiMindError)

    def test_custom_message(self):
        exc = PermissionDeniedError("Access denied")
        assert exc.message == "Access denied"
        assert str(exc) == "Access denied"


class TestUpstreamError:
    """Tests for UpstreamError."""

    def test_code(self):
        assert UpstreamError.code == "upstream_error"

    def test_status_code(self):
        assert UpstreamError.status_code == 502

    def test_is_wikimind_error(self):
        assert issubclass(UpstreamError, WikiMindError)

    def test_custom_message(self):
        exc = UpstreamError("LLM provider unavailable")
        assert exc.message == "LLM provider unavailable"
        assert str(exc) == "LLM provider unavailable"
