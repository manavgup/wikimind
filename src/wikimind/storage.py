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

from wikimind.config import get_settings


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


@lru_cache(maxsize=1)
def get_wiki_storage() -> FileStorage:
    """Return the wiki file storage singleton."""
    settings = get_settings()
    return LocalFileStorage(root=Path(settings.data_dir) / "wiki")


@lru_cache(maxsize=1)
def get_raw_storage() -> FileStorage:
    """Return the raw source file storage singleton."""
    settings = get_settings()
    return LocalFileStorage(root=Path(settings.data_dir) / "raw")


def resolve_wiki_path(relative_path: str) -> Path:
    """Resolve a wiki-relative path to an absolute filesystem path.

    Handles backward compatibility: if the path is already absolute,
    returns it as-is.
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
    """
    path = Path(relative_path)
    if path.is_absolute():
        return path
    settings = get_settings()
    return Path(settings.data_dir) / "raw" / relative_path
