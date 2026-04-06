"""Custom exception hierarchy for WikiMind domain errors.

Each exception carries a machine-readable ``code`` attribute that maps to the
``error.code`` field in the standard JSON error envelope, making it easy for
clients to branch on error type without parsing human-readable messages.
"""


class WikiMindError(Exception):
    """Base exception for all WikiMind domain errors."""

    code: str = "wikimind_error"
    status_code: int = 500

    def __init__(self, message: str = "An unexpected error occurred") -> None:
        self.message = message
        super().__init__(message)


class IngestError(WikiMindError):
    """Raised when source ingestion fails (bad URL, parse failure, etc.)."""

    code: str = "ingest_failed"
    status_code: int = 400


class CompilationError(WikiMindError):
    """Raised when the LLM compiler cannot produce a wiki article."""

    code: str = "compilation_failed"
    status_code: int = 500


class QueryError(WikiMindError):
    """Raised when a user query cannot be answered (missing context, bad input)."""

    code: str = "query_failed"
    status_code: int = 400


class ConfigError(WikiMindError):
    """Raised when application configuration is invalid or missing."""

    code: str = "config_error"
    status_code: int = 500
