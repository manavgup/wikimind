# R2 Storage Backend (PR 3 of 3 for Cloud Deployment)

## Status: Implemented

## Summary

Implements `R2FileStorage` — a Cloudflare R2 / S3-compatible backend for
the `FileStorage` protocol established in PR 1 (FileStorage abstraction).

## Changes

1. **Config** (`src/wikimind/config.py`):
   - `storage_backend: str = "local"` — `"local"` or `"r2"`
   - `r2_bucket: str | None` — R2 bucket name
   - `r2_endpoint_url: str | None` — R2 endpoint URL

2. **R2FileStorage** (`src/wikimind/storage_r2.py`):
   - Implements all `FileStorage` protocol methods
   - Uses boto3 S3 client with `asyncio.to_thread()` wrappers
   - Lazy client creation (no boto3 import until first use)
   - Append emulated as read + concat + write
   - `read()` raises `FileNotFoundError` on `NoSuchKey` (matches local)

3. **Factory** (`src/wikimind/storage.py`):
   - `get_wiki_storage()` / `get_raw_storage()` return `R2FileStorage`
     when `storage_backend == "r2"`
   - Lazy import of `R2FileStorage` to avoid pulling boto3 for local users

4. **Tests**:
   - `tests/unit/test_storage_r2.py` — mock boto3, full method coverage
   - `tests/integration/test_storage_r2_minio.py` — MinIO Docker, full CRUD

5. **Docs**:
   - `docs/adr/adr-020-cloud-storage-abstraction.md`
   - Amendment to ADR-004
   - `.env.example` updated
   - `README.md` cloud deployment section
