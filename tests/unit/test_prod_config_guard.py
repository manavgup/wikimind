"""Tests for production config guard — Redis required on Fly.io."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wikimind.jobs.background import (
    BackgroundCompiler,
    ProductionConfigError,
    _check_production_redis_guard,
)


class TestProductionRedisGuard:
    """Verify the startup guard enforces Redis on Fly.io."""

    def test_fly_without_redis_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When FLY_APP_NAME is set and redis_url is None, guard raises."""
        monkeypatch.setenv("FLY_APP_NAME", "wikimind")
        with patch("wikimind.jobs.background.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = None
            with pytest.raises(ProductionConfigError, match="requires Redis"):
                _check_production_redis_guard()

    def test_fly_with_redis_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When FLY_APP_NAME is set and redis_url is configured, no error."""
        monkeypatch.setenv("FLY_APP_NAME", "wikimind")
        with patch("wikimind.jobs.background.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://localhost:6379"
            # Should not raise
            _check_production_redis_guard()

    def test_local_without_redis_allows_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When FLY_APP_NAME is NOT set, in-process fallback is allowed."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        with patch("wikimind.jobs.background.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = None
            # Should not raise — local dev is fine without Redis
            _check_production_redis_guard()

    def test_background_compiler_init_checks_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BackgroundCompiler.__init__ triggers the guard."""
        monkeypatch.setenv("FLY_APP_NAME", "wikimind")
        with patch("wikimind.jobs.background.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = None
            with pytest.raises(ProductionConfigError):
                BackgroundCompiler()

    def test_background_compiler_arq_mode_on_fly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BackgroundCompiler uses ARQ mode when redis_url is configured."""
        monkeypatch.setenv("FLY_APP_NAME", "wikimind")
        with patch("wikimind.jobs.background.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://localhost:6379"
            compiler = BackgroundCompiler()
            assert compiler.is_prod is True
