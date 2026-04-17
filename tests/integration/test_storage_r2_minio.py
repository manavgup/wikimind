"""Integration tests for R2FileStorage against a real MinIO instance.

These tests require Docker to be available and will spin up a temporary
MinIO container. They are automatically skipped when Docker is not
available (e.g. in CI environments without Docker).

To run manually::

    docker run -d --name minio-test -p 9100:9000 \
        -e MINIO_ROOT_USER=minioadmin \
        -e MINIO_ROOT_PASSWORD=minioadmin \
        minio/minio server /data

    pytest tests/integration/test_storage_r2_minio.py -v
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

# Skip the entire module if Docker is not available
_has_docker = shutil.which("docker") is not None


def _docker_available() -> bool:
    """Check if Docker daemon is actually running (not just installed)."""
    if not _has_docker:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Docker not available")

MINIO_PORT = 9100
MINIO_ENDPOINT = f"http://localhost:{MINIO_PORT}"
MINIO_USER = "minioadmin"
MINIO_PASSWORD = "minioadmin"
CONTAINER_NAME = "wikimind-test-minio"
TEST_BUCKET = "wikimind-test"


@pytest.fixture(scope="module")
def minio_container():
    """Start a MinIO container for the test module, clean up after."""
    # Stop any leftover container
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False)

    # Start MinIO
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{MINIO_PORT}:9000",
            "-e",
            f"MINIO_ROOT_USER={MINIO_USER}",
            "-e",
            f"MINIO_ROOT_PASSWORD={MINIO_PASSWORD}",
            "minio/minio",
            "server",
            "/data",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to start MinIO container: {result.stderr}")

    # Wait for MinIO to be ready
    import boto3  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_USER,
        aws_secret_access_key=MINIO_PASSWORD,
    )

    for _ in range(30):
        try:
            client.list_buckets()
            break
        except Exception:
            time.sleep(0.5)
    else:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False)
        pytest.skip("MinIO did not become ready in time")

    # Create test bucket — ignore if it already exists
    import contextlib  # noqa: PLC0415

    with contextlib.suppress(client.exceptions.BucketAlreadyOwnedByYou):
        client.create_bucket(Bucket=TEST_BUCKET)

    yield

    # Cleanup
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True, check=False)


@pytest.fixture
def storage(minio_container):
    """Create a fresh R2FileStorage pointing at the MinIO test bucket."""
    from wikimind.storage_r2 import R2FileStorage  # noqa: PLC0415

    return R2FileStorage(
        bucket=TEST_BUCKET,
        endpoint_url=MINIO_ENDPOINT,
        prefix="test",
        aws_access_key_id=MINIO_USER,
        aws_secret_access_key=MINIO_PASSWORD,
    )


@pytest.fixture(autouse=True)
def _clean_bucket(minio_container):
    """Clean up all objects in the test bucket between tests."""
    yield

    import boto3  # noqa: PLC0415

    client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_USER,
        aws_secret_access_key=MINIO_PASSWORD,
    )
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=TEST_BUCKET):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket=TEST_BUCKET, Key=obj["Key"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_and_read(storage):
    await storage.write("concept/article.md", "hello world")
    content = await storage.read("concept/article.md")
    assert content == "hello world"


@pytest.mark.asyncio
async def test_write_bytes_and_read_bytes(storage):
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


@pytest.mark.asyncio
async def test_full_cycle(storage):
    """Write, read, exists, list, delete — full CRUD cycle."""
    await storage.write("cycle/test.md", "content")
    assert await storage.exists("cycle/test.md")
    assert await storage.read("cycle/test.md") == "content"

    files = await storage.list("cycle/")
    assert "cycle/test.md" in files

    await storage.delete("cycle/test.md")
    assert not await storage.exists("cycle/test.md")
