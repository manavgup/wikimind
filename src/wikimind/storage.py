"""File storage abstraction for wiki and raw source files.

Provides a protocol for async file operations and a local filesystem
implementation. In production, an R2/S3 implementation can be swapped
in via configuration without changing application code.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, runtime_checkable

from wikimind.config import get_settings


@runtime_checkable
class FileStorage(Protocol):
    """Async file storage interface."""

    async def read(self, relative_path: str) -> str:
        """Read text content from a file."""
        ...  # type: ignore[empty-body]

    async def read_bytes(self, relative_path: str) -> bytes:
        """Read binary content from a file."""
        ...  # type: ignore[empty-body]

    async def write(self, relative_path: str, content: str) -> None:
        """Write text content to a file, creating parent dirs as needed."""
        ...  # type: ignore[empty-body]

    async def write_bytes(self, relative_path: str, data: bytes) -> None:
        """Write binary content to a file, creating parent dirs as needed."""
        ...  # type: ignore[empty-body]

    async def append(self, relative_path: str, content: str) -> None:
        """Append text content to a file, creating it if it does not exist."""
        ...  # type: ignore[empty-body]

    async def delete(self, relative_path: str) -> None:
        """Delete a file. No-op if the file does not exist."""
        ...  # type: ignore[empty-body]

    async def exists(self, relative_path: str) -> bool:
        """Return True if the file exists."""
        ...  # type: ignore[empty-body]

    async def list(self, prefix: str = "") -> list[str]:
        """List all files under the given prefix (or root if empty)."""
        ...  # type: ignore[empty-body]

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute filesystem path.

        Needed by callers that must hand a real path to external tools
        (e.g. PDF extractors, log messages). Prefer ``read`` / ``write``
        for normal I/O.
        """
        ...  # type: ignore[empty-body]


class LocalFileStorage:
    """Local filesystem implementation of FileStorage."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve(self, relative_path: str) -> Path:
        resolved = (self.root / relative_path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            msg = f"Path traversal detected: {relative_path!r}"
            raise ValueError(msg)
        return resolved

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute filesystem path.

        Needed by callers that must hand a real path to external tools
        (e.g. PDF extractors, log messages). Prefer ``read`` / ``write``
        for normal I/O.
        """
        return self._resolve(relative_path)

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


def get_wiki_storage(user_id: str) -> LocalFileStorage:
    """Return wiki file storage, optionally scoped to a user."""
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki"
    if user_id:
        root = root / user_id
    return LocalFileStorage(root=root)


def get_raw_storage(user_id: str) -> LocalFileStorage:
    """Return raw source file storage, optionally scoped to a user."""
    settings = get_settings()
    root = Path(settings.data_dir) / "raw"
    if user_id:
        root = root / user_id
    return LocalFileStorage(root=root)


async def read_article_content(file_path: str, user_id: str) -> str:
    """Read article markdown content from disk.

    Canonical helper used by wiki service, Q&A agent, and export routes.
    Returns an empty string when the file cannot be read (missing, permission
    error, etc.) so callers never need their own OSError handling.

    Args:
        file_path: Relative path to the article markdown file within the
            user's wiki storage directory.
        user_id: User ID for storage namespacing.

    Returns:
        The file content, or an empty string if the file cannot be read.
    """
    try:
        storage = get_wiki_storage(user_id)
        return await storage.read(file_path)
    except (OSError, ValueError):
        return ""


def find_original_sibling(txt_path: Path) -> Path | None:
    """Find the non-.txt sibling of a raw source file.

    During ingest, adapters store both the cleaned text ({id}.txt) and the
    original binary ({id}.pdf, {id}.html).  This function locates the
    original by scanning the same directory for a file with the same stem
    but a different extension.

    Returns None if only the .txt exists (text/YouTube sources) or if
    the txt_path itself does not exist.
    """
    if not txt_path.exists():
        return None
    stem = txt_path.stem
    parent = txt_path.parent
    for sibling in parent.iterdir():
        if sibling.stem == stem and sibling.suffix != ".txt" and sibling.is_file():
            return sibling
    return None
