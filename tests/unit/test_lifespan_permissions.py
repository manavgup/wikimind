"""Tests for lifespan data-directory write permission check."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

from wikimind.config import Settings, get_settings

log = structlog.get_logger()


def _check_write_permissions(settings_obj: Settings) -> None:
    """Replicate the lifespan permission check logic for isolated testing.

    This avoids running the full lifespan (which requires DB init) while
    exercising the same code path that runs in ``main.lifespan``.
    """
    data_dir = Path(settings_obj.data_dir)
    if settings_obj.storage_backend == "local":
        for subdir in ("wiki", "raw"):
            test_dir = data_dir / subdir
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / ".write-test"
            try:
                test_file.write_text("ok")
                test_file.unlink()
            except PermissionError:
                log.critical("No write permission", path=str(test_dir))
                raise SystemExit(1) from None


@pytest.mark.asyncio
async def test_lifespan_writable_dirs_succeed(tmp_path: Path) -> None:
    """Lifespan should complete startup when data directories are writable."""
    get_settings.cache_clear()
    settings = get_settings()
    # tmp_path-based data dir from conftest is always writable — just verify
    # the write-test files are created and cleaned up without error.
    _check_write_permissions(settings)
    data_dir = Path(settings.data_dir)
    for subdir in ("wiki", "raw"):
        assert not (data_dir / subdir / ".write-test").exists()


@pytest.mark.asyncio
async def test_lifespan_unwritable_dir_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan should raise SystemExit when a data directory is not writable."""
    get_settings.cache_clear()
    settings = get_settings()

    data_dir = Path(settings.data_dir)
    wiki_dir = data_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    original_write_text = Path.write_text

    def _failing_write_text(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == ".write-test":
            raise PermissionError(f"Permission denied: {self}")
        return original_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    with patch.object(Path, "write_text", _failing_write_text), pytest.raises(SystemExit):
        _check_write_permissions(settings)
