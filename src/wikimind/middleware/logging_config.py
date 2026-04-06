"""Structured logging configuration for the WikiMind gateway.

Sets up *structlog* with a JSON renderer for production and a
human-readable console renderer for local development.  A custom
processor injects the current correlation ID into every log entry
and a sanitisation step strips sensitive values (API keys, tokens,
passwords) so they never appear in log output.

The log level is controlled by the ``LOG_LEVEL`` environment variable
(default: ``INFO``).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "authorization",
        "credential",
        "credentials",
    }
)

_SENSITIVE_PATTERN: re.Pattern[str] = re.compile(
    r"(sk-|ghp_|gho_|Bearer\s+)\S+",
    re.IGNORECASE,
)


def _sanitize_event_dict(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Remove or mask values that look like secrets."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
        elif isinstance(event_dict[key], str):
            event_dict[key] = _SENSITIVE_PATTERN.sub("***REDACTED***", event_dict[key])
    return event_dict


def configure_logging() -> None:
    """Initialise structlog and stdlib logging for the application.

    Call this once during application startup (inside the FastAPI
    lifespan context).
    """
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level: int = getattr(logging, log_level_name, logging.INFO)

    # Detect environment: JSON for production, pretty console for dev.
    is_dev = os.environ.get("WIKIMIND_ENV", "development").lower() == "development"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _sanitize_event_dict,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_dev:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quieten noisy third-party loggers.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(log_level, logging.WARNING))
