"""Cloudflare R2 / S3-compatible implementation of the FileStorage protocol.

All boto3 calls are blocking and are wrapped in ``asyncio.to_thread()`` so
they can be called from async FastAPI handlers without blocking the event loop.

The ``append`` operation is emulated as read + append + write because S3/R2
does not support native append.  The ``delete`` method is a silent no-op when
the key does not exist, matching ``LocalFileStorage`` semantics.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

log = structlog.get_logger()


class R2FileStorage:
    """S3-compatible (Cloudflare R2) file storage backend."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        prefix: str = "",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._endpoint_url = endpoint_url
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._client: S3Client | None = None

    def _get_client(self) -> Any:
        """Lazily create the boto3 S3 client (not thread-safe, but always called inside to_thread)."""
        if self._client is None:
            import boto3  # noqa: PLC0415 — lazy import to avoid pulling boto3 when running local

            kwargs: dict[str, Any] = {
                "service_name": "s3",
                "endpoint_url": self._endpoint_url,
            }
            if self._aws_access_key_id:
                kwargs["aws_access_key_id"] = self._aws_access_key_id
            if self._aws_secret_access_key:
                kwargs["aws_secret_access_key"] = self._aws_secret_access_key
            self._client = boto3.client(**kwargs)
        return self._client

    def _key(self, relative_path: str) -> str:
        """Build the full S3 key from a relative path."""
        return f"{self.prefix}{relative_path}"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def read(self, relative_path: str) -> str:
        """Read text content from R2."""
        data = await self.read_bytes(relative_path)
        return data.decode("utf-8")

    async def read_bytes(self, relative_path: str) -> bytes:
        """Read binary content from R2."""

        def _read() -> bytes:
            client = self._get_client()
            try:
                resp = client.get_object(Bucket=self.bucket, Key=self._key(relative_path))
                return resp["Body"].read()  # type: ignore[no-any-return]
            except client.exceptions.NoSuchKey:
                raise FileNotFoundError(relative_path) from None

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def write(self, relative_path: str, content: str) -> None:
        """Write text content to R2."""
        await self.write_bytes(relative_path, content.encode("utf-8"))

    async def write_bytes(self, relative_path: str, data: bytes) -> None:
        """Write binary content to R2."""

        def _write() -> None:
            client = self._get_client()
            client.put_object(Bucket=self.bucket, Key=self._key(relative_path), Body=data)

        await asyncio.to_thread(_write)

    # ------------------------------------------------------------------
    # Append (emulated: read + concat + write)
    # ------------------------------------------------------------------

    async def append(self, relative_path: str, content: str) -> None:
        """Append text to an R2 object (emulated via read-modify-write)."""
        try:
            existing = await self.read(relative_path)
        except FileNotFoundError:
            existing = ""
        await self.write(relative_path, existing + content)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, relative_path: str) -> None:
        """Delete an object from R2. No-op if the key does not exist."""

        def _delete() -> None:
            client = self._get_client()
            # S3 delete_object is idempotent — no error on missing key
            client.delete_object(Bucket=self.bucket, Key=self._key(relative_path))

        await asyncio.to_thread(_delete)

    # ------------------------------------------------------------------
    # Exists
    # ------------------------------------------------------------------

    async def exists(self, relative_path: str) -> bool:
        """Return True if the key exists in R2."""

        def _exists() -> bool:
            client = self._get_client()
            try:
                client.head_object(Bucket=self.bucket, Key=self._key(relative_path))
                return True
            except client.exceptions.ClientError as exc:
                # head_object raises ClientError with 404 for missing keys
                code = exc.response.get("Error", {}).get("Code", "")
                if code in ("404", "NoSuchKey"):
                    return False
                raise

        return await asyncio.to_thread(_exists)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list(self, prefix: str = "") -> list[str]:
        """List all keys under the given prefix, returning relative paths."""
        full_prefix = self._key(prefix)

        def _list() -> list[str]:
            client = self._get_client()
            paginator = client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    # Strip the storage prefix to return a relative path
                    if self.prefix and key.startswith(self.prefix):
                        keys.append(key[len(self.prefix) :])
                    else:
                        keys.append(key)
            return keys

        return await asyncio.to_thread(_list)
