"""Tests for R2FileStorage with mocked boto3 client."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wikimind.config import get_settings
from wikimind.storage import FileStorage, get_raw_storage, get_wiki_storage
from wikimind.storage_r2 import R2FileStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(
    bucket: str = "test-bucket",
    endpoint_url: str = "https://r2.example.com",
    prefix: str = "",
) -> R2FileStorage:
    """Create an R2FileStorage with default test params."""
    return R2FileStorage(
        bucket=bucket,
        endpoint_url=endpoint_url,
        prefix=prefix,
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",  # pragma: allowlist secret
    )


def _mock_client() -> MagicMock:
    """Create a mock S3 client with standard exception types."""
    client = MagicMock()

    # NoSuchKey exception class
    no_such_key = type("NoSuchKey", (Exception,), {})
    client.exceptions.NoSuchKey = no_such_key

    # ClientError with configurable response
    class ClientError(Exception):
        def __init__(self, response: dict[str, Any], operation_name: str = ""):
            self.response = response
            super().__init__(f"{operation_name}: {response}")

    client.exceptions.ClientError = ClientError
    return client


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_r2_storage_is_file_storage_protocol():
    """R2FileStorage satisfies the FileStorage runtime protocol."""
    storage = _make_storage()
    assert isinstance(storage, FileStorage)


# ---------------------------------------------------------------------------
# Key construction
# ---------------------------------------------------------------------------


def test_key_no_prefix():
    storage = _make_storage(prefix="")
    assert storage._key("concept/article.md") == "concept/article.md"


def test_key_with_prefix():
    storage = _make_storage(prefix="wiki")
    assert storage._key("concept/article.md") == "wiki/concept/article.md"


def test_key_with_trailing_slash_prefix():
    storage = _make_storage(prefix="wiki/")
    assert storage._key("concept/article.md") == "wiki/concept/article.md"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_text():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()
    body = MagicMock()
    body.read.return_value = b"hello world"
    client.get_object.return_value = {"Body": body}
    storage._client = client

    result = await storage.read("concept/article.md")

    assert result == "hello world"
    client.get_object.assert_called_once_with(Bucket="test-bucket", Key="wiki/concept/article.md")


@pytest.mark.asyncio
async def test_read_bytes():
    storage = _make_storage(prefix="data")
    client = _mock_client()
    raw = b"\x89PNG fake"
    body = MagicMock()
    body.read.return_value = raw
    client.get_object.return_value = {"Body": body}
    storage._client = client

    result = await storage.read_bytes("image.png")

    assert result == raw
    client.get_object.assert_called_once_with(Bucket="test-bucket", Key="data/image.png")


@pytest.mark.asyncio
async def test_read_missing_raises_file_not_found():
    storage = _make_storage()
    client = _mock_client()
    client.get_object.side_effect = client.exceptions.NoSuchKey("not found")
    storage._client = client

    with pytest.raises(FileNotFoundError, match=r"missing\.md"):
        await storage.read("missing.md")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_text():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()
    storage._client = client

    await storage.write("concept/new.md", "content here")

    client.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="wiki/concept/new.md",
        Body=b"content here",
    )


@pytest.mark.asyncio
async def test_write_bytes():
    storage = _make_storage(prefix="raw")
    client = _mock_client()
    storage._client = client

    data = b"\x00\x01\x02"
    await storage.write_bytes("binary.dat", data)

    client.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="raw/binary.dat",
        Body=data,
    )


# ---------------------------------------------------------------------------
# Append (emulated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_to_existing():
    storage = _make_storage()
    client = _mock_client()
    body = MagicMock()
    body.read.return_value = b"line1\n"
    client.get_object.return_value = {"Body": body}
    storage._client = client

    await storage.append("log.md", "line2\n")

    # Should have read the existing content then written the combined result
    client.get_object.assert_called_once()
    client.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="log.md",
        Body=b"line1\nline2\n",
    )


@pytest.mark.asyncio
async def test_append_to_new_file():
    storage = _make_storage()
    client = _mock_client()
    client.get_object.side_effect = client.exceptions.NoSuchKey("not found")
    storage._client = client

    await storage.append("new.md", "first line\n")

    client.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="new.md",
        Body=b"first line\n",
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()
    storage._client = client

    await storage.delete("concept/old.md")

    client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="wiki/concept/old.md")


@pytest.mark.asyncio
async def test_delete_missing_is_noop():
    """delete_object is idempotent in S3 — no error on missing keys."""
    storage = _make_storage()
    client = _mock_client()
    storage._client = client

    await storage.delete("nonexistent.md")
    client.delete_object.assert_called_once()


# ---------------------------------------------------------------------------
# Exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exists_true():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()
    client.head_object.return_value = {}
    storage._client = client

    assert await storage.exists("concept/article.md") is True
    client.head_object.assert_called_once_with(Bucket="test-bucket", Key="wiki/concept/article.md")


@pytest.mark.asyncio
async def test_exists_false():
    storage = _make_storage()
    client = _mock_client()
    error_response = {"Error": {"Code": "404"}}
    client.head_object.side_effect = client.exceptions.ClientError(error_response, "HeadObject")
    storage._client = client

    assert await storage.exists("missing.md") is False


@pytest.mark.asyncio
async def test_exists_no_such_key_code():
    storage = _make_storage()
    client = _mock_client()
    error_response = {"Error": {"Code": "NoSuchKey"}}
    client.head_object.side_effect = client.exceptions.ClientError(error_response, "HeadObject")
    storage._client = client

    assert await storage.exists("missing.md") is False


@pytest.mark.asyncio
async def test_exists_unexpected_error_propagates():
    storage = _make_storage()
    client = _mock_client()
    error_response = {"Error": {"Code": "403"}}
    client.head_object.side_effect = client.exceptions.ClientError(error_response, "HeadObject")
    storage._client = client

    with pytest.raises(client.exceptions.ClientError):
        await storage.exists("forbidden.md")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_with_prefix():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "wiki/concept/a.md"}, {"Key": "wiki/concept/b.md"}]},
    ]
    client.get_paginator.return_value = paginator
    storage._client = client

    result = await storage.list("concept/")

    assert sorted(result) == ["concept/a.md", "concept/b.md"]
    paginator.paginate.assert_called_once_with(Bucket="test-bucket", Prefix="wiki/concept/")


@pytest.mark.asyncio
async def test_list_all():
    storage = _make_storage(prefix="wiki")
    client = _mock_client()

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "wiki/x.md"}, {"Key": "wiki/y/z.md"}]},
    ]
    client.get_paginator.return_value = paginator
    storage._client = client

    result = await storage.list()

    assert sorted(result) == ["x.md", "y/z.md"]


@pytest.mark.asyncio
async def test_list_empty_bucket():
    storage = _make_storage()
    client = _mock_client()

    paginator = MagicMock()
    paginator.paginate.return_value = [{}]  # No Contents key
    client.get_paginator.return_value = paginator
    storage._client = client

    result = await storage.list()

    assert result == []


@pytest.mark.asyncio
async def test_list_paginated():
    storage = _make_storage(prefix="data")
    client = _mock_client()

    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "data/a.txt"}]},
        {"Contents": [{"Key": "data/b.txt"}, {"Key": "data/c.txt"}]},
    ]
    client.get_paginator.return_value = paginator
    storage._client = client

    result = await storage.list()

    assert sorted(result) == ["a.txt", "b.txt", "c.txt"]


# ---------------------------------------------------------------------------
# Client creation (lazy)
# ---------------------------------------------------------------------------


def test_lazy_client_creation():
    """Client is not created until the first operation calls _get_client."""
    storage = _make_storage()
    assert storage._client is None


def test_client_created_with_credentials():
    """Verify boto3.client is called with the right kwargs."""
    mock_boto3 = MagicMock()
    storage = _make_storage(endpoint_url="https://my-r2.example.com")

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        storage._get_client()

    mock_boto3.client.assert_called_once_with(
        service_name="s3",
        endpoint_url="https://my-r2.example.com",
        aws_access_key_id="test-key",
        aws_secret_access_key="test-secret",  # pragma: allowlist secret
    )


def test_client_created_without_credentials():
    """Verify boto3.client omits credentials when not provided."""
    mock_boto3 = MagicMock()
    storage = R2FileStorage(
        bucket="test-bucket",
        endpoint_url="https://r2.example.com",
    )

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        storage._get_client()

    mock_boto3.client.assert_called_once_with(
        service_name="s3",
        endpoint_url="https://r2.example.com",
    )


def test_client_cached():
    """Verify the client is created only once and then reused."""
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    storage = _make_storage()

    with patch.dict(sys.modules, {"boto3": mock_boto3}):
        c1 = storage._get_client()
        c2 = storage._get_client()

    assert c1 is c2
    assert mock_boto3.client.call_count == 1


# ---------------------------------------------------------------------------
# Factory integration (storage.py get_wiki_storage / get_raw_storage)
# ---------------------------------------------------------------------------


def test_factory_returns_r2_when_configured(tmp_path, monkeypatch):
    """get_wiki_storage returns R2FileStorage when storage_backend=r2."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WIKIMIND_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("WIKIMIND_R2_BUCKET", "my-bucket")
    monkeypatch.setenv("WIKIMIND_R2_ENDPOINT_URL", "https://r2.example.com")
    monkeypatch.setenv("WIKIMIND_AWS_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("WIKIMIND_AWS_SECRET_ACCESS_KEY", "secret")  # pragma: allowlist secret
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()

    try:
        wiki = get_wiki_storage()
        raw = get_raw_storage()
        assert isinstance(wiki, R2FileStorage)
        assert isinstance(raw, R2FileStorage)
        assert wiki.bucket == "my-bucket"
        assert wiki.prefix == "wiki/"
        assert raw.prefix == "raw/"
    finally:
        get_settings.cache_clear()
        get_wiki_storage.cache_clear()
        get_raw_storage.cache_clear()


def test_factory_raises_without_bucket(tmp_path, monkeypatch):
    """get_wiki_storage raises ValueError when r2 backend is missing bucket config."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WIKIMIND_STORAGE_BACKEND", "r2")
    # No bucket or endpoint set
    monkeypatch.delenv("WIKIMIND_R2_BUCKET", raising=False)
    monkeypatch.delenv("WIKIMIND_R2_ENDPOINT_URL", raising=False)
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()

    try:
        with pytest.raises(ValueError, match="R2_BUCKET"):
            get_wiki_storage()
    finally:
        get_settings.cache_clear()
        get_wiki_storage.cache_clear()


def test_factory_raises_without_endpoint(tmp_path, monkeypatch):
    """get_wiki_storage raises ValueError when r2 backend is missing endpoint config."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WIKIMIND_STORAGE_BACKEND", "r2")
    monkeypatch.setenv("WIKIMIND_R2_BUCKET", "my-bucket")
    monkeypatch.delenv("WIKIMIND_R2_ENDPOINT_URL", raising=False)
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()

    try:
        with pytest.raises(ValueError, match="R2_ENDPOINT_URL"):
            get_wiki_storage()
    finally:
        get_settings.cache_clear()
        get_wiki_storage.cache_clear()
