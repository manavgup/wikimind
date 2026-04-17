"""Tests for the FileStorage abstraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from wikimind.config import get_settings
from wikimind.storage import (
    FileStorage,
    LocalFileStorage,
    get_raw_storage,
    get_wiki_storage,
    resolve_raw_path,
    resolve_wiki_path,
)


@pytest.fixture
def storage(tmp_path):
    return LocalFileStorage(root=tmp_path)


@pytest.mark.asyncio
async def test_write_and_read(storage, tmp_path):
    await storage.write("subdir/test.md", "hello world")
    content = await storage.read("subdir/test.md")
    assert content == "hello world"
    assert (tmp_path / "subdir" / "test.md").exists()


@pytest.mark.asyncio
async def test_write_bytes_and_read_bytes(storage, tmp_path):
    data = b"\x89PNG fake image data"
    await storage.write_bytes("raw/file.pdf", data)
    result = await storage.read_bytes("raw/file.pdf")
    assert result == data


@pytest.mark.asyncio
async def test_append(storage):
    await storage.write("log.md", "line1\n")
    await storage.append("log.md", "line2\n")
    content = await storage.read("log.md")
    assert content == "line1\nline2\n"


@pytest.mark.asyncio
async def test_append_creates_file(storage):
    await storage.append("new.md", "first line\n")
    content = await storage.read("new.md")
    assert content == "first line\n"


@pytest.mark.asyncio
async def test_delete(storage):
    await storage.write("to_delete.md", "bye")
    assert await storage.exists("to_delete.md")
    await storage.delete("to_delete.md")
    assert not await storage.exists("to_delete.md")


@pytest.mark.asyncio
async def test_delete_missing_is_noop(storage):
    await storage.delete("nonexistent.md")  # should not raise


@pytest.mark.asyncio
async def test_exists(storage):
    assert not await storage.exists("nope.md")
    await storage.write("yep.md", "here")
    assert await storage.exists("yep.md")


@pytest.mark.asyncio
async def test_list_files(storage):
    await storage.write("a/one.md", "1")
    await storage.write("a/two.md", "2")
    await storage.write("b/three.md", "3")
    files = await storage.list("a/")
    assert sorted(files) == ["a/one.md", "a/two.md"]


@pytest.mark.asyncio
async def test_list_all(storage):
    await storage.write("x.md", "x")
    await storage.write("y/z.md", "z")
    files = await storage.list()
    assert sorted(files) == ["x.md", "y/z.md"]


@pytest.mark.asyncio
async def test_read_missing_raises(storage):
    with pytest.raises(FileNotFoundError):
        await storage.read("missing.md")


# ---------------------------------------------------------------------------
# Protocol and factory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_storage_is_file_storage_protocol():
    """LocalFileStorage satisfies the FileStorage protocol."""
    storage = LocalFileStorage(root=Path("/tmp/test"))
    assert isinstance(storage, FileStorage)


def test_get_wiki_storage_returns_local(tmp_path, monkeypatch):
    """get_wiki_storage() returns a LocalFileStorage rooted at wiki_dir."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    storage = get_wiki_storage()
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "wiki"
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()


def test_get_raw_storage_returns_local(tmp_path, monkeypatch):
    """get_raw_storage() returns a LocalFileStorage rooted at raw_dir."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    get_raw_storage.cache_clear()
    storage = get_raw_storage()
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "raw"
    get_settings.cache_clear()
    get_raw_storage.cache_clear()


# ---------------------------------------------------------------------------
# resolve_wiki_path / resolve_raw_path tests
# ---------------------------------------------------------------------------


def test_resolve_wiki_path_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = resolve_wiki_path("concept/article.md")
    assert result == tmp_path / "wiki" / "concept" / "article.md"
    get_settings.cache_clear()


def test_resolve_wiki_path_absolute():
    result = resolve_wiki_path("/absolute/path/article.md")
    assert result == Path("/absolute/path/article.md")


def test_resolve_raw_path_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = resolve_raw_path("source-id.txt")
    assert result == tmp_path / "raw" / "source-id.txt"
    get_settings.cache_clear()
