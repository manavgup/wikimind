"""Tests for the production Redis guard in jobs/background.py.

Covers _check_production_redis_guard() which raises ProductionConfigError
when FLY_APP_NAME is set but no Redis URL is configured.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wikimind.config import get_settings
from wikimind.jobs.background import (
    BackgroundCompiler,
    ProductionConfigError,
    _check_production_redis_guard,
)


def test_production_guard_raises_on_fly_without_redis(monkeypatch) -> None:
    """On Fly.io (FLY_APP_NAME set) without Redis URL, raises ProductionConfigError."""
    monkeypatch.setenv("FLY_APP_NAME", "wikimind-prod")
    get_settings.cache_clear()

    with patch("wikimind.jobs.background.get_settings") as mock_settings:
        mock_settings.return_value.redis_url = None
        with pytest.raises(ProductionConfigError, match="Production environment"):
            _check_production_redis_guard()


def test_production_guard_passes_on_fly_with_redis(monkeypatch) -> None:
    """On Fly.io with Redis configured, no exception."""
    monkeypatch.setenv("FLY_APP_NAME", "wikimind-prod")
    get_settings.cache_clear()

    with patch("wikimind.jobs.background.get_settings") as mock_settings:
        mock_settings.return_value.redis_url = "redis://localhost:6379"
        _check_production_redis_guard()  # should not raise


def test_production_guard_passes_locally_without_redis(monkeypatch) -> None:
    """Locally (no FLY_APP_NAME), no Redis is fine — uses in-process fallback."""
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    get_settings.cache_clear()

    with patch("wikimind.jobs.background.get_settings") as mock_settings:
        mock_settings.return_value.redis_url = None
        _check_production_redis_guard()  # should not raise


def test_background_compiler_is_prod_property() -> None:
    """is_prod returns True when redis_url is set."""
    bc = BackgroundCompiler()
    bc._redis_url = None
    assert bc.is_prod is False

    bc._redis_url = "redis://localhost:6379"
    assert bc.is_prod is True
