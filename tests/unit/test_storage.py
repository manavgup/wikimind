"""Tests for the FileStorage abstraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.storage import (
    FileStorage,
    LocalFileStorage,
    find_original_sibling,
    get_raw_storage,
    get_wiki_storage,
    read_article_content,
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
    """get_wiki_storage(user_id=TEST_USER_ID) returns a LocalFileStorage rooted at wiki_dir."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_wiki_storage(user_id=TEST_USER_ID)
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "wiki" / TEST_USER_ID
    get_settings.cache_clear()


def test_get_wiki_storage_with_user_id(tmp_path, monkeypatch):
    """get_wiki_storage(user_id=...) returns storage rooted at wiki/{user_id}."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_wiki_storage(user_id="user-123")
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "wiki" / "user-123"
    get_settings.cache_clear()


def test_get_raw_storage_returns_local(tmp_path, monkeypatch):
    """get_raw_storage(user_id=TEST_USER_ID) returns a LocalFileStorage rooted at raw_dir."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_raw_storage(user_id=TEST_USER_ID)
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "raw" / TEST_USER_ID
    get_settings.cache_clear()


def test_get_raw_storage_with_user_id(tmp_path, monkeypatch):
    """get_raw_storage(user_id=...) returns storage rooted at raw/{user_id}."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_raw_storage(user_id="user-456")
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "raw" / "user-456"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# get_wiki_storage / get_raw_storage root resolution tests
# ---------------------------------------------------------------------------


def test_wiki_storage_resolve_path(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_wiki_storage(TEST_USER_ID)
    result = storage.resolve_path("concept/article.md")
    assert result == tmp_path / "wiki" / TEST_USER_ID / "concept" / "article.md"
    get_settings.cache_clear()


def test_wiki_storage_resolve_path_with_user_id(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_wiki_storage("user-abc")
    result = storage.resolve_path("concept/article.md")
    assert result == tmp_path / "wiki" / "user-abc" / "concept" / "article.md"
    get_settings.cache_clear()


def test_raw_storage_resolve_path(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_raw_storage(TEST_USER_ID)
    result = storage.resolve_path("source-id.txt")
    assert result == tmp_path / "raw" / TEST_USER_ID / "source-id.txt"
    get_settings.cache_clear()


def test_raw_storage_resolve_path_with_user_id(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    storage = get_raw_storage("user-xyz")
    result = storage.resolve_path("source-id.txt")
    assert result == tmp_path / "raw" / "user-xyz" / "source-id.txt"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# read_article_content tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_article_content_ok(tmp_path):
    """read_article_content returns file contents via wiki storage."""
    # _isolated_data_dir fixture sets WIKIMIND_DATA_DIR to tmp_path / "wikimind"
    wiki_dir = tmp_path / "wikimind" / "wiki" / TEST_USER_ID
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "test.md").write_text("hello world", encoding="utf-8")
    result = await read_article_content("test.md", user_id=TEST_USER_ID)
    assert result == "hello world"


@pytest.mark.asyncio
async def test_read_article_content_missing_returns_empty(tmp_path):
    """read_article_content returns empty string for missing files."""
    result = await read_article_content("nonexistent.md", user_id=TEST_USER_ID)
    assert result == ""


# ---------------------------------------------------------------------------
# find_original_sibling tests
# ---------------------------------------------------------------------------


def test_find_original_sibling_finds_pdf(tmp_path: Path) -> None:
    """When a .pdf sibling exists alongside the .txt, return it."""
    (tmp_path / "abc.txt").write_text("extracted text")
    (tmp_path / "abc.pdf").write_bytes(b"%PDF-fake")
    result = find_original_sibling(tmp_path / "abc.txt")
    assert result is not None
    assert result.suffix == ".pdf"
    assert result.name == "abc.pdf"


def test_find_original_sibling_finds_html(tmp_path: Path) -> None:
    """When an .html sibling exists alongside the .txt, return it."""
    (tmp_path / "xyz.txt").write_text("extracted text")
    (tmp_path / "xyz.html").write_text("<html>hello</html>")
    result = find_original_sibling(tmp_path / "xyz.txt")
    assert result is not None
    assert result.suffix == ".html"


def test_find_original_sibling_returns_none_for_text_only(tmp_path: Path) -> None:
    """When only the .txt exists (text/YouTube sources), return None."""
    (tmp_path / "zzz.txt").write_text("plain text source")
    result = find_original_sibling(tmp_path / "zzz.txt")
    assert result is None


def test_find_original_sibling_returns_none_for_missing_file(tmp_path: Path) -> None:
    """When the txt file itself doesn't exist, return None."""
    result = find_original_sibling(tmp_path / "nonexistent.txt")
    assert result is None
