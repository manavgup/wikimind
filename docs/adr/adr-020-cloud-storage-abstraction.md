# ADR-020: Cloud Storage Abstraction (R2/S3 Backend)

## Status

Accepted

## Context

WikiMind stores wiki articles and raw source files as plain files on disk
(ADR-004). For cloud deployment (Fly.io, Railway, etc.), ephemeral
container filesystems lose data on restart. We need a durable storage
backend that works across container restarts and redeployments.

The PR-1 FileStorage abstraction (protocol in `storage.py`) established
the interface boundary. This ADR covers the concrete cloud implementation.

## Decision

Add an **R2FileStorage** class (`storage_r2.py`) implementing the
`FileStorage` protocol using boto3's S3 client, targeting Cloudflare R2
as the primary object store. The same code works against any S3-compatible
endpoint (AWS S3, MinIO, Backblaze B2).

### Storage backend selection

A new `storage_backend` setting (`"local"` default, `"r2"` for cloud)
controls which implementation the factory functions return:

```python
# config.py
storage_backend: str = "local"
r2_bucket: str | None = None
r2_endpoint_url: str | None = None
```

### Key design choices

1. **Lazy boto3 import** — `storage_r2.py` is only imported when
   `storage_backend == "r2"`, so local users never pay the boto3 import
   cost.

2. **asyncio.to_thread()** — All boto3 calls are synchronous. Wrapping
   them in `to_thread()` keeps the event loop unblocked, matching the
   same pattern used by `LocalFileStorage`.

3. **Emulated append** — R2/S3 has no native append operation.
   `R2FileStorage.append()` performs read → concatenate → write. This is
   acceptable because append is only used for index files and logs, not
   hot-path operations.

4. **Prefix-based isolation** — Wiki files use prefix `wiki/`, raw files
   use prefix `raw/`. A single bucket can serve both by routing through
   the prefix parameter in the factory function.

5. **Existing AWS credentials** — The `aws_access_key_id` and
   `aws_secret_access_key` fields already existed in `Settings` for the
   sync feature. R2 reuses them.

### Configuration

```bash
WIKIMIND_STORAGE_BACKEND=r2
WIKIMIND_R2_BUCKET=my-wikimind-bucket
WIKIMIND_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
WIKIMIND_AWS_ACCESS_KEY_ID=...
WIKIMIND_AWS_SECRET_ACCESS_KEY=...
```

## Alternatives Considered

**Fly.io Volumes** — Persistent volumes tied to a single machine. Simpler
but does not support multi-region or horizontal scaling. Also adds vendor
lock-in to Fly.io infrastructure.

**SQLite BLOB storage** — Store file content as BLOBs in the database.
Loses human-readability and the ability to use external tools. Conflicts
with ADR-004's core rationale.

**Async S3 library (aiobotocore)** — Would avoid the `to_thread()` wrapper
but adds a complex dependency with its own event loop management. The
`to_thread()` approach is simpler, proven in the local backend, and
sufficient for WikiMind's throughput needs.

**Abstract base class instead of Protocol** — An ABC would enforce the
interface at class definition time. We chose Protocol because it supports
structural subtyping (duck typing), avoids inheritance hierarchies, and
works with `isinstance()` checks via `@runtime_checkable`.

## Consequences

**Enables:**
- Cloud deployment on Fly.io, Railway, or any container platform
- Data durability across container restarts and redeployments
- Multi-region access when using Cloudflare R2's global network
- Works with any S3-compatible storage (AWS S3, MinIO, Backblaze B2)
- Local development remains zero-config (default is still filesystem)

**Constrains:**
- Append operations require a full read-modify-write cycle (acceptable
  for current usage patterns)
- `resolve_wiki_path()` and `resolve_raw_path()` still return local `Path`
  objects — callers that bypass `FileStorage` and access the filesystem
  directly will not work with R2 (by design — they should be migrated)

**Risks:**
- Network latency for file operations vs. local disk. Mitigated by the
  fact that WikiMind's file operations are not on the hot path of user
  requests (compilation is async, reads are cached in the DB summary).
- Append race conditions if two workers append simultaneously. Acceptable
  for single-instance deployments; would need locking for multi-instance.

## Amendment to ADR-004

ADR-004 specified filesystem paths as the storage location for wiki
articles. This ADR extends that decision: the **content** is still plain
markdown, but the **storage location** is now pluggable. When using R2,
files are stored as S3 objects with the same key structure
(`wiki/{concept}/{slug}.md`). The human-readability guarantee is preserved
because R2 objects can be downloaded and browsed as regular files.
