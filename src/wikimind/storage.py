"""File storage abstraction for wiki and raw source files.

Provides a protocol for async file operations and a local filesystem
implementation. In production, an R2/S3 implementation can be swapped
in via configuration without changing application code.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

from wikimind.config import get_settings

log = structlog.get_logger()


@runtime_checkable
class FileStorage(Protocol):
    """Async file storage interface."""

    async def read(self, relative_path: str) -> str:
        """Read text content from a file."""
        ...

    async def read_bytes(self, relative_path: str) -> bytes:
        """Read binary content from a file."""
        ...

    async def write(self, relative_path: str, content: str) -> None:
        """Write text content to a file, creating parent dirs as needed."""
        ...

    async def write_bytes(self, relative_path: str, data: bytes) -> None:
        """Write binary content to a file, creating parent dirs as needed."""
        ...

    async def append(self, relative_path: str, content: str) -> None:
        """Append text content to a file, creating it if it does not exist."""
        ...

    async def delete(self, relative_path: str) -> None:
        """Delete a file. No-op if the file does not exist."""
        ...

    async def exists(self, relative_path: str) -> bool:
        """Return True if the file exists."""
        ...

    async def list(self, prefix: str = "") -> list[str]:
        """List all files under the given prefix (or root if empty)."""
        ...


class LocalFileStorage:
    """Local filesystem implementation of FileStorage."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve(self, relative_path: str) -> Path:
        return self.root / relative_path

    async def read(self, relative_path: str) -> str:
        """Read text content from a file."""
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def read_bytes(self, relative_path: str) -> bytes:
        """Read binary content from a file."""
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.read_bytes)

    async def write(self, relative_path: str, content: str) -> None:
        """Write text content to a file, creating parent dirs as needed."""
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    async def write_bytes(self, relative_path: str, data: bytes) -> None:
        """Write binary content to a file, creating parent dirs as needed."""
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def append(self, relative_path: str, content: str) -> None:
        """Append text content to a file, creating it if it does not exist."""
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        def _append() -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(content)

        await asyncio.to_thread(_append)

    async def delete(self, relative_path: str) -> None:
        """Delete a file. No-op if the file does not exist."""
        path = self._resolve(relative_path)
        if path.exists():
            await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, relative_path: str) -> bool:
        """Return True if the file exists."""
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.exists)

    async def list(self, prefix: str = "") -> list[str]:
        """List all files under the given prefix (or root if empty)."""
        search_dir = self._resolve(prefix) if prefix else self.root

        def _list() -> list[str]:
            if not search_dir.exists():
                return []
            return [str(p.relative_to(self.root)) for p in search_dir.rglob("*") if p.is_file()]

        return await asyncio.to_thread(_list)


def _make_r2_storage(prefix: str) -> FileStorage:
    """Create an R2FileStorage instance with the given key prefix.

    Uses lazy import to avoid pulling boto3 when running local.
    """
    from wikimind.storage_r2 import R2FileStorage  # noqa: PLC0415

    settings = get_settings()
    if not settings.r2_bucket:
        msg = "WIKIMIND_R2_BUCKET must be set when storage_backend=r2"
        raise ValueError(msg)
    if not settings.r2_endpoint_url:
        msg = "WIKIMIND_R2_ENDPOINT_URL must be set when storage_backend=r2"
        raise ValueError(msg)

    aws_key = settings.aws_access_key_id.get_secret_value() if settings.aws_access_key_id else None
    aws_secret = settings.aws_secret_access_key.get_secret_value() if settings.aws_secret_access_key else None

    log.info("creating R2 storage", bucket=settings.r2_bucket, prefix=prefix)
    return R2FileStorage(
        bucket=settings.r2_bucket,
        endpoint_url=settings.r2_endpoint_url,
        prefix=prefix,
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
    )


@lru_cache(maxsize=1)
def get_wiki_storage() -> FileStorage:
    """Return the wiki file storage singleton."""
    settings = get_settings()
    if settings.storage_backend == "r2":
        return _make_r2_storage(prefix="wiki")
    return LocalFileStorage(root=Path(settings.data_dir) / "wiki")


@lru_cache(maxsize=1)
def get_raw_storage() -> FileStorage:
    """Return the raw source file storage singleton."""
    settings = get_settings()
    if settings.storage_backend == "r2":
        return _make_r2_storage(prefix="raw")
    return LocalFileStorage(root=Path(settings.data_dir) / "raw")


def resolve_wiki_path(relative_path: str) -> Path:
    """Resolve a wiki-relative path to an absolute filesystem path.

    Handles backward compatibility: if the path is already absolute,
    returns it as-is.

    NOTE: For local storage only. When ``storage_backend=r2``, use the
    sync helpers (``read_wiki``, ``write_wiki``, etc.) instead.
    """
    path = Path(relative_path)
    if path.is_absolute():
        return path
    settings = get_settings()
    return Path(settings.data_dir) / "wiki" / relative_path


def resolve_raw_path(relative_path: str) -> Path:
    """Resolve a raw-relative path to an absolute filesystem path.

    Handles backward compatibility: if the path is already absolute,
    returns it as-is.

    NOTE: For local storage only. When ``storage_backend=r2``, use the
    sync helpers (``read_raw``, ``write_raw``, etc.) instead.
    """
    path = Path(relative_path)
    if path.is_absolute():
        return path
    settings = get_settings()
    return Path(settings.data_dir) / "raw" / relative_path


# ---------------------------------------------------------------------------
# Sync helpers — bridge sync callers to the async FileStorage backend.
# These run the async storage method on the current event loop via
# asyncio.get_event_loop().run_until_complete(), or fall back to
# asyncio.run() if no loop is running. Safe to call from sync code
# inside an async application (FastAPI handlers are already in a loop).
# ---------------------------------------------------------------------------


def _run_async(coro):  # noqa: ANN001, ANN202
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures  # noqa: PLC0415

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def write_wiki(relative_path: str, content: str) -> None:
    """Write text to wiki storage (sync wrapper)."""
    _run_async(get_wiki_storage().write(relative_path, content))


def write_wiki_bytes(relative_path: str, data: bytes) -> None:
    """Write bytes to wiki storage (sync wrapper)."""
    _run_async(get_wiki_storage().write_bytes(relative_path, data))


def read_wiki(relative_path: str) -> str:
    """Read text from wiki storage (sync wrapper)."""
    return _run_async(get_wiki_storage().read(relative_path))


def delete_wiki(relative_path: str) -> None:
    """Delete a file from wiki storage (sync wrapper)."""
    _run_async(get_wiki_storage().delete(relative_path))


def write_raw(relative_path: str, content: str) -> None:
    """Write text to raw storage (sync wrapper)."""
    _run_async(get_raw_storage().write(relative_path, content))


def write_raw_bytes(relative_path: str, data: bytes) -> None:
    """Write bytes to raw storage (sync wrapper)."""
    _run_async(get_raw_storage().write_bytes(relative_path, data))


def read_raw(relative_path: str) -> str:
    """Read text from raw storage (sync wrapper)."""
    return _run_async(get_raw_storage().read(relative_path))


def delete_raw(relative_path: str) -> None:
    """Delete a file from raw storage (sync wrapper)."""
    _run_async(get_raw_storage().delete(relative_path))
