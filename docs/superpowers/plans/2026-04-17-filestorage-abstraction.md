# FileStorage Abstraction Implementation Plan (PR 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all direct `Path` file I/O with a `FileStorage` protocol so wiki and raw files can later be stored in R2/S3 without changing application logic.

**Architecture:** A `FileStorage` protocol defines async read/write/delete/list. `LocalFileStorage` wraps current `Path` operations with `asyncio.to_thread()`. Two singleton factories (`get_wiki_storage()`, `get_raw_storage()`) return the appropriate backend. `Article.file_path` and `Source.file_path` change from absolute to relative paths. A one-time migration converts existing records.

**Tech Stack:** Python 3.11+, asyncio, pathlib, pytest, SQLModel

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/wikimind/storage.py` | `FileStorage` protocol, `LocalFileStorage`, singleton factories |
| Create | `tests/unit/test_storage.py` | Unit tests for `LocalFileStorage` |
| Modify | `src/wikimind/engine/compiler.py` | Use `wiki_storage` for article writes/deletes |
| Modify | `src/wikimind/engine/concept_compiler.py` | Use `wiki_storage` for concept page writes/deletes/reads |
| Modify | `src/wikimind/engine/qa_agent.py` | Use `wiki_storage` for answer writes and article reads |
| Modify | `src/wikimind/engine/frontmatter_validator.py` | Accept `str` content instead of `Path` |
| Modify | `src/wikimind/services/wiki_index.py` | Use `wiki_storage` for index.md and health page writes |
| Modify | `src/wikimind/services/activity_log.py` | Use `wiki_storage` for log append |
| Modify | `src/wikimind/services/wiki.py` | Use `wiki_storage` for article reads |
| Modify | `src/wikimind/engine/linter/contradictions.py` | Use `wiki_storage` for article reads |
| Modify | `src/wikimind/jobs/sweep.py` | Use `wiki_storage` for article reads/writes |
| Modify | `src/wikimind/jobs/worker.py` | Use `wiki_storage` + `raw_storage` for reads |
| Modify | `src/wikimind/ingest/service.py` | Use `raw_storage` for source file writes |
| Modify | `src/wikimind/database.py` | Add `_migrate_to_relative_paths()` in `init_db()` |

---

### Task 1: Create FileStorage protocol and LocalFileStorage

**Files:**
- Create: `src/wikimind/storage.py`
- Test: `tests/unit/test_storage.py`

- [ ] **Step 1: Write tests for LocalFileStorage**

```python
# tests/unit/test_storage.py
"""Tests for the FileStorage abstraction."""

from __future__ import annotations

import pytest

from wikimind.storage import LocalFileStorage


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && source .venv/bin/activate && pytest tests/unit/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wikimind.storage'`

- [ ] **Step 3: Implement FileStorage protocol and LocalFileStorage**

```python
# src/wikimind/storage.py
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

    async def read(self, relative_path: str) -> str: ...
    async def read_bytes(self, relative_path: str) -> bytes: ...
    async def write(self, relative_path: str, content: str) -> None: ...
    async def write_bytes(self, relative_path: str, data: bytes) -> None: ...
    async def append(self, relative_path: str, content: str) -> None: ...
    async def delete(self, relative_path: str) -> None: ...
    async def exists(self, relative_path: str) -> bool: ...
    async def list(self, prefix: str = "") -> list[str]: ...


class LocalFileStorage:
    """Local filesystem implementation of FileStorage."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _resolve(self, relative_path: str) -> Path:
        return self.root / relative_path

    async def read(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def read_bytes(self, relative_path: str) -> bytes:
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.read_bytes)

    async def write(self, relative_path: str, content: str) -> None:
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    async def write_bytes(self, relative_path: str, data: bytes) -> None:
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def append(self, relative_path: str, content: str) -> None:
        path = self._resolve(relative_path)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        def _append():
            with path.open("a", encoding="utf-8") as fh:
                fh.write(content)

        await asyncio.to_thread(_append)

    async def delete(self, relative_path: str) -> None:
        path = self._resolve(relative_path)
        if path.exists():
            await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, relative_path: str) -> bool:
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.exists)

    async def list(self, prefix: str = "") -> list[str]:
        search_dir = self._resolve(prefix) if prefix else self.root

        def _list():
            if not search_dir.exists():
                return []
            return [
                str(p.relative_to(self.root))
                for p in search_dir.rglob("*")
                if p.is_file()
            ]

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_storage.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/storage.py tests/unit/test_storage.py
git commit -s -m "feat: add FileStorage protocol and LocalFileStorage implementation"
```

---

### Task 2: Refactor frontmatter_validator to accept content string

The validator currently reads from disk via `Path.read_text()`. Change it to accept content as a string so callers can pass content they already have or read through storage.

**Files:**
- Modify: `src/wikimind/engine/frontmatter_validator.py`
- Modify: `src/wikimind/engine/compiler.py:586` (call site)

- [ ] **Step 1: Update parse_frontmatter to accept string content**

In `src/wikimind/engine/frontmatter_validator.py`, change `parse_frontmatter` to accept a `str` instead of `Path`:

```python
# Replace the existing parse_frontmatter function (lines 30-50)
def parse_frontmatter(content: str) -> dict | None:
    """Extract YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return None

    end = content.find("---", 3)
    if end == -1:
        return None

    yaml_block = content[3:end].strip()
    try:
        return yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        log.warning("frontmatter_validator: YAML parse error", error=str(exc))
        return None
```

- [ ] **Step 2: Update validate_frontmatter to accept string content**

```python
# Replace the existing validate_frontmatter function (lines 53-85)
def validate_frontmatter(content: str) -> bool:
    """Validate frontmatter of wiki markdown content against its page-type model."""
    data = parse_frontmatter(content)
    if data is None:
        log.warning("frontmatter_validator: no frontmatter found")
        return False

    page_type = data.get("page_type")
    if page_type is None:
        log.warning("frontmatter_validator: missing page_type field")
        return False

    model_cls = _FRONTMATTER_MODELS.get(str(page_type))
    if model_cls is None:
        log.warning(
            "frontmatter_validator: unknown page_type",
            page_type=page_type,
        )
        return False

    try:
        model_cls(**data)
        return True
    except ValidationError as exc:
        log.warning(
            "frontmatter_validator: validation failed",
            page_type=page_type,
            errors=exc.error_count(),
            detail=str(exc),
        )
        return False
```

- [ ] **Step 3: Update call site in compiler.py**

In `src/wikimind/engine/compiler.py`, the call at line 586 is:
```python
validate_frontmatter(file_path)
```

Change to pass the content string (the `content` variable is in scope from the write above):
```python
validate_frontmatter(content)
```

- [ ] **Step 4: Run existing tests**

Run: `pytest tests/ -v -k "frontmatter or compiler" --timeout=30`
Expected: All pass (the validator tests should still work since they construct content)

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/frontmatter_validator.py src/wikimind/engine/compiler.py
git commit -s -m "refactor: frontmatter validator accepts content string instead of Path"
```

---

### Task 3: Refactor compiler.py to use wiki_storage

**Files:**
- Modify: `src/wikimind/engine/compiler.py`

- [ ] **Step 1: Add storage import at top of compiler.py**

Add to the imports section:
```python
from wikimind.storage import get_wiki_storage
```

- [ ] **Step 2: Refactor `_write_article_file()` (line 511)**

Current code constructs a `Path`, creates a directory, writes content, and returns the `Path`. Change to:

```python
def _write_article_file(
    self,
    result: CompilationResult,
    source: Source,
    slug: str,
    resolved: list[ResolvedBacklink],
    unresolved: list[str],
) -> str:
    """Write article markdown file. Returns the relative path for DB storage."""
    # Determine relative path: {first_concept_slug}/{slug}.md
    concept = result.concepts[0] if result.concepts else "uncategorized"
    concept_slug = slugify(concept)
    relative_path = f"{concept_slug}/{slug}.md"

    # Build the markdown content (same as before — all the frontmatter
    # and body construction stays identical, just the write changes)
    # ... (keep all existing content construction code unchanged) ...

    # The content variable is built the same way as before.
    # Replace the old write:
    #   file_path.write_text(content, encoding="utf-8")
    # With storage write (sync wrapper since this is a sync method):
    import asyncio
    storage = get_wiki_storage()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # We're inside an async context — use to_thread
        # But this is a sync method, so just use the underlying Path directly
        from pathlib import Path
        full_path = Path(get_settings().data_dir) / "wiki" / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
    else:
        asyncio.run(storage.write(relative_path, content))

    validate_frontmatter(content)
    return relative_path
```

**Wait — this is getting complicated because `_write_article_file` is a sync method called from async context.** The cleaner approach: since `LocalFileStorage` wraps sync `Path` operations in `to_thread()`, and `_write_article_file` is itself sync, just use Path directly but construct the relative path. Store the relative path in the DB. The storage abstraction is used by readers and by the async callers.

Let me revise. The simpler approach:

```python
def _write_article_file(
    self,
    result: CompilationResult,
    source: Source,
    slug: str,
    resolved: list[ResolvedBacklink],
    unresolved: list[str],
) -> str:
    """Write article markdown to wiki storage. Returns relative path."""
    wiki_dir = Path(self.settings.data_dir) / "wiki"
    concept = result.concepts[0] if result.concepts else "uncategorized"
    concept_slug = slugify(concept)
    concept_dir = wiki_dir / concept_slug
    concept_dir.mkdir(parents=True, exist_ok=True)
    file_path = concept_dir / f"{slug}.md"

    # ... (all existing content construction stays exactly the same) ...

    file_path.write_text(content, encoding="utf-8")
    validate_frontmatter(content)

    # Return relative path for DB storage instead of absolute Path
    return str(file_path.relative_to(wiki_dir))
```

- [ ] **Step 3: Update `_create_article()` to store relative path**

At line 336, change:
```python
file_path=str(file_path),
```
to:
```python
file_path=relative_path,
```

(where `relative_path` is the string returned by `_write_article_file()`)

- [ ] **Step 4: Update `_replace_article_in_place()` to use relative paths**

At line 403, the delete uses an absolute path from the DB:
```python
old_path = Path(existing.file_path)
old_path.unlink(missing_ok=True)
```

Change to resolve through wiki_dir:
```python
wiki_dir = Path(self.settings.data_dir) / "wiki"
old_path = wiki_dir / existing.file_path
old_path.unlink(missing_ok=True)
```

At line 417, change:
```python
existing.file_path = str(new_path)
```
to:
```python
existing.file_path = relative_path
```
(where `relative_path` is returned by `_write_article_file()`)

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_compiler.py tests/unit/test_jobs.py -v --timeout=60`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/engine/compiler.py
git commit -s -m "refactor: compiler stores relative wiki paths, returns string from _write_article_file"
```

---

### Task 4: Refactor concept_compiler.py to use relative paths

**Files:**
- Modify: `src/wikimind/engine/concept_compiler.py`

- [ ] **Step 1: Refactor `_write_concept_file()` to return relative path**

Change the return type from `Path` to `str` and return relative path:

```python
def _write_concept_file(
    self, compilation: ConceptCompilationResult, concept: Concept, source_articles: list[Article]
) -> str:
    """Write concept page markdown. Returns relative path."""
    wiki_dir = Path(self.settings.data_dir) / "wiki"
    slug = slugify(concept.name)
    concept_dir = wiki_dir / slug
    concept_dir.mkdir(parents=True, exist_ok=True)
    file_path = concept_dir / f"{slug}.md"

    # ... (all existing content construction stays the same) ...

    file_path.write_text(content, encoding="utf-8")
    return str(file_path.relative_to(wiki_dir))
```

- [ ] **Step 2: Update `_save_concept_page()` to use relative paths**

At line 237 (delete existing file):
```python
Path(existing.file_path).unlink(missing_ok=True)
```
Change to:
```python
wiki_dir = Path(self.settings.data_dir) / "wiki"
(wiki_dir / existing.file_path).unlink(missing_ok=True)
```

At line 240 (store file_path):
```python
existing.file_path = str(file_path)
```
Change to:
```python
existing.file_path = relative_path
```
(where `relative_path` is returned by `_write_concept_file()`)

At line 262 (new article):
```python
file_path=str(file_path),
```
Change to:
```python
file_path=relative_path,
```

- [ ] **Step 3: Update `_build_source_material()` to resolve paths through wiki_dir**

At line 129:
```python
fc = Path(article.file_path).read_text(encoding="utf-8")
```
Change to:
```python
wiki_dir = Path(get_settings().data_dir) / "wiki"
fc = (wiki_dir / article.file_path).read_text(encoding="utf-8")
```

Add `from wikimind.config import get_settings` to the imports if not already present.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_concept_compiler.py -v --timeout=60`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/concept_compiler.py
git commit -s -m "refactor: concept compiler stores relative wiki paths"
```

---

### Task 5: Refactor wiki readers (wiki.py, contradictions.py, qa_agent.py)

**Files:**
- Modify: `src/wikimind/services/wiki.py`
- Modify: `src/wikimind/engine/linter/contradictions.py`
- Modify: `src/wikimind/engine/qa_agent.py`

- [ ] **Step 1: Update `_read_article_content()` in wiki.py (line 59)**

```python
def _read_article_content(file_path: str) -> str:
    """Read article content, resolving relative path through wiki_dir."""
    from wikimind.config import get_settings

    path = Path(file_path)
    if not path.is_absolute():
        path = Path(get_settings().data_dir) / "wiki" / file_path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return ""
```

Note: The `is_absolute()` check provides backward compatibility with any unmigrated absolute paths.

- [ ] **Step 2: Update `_extract_claims()` in contradictions.py (line 61)**

```python
def _extract_claims(article: Article) -> list[str]:
    """Extract key claims from article for contradiction detection."""
    from wikimind.config import get_settings

    path = Path(article.file_path)
    if not path.is_absolute():
        path = Path(get_settings().data_dir) / "wiki" / article.file_path
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return []
    # ... rest of function unchanged ...
```

- [ ] **Step 3: Update `_read_article_content()` in qa_agent.py (line 498)**

```python
def _read_article_content(self, file_path: str) -> str | None:
    """Read article content, resolving relative path through wiki_dir."""
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(self.settings.data_dir) / "wiki" / file_path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_wiki_service.py tests/unit/test_linter.py tests/unit/test_qa_agent.py -v --timeout=60`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/services/wiki.py src/wikimind/engine/linter/contradictions.py src/wikimind/engine/qa_agent.py
git commit -s -m "refactor: wiki readers resolve relative paths through wiki_dir"
```

---

### Task 6: Refactor qa_agent.py writer and wiki_index.py

**Files:**
- Modify: `src/wikimind/engine/qa_agent.py`
- Modify: `src/wikimind/services/wiki_index.py`

- [ ] **Step 1: Update `_file_back_thread()` in qa_agent.py (line 528)**

Change the write at line 583-587 to store relative paths:

```python
# Replace the wiki_dir construction and write:
wiki_dir = Path(self.settings.data_dir) / "wiki" / "qa-answers"
wiki_dir.mkdir(parents=True, exist_ok=True)
slug = conversation.id
file_path = wiki_dir / f"{slug}.md"
file_path.write_text(markdown, encoding="utf-8")

# Store relative path in DB:
relative_path = f"qa-answers/{slug}.md"
```

And at line 614 (update existing):
```python
# Resolve the existing relative path to write:
wiki_dir = Path(self.settings.data_dir) / "wiki"
abs_path = wiki_dir / existing_article.file_path
abs_path.parent.mkdir(parents=True, exist_ok=True)
abs_path.write_text(markdown, encoding="utf-8")
```

Update the Article creation to use `relative_path` instead of `str(file_path)`.

- [ ] **Step 2: Update `regenerate_index_md()` in wiki_index.py (line 70)**

Change the write to store relative path:

```python
# Keep the current write logic using Path:
wiki_dir = Path(settings.data_dir) / "wiki"
wiki_dir.mkdir(parents=True, exist_ok=True)
index_path = wiki_dir / "index.md"
# ... build lines ...
index_path.write_text("".join(lines), encoding="utf-8")

# Return relative path:
return "index.md"
```

Change return type from `Path` to `str`.

- [ ] **Step 3: Update `generate_meta_health_page()` in wiki_index.py (line 167)**

Same pattern:
```python
meta_dir = Path(settings.data_dir) / "wiki" / "meta"
meta_dir.mkdir(parents=True, exist_ok=True)
health_path = meta_dir / "wiki-health.md"
# ... build lines ...
health_path.write_text("".join(lines), encoding="utf-8")
return "meta/wiki-health.md"
```

Change return type from `Path` to `str`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -v -k "qa_agent or wiki_index or index" --timeout=60`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/qa_agent.py src/wikimind/services/wiki_index.py
git commit -s -m "refactor: qa_agent and wiki_index store relative paths"
```

---

### Task 7: Refactor activity_log.py

**Files:**
- Modify: `src/wikimind/services/activity_log.py`

- [ ] **Step 1: Update `append_log_entry()` (line 20)**

The activity log appends to `wiki/log.md`. Keep the Path-based write but construct through wiki_dir:

```python
def append_log_entry(op: str, title: str, extra: dict | None = None) -> None:
    # ... existing line construction unchanged ...

    wiki_dir = Path(get_settings().data_dir) / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    log_path = wiki_dir / "log.md"

    with log_path.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write(_LOG_HEADER)
        fh.writelines(lines)
```

This function is already correct — it uses `settings.data_dir / "wiki"`. No change needed for relative paths since the log file isn't tracked in the DB. The key change is just ensuring it goes through a consistent path construction.

Actually, verify: is this function already correct? If so, skip this task.

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_activity_log.py -v --timeout=30`
Expected: All pass

- [ ] **Step 3: Commit (if any changes were made)**

```bash
git add src/wikimind/services/activity_log.py
git commit -s -m "refactor: activity log uses consistent wiki_dir path construction"
```

---

### Task 8: Refactor sweep.py and worker.py

**Files:**
- Modify: `src/wikimind/jobs/sweep.py`
- Modify: `src/wikimind/jobs/worker.py`

- [ ] **Step 1: Update `_sweep_single_article()` in sweep.py (line 36)**

The sweep reads and writes article files using `article.file_path`. Resolve relative paths:

```python
async def _sweep_single_article(
    article: Article,
    session: AsyncSession,
) -> bool:
    from wikimind.config import get_settings

    wiki_dir = Path(get_settings().data_dir) / "wiki"
    file_path = Path(article.file_path)
    if not file_path.is_absolute():
        file_path = wiki_dir / article.file_path

    if not file_path.exists():
        log.warning("sweep: file not found, skipping", article_id=article.id, path=str(file_path))
        return False

    content = file_path.read_text(encoding="utf-8")

    # ... (all existing resolution logic unchanged) ...

    # Write back (line 85):
    file_path.write_text(new_content, encoding="utf-8")

    # ... (backlink creation unchanged) ...
```

- [ ] **Step 2: Update `compile_source()` in worker.py (line 97)**

The worker reads `source.file_path` for compilation. Resolve relative paths through raw_dir:

```python
# At line 96-97, change:
text_path = Path(source.file_path)
# to:
raw_dir = Path(get_settings().data_dir) / "raw"
text_path = Path(source.file_path)
if not text_path.is_absolute():
    text_path = raw_dir / source.file_path
content = text_path.read_text(encoding="utf-8")
```

- [ ] **Step 3: Update article read for embeddings in worker.py (line 142)**

```python
# Change:
content = Path(article.file_path).read_text(encoding="utf-8")
# To:
wiki_dir = Path(get_settings().data_dir) / "wiki"
article_path = Path(article.file_path)
if not article_path.is_absolute():
    article_path = wiki_dir / article.file_path
content = article_path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Update `recompile_article()` in worker.py (line 253)**

```python
# Change:
content = Path(source.file_path).read_text(encoding="utf-8")
# To:
raw_dir = Path(get_settings().data_dir) / "raw"
source_path = Path(source.file_path)
if not source_path.is_absolute():
    source_path = raw_dir / source.file_path
content = source_path.read_text(encoding="utf-8")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_sweep.py tests/unit/test_sweep_session.py tests/unit/test_jobs.py -v --timeout=60`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/jobs/sweep.py src/wikimind/jobs/worker.py
git commit -s -m "refactor: sweep and worker resolve relative file paths through data_dir"
```

---

### Task 9: Refactor ingest/service.py to store relative raw paths

**Files:**
- Modify: `src/wikimind/ingest/service.py`

- [ ] **Step 1: Update URLAdapter.ingest() (line 453-458)**

Change from storing absolute path to relative:

```python
raw_dir = Path(settings.data_dir) / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
(raw_dir / f"{source.id}.html").write_text(html, encoding="utf-8")
text_path = raw_dir / f"{source.id}.txt"
text_path.write_text(downloaded, encoding="utf-8")
# Store relative path:
source.file_path = f"{source.id}.txt"
```

- [ ] **Step 2: Update PDFAdapter.ingest() (line 608-637)**

```python
raw_dir = Path(settings.data_dir) / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
raw_pdf_path = raw_dir / f"{source.id}.pdf"
raw_pdf_path.write_bytes(file_bytes)
# ... extraction logic ...
text_path = raw_dir / f"{source.id}.txt"
text_path.write_text(clean_text, encoding="utf-8")
# Store relative path:
source.file_path = f"{source.id}.txt"
```

- [ ] **Step 3: Update TextAdapter.ingest() (line 1062-1066)**

```python
raw_dir = Path(settings.data_dir) / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
text_path = raw_dir / f"{source.id}.txt"
text_path.write_text(content, encoding="utf-8")
# Store relative path:
source.file_path = f"{source.id}.txt"
```

- [ ] **Step 4: Update YouTubeAdapter.ingest() (line 1127-1131)**

```python
raw_dir = Path(settings.data_dir) / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
text_path = raw_dir / f"{source.id}.txt"
text_path.write_text(transcript_text, encoding="utf-8")
# Store relative path:
source.file_path = f"{source.id}.txt"
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_ingest_service.py tests/unit/test_pdf_adapter.py -v --timeout=60`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/ingest/service.py
git commit -s -m "refactor: ingest adapters store relative raw paths"
```

---

### Task 10: Add path migration for existing DB records

**Files:**
- Modify: `src/wikimind/database.py`
- Test: `tests/unit/test_storage.py` (add migration test)

- [ ] **Step 1: Write migration test**

Add to `tests/unit/test_storage.py`:

```python
from wikimind.database import _migrate_to_relative_paths


@pytest.mark.asyncio
async def test_migrate_absolute_to_relative(db_session, tmp_path, monkeypatch):
    """Existing absolute paths are converted to relative on startup."""
    from wikimind.config import get_settings

    settings = get_settings()
    wiki_dir = str(Path(settings.data_dir) / "wiki")
    raw_dir = str(Path(settings.data_dir) / "raw")

    # Create article with absolute path
    from wikimind.models import Article
    article = Article(
        slug="test-article",
        title="Test",
        file_path=f"{wiki_dir}/concept/test-article.md",
    )
    db_session.add(article)
    await db_session.commit()

    # Run migration
    await _migrate_to_relative_paths(db_session)

    await db_session.refresh(article)
    assert article.file_path == "concept/test-article.md"
```

- [ ] **Step 2: Implement `_migrate_to_relative_paths()`**

Add to `src/wikimind/database.py`:

```python
from wikimind.config import get_settings


async def _migrate_to_relative_paths(session: AsyncSession) -> None:
    """Convert absolute file_path values to relative paths.

    Runs once at startup. Idempotent — already-relative paths are skipped.
    """
    from wikimind.models import Article, Source

    settings = get_settings()
    wiki_prefix = str(Path(settings.data_dir) / "wiki") + "/"
    raw_prefix = str(Path(settings.data_dir) / "raw") + "/"

    # Migrate Article.file_path (wiki-relative)
    result = await session.execute(select(Article).where(Article.file_path.startswith("/")))
    for article in result.scalars().all():
        if article.file_path.startswith(wiki_prefix):
            article.file_path = article.file_path[len(wiki_prefix):]
            session.add(article)

    # Migrate Source.file_path (raw-relative)
    result = await session.execute(select(Source).where(Source.file_path.startswith("/")))
    for source in result.scalars().all():
        if source.file_path and source.file_path.startswith(raw_prefix):
            source.file_path = source.file_path[len(raw_prefix):]
            session.add(source)

    await session.commit()
```

- [ ] **Step 3: Call migration from init_db()**

In `src/wikimind/database.py`, in the `init_db()` function, after `create_all`:

```python
async def init_db():
    # ... existing create_all and migration logic ...

    # Convert absolute paths to relative (idempotent)
    async with get_session_factory()() as session:
        await _migrate_to_relative_paths(session)
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/unit/test_storage.py -v --timeout=30`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/database.py tests/unit/test_storage.py
git commit -s -m "feat: add migration to convert absolute file paths to relative"
```

---

### Task 11: Add resolve_path helper and clean up is_absolute checks

**Files:**
- Modify: `src/wikimind/storage.py`

- [ ] **Step 1: Add resolve helpers to storage.py**

Instead of repeating `is_absolute()` checks in every reader, add utility functions:

```python
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
```

- [ ] **Step 2: Replace inline is_absolute checks with resolve helpers**

In all the files modified in Tasks 5, 8 — replace the inline `is_absolute()` pattern:

```python
# Before (repeated in every file):
path = Path(article.file_path)
if not path.is_absolute():
    path = Path(get_settings().data_dir) / "wiki" / article.file_path

# After:
from wikimind.storage import resolve_wiki_path
path = resolve_wiki_path(article.file_path)
```

Apply in: `wiki.py`, `contradictions.py`, `qa_agent.py`, `sweep.py`, `worker.py`

- [ ] **Step 3: Add test for resolve helpers**

Add to `tests/unit/test_storage.py`:

```python
from wikimind.storage import resolve_wiki_path, resolve_raw_path


def test_resolve_wiki_path_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    from wikimind.config import get_settings
    get_settings.cache_clear()
    result = resolve_wiki_path("concept/article.md")
    assert result == tmp_path / "wiki" / "concept" / "article.md"
    get_settings.cache_clear()


def test_resolve_wiki_path_absolute():
    result = resolve_wiki_path("/absolute/path/article.md")
    assert result == Path("/absolute/path/article.md")


def test_resolve_raw_path_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    from wikimind.config import get_settings
    get_settings.cache_clear()
    result = resolve_raw_path("source-id.txt")
    assert result == tmp_path / "raw" / "source-id.txt"
    get_settings.cache_clear()
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/ -v --timeout=120`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/storage.py src/wikimind/services/wiki.py src/wikimind/engine/linter/contradictions.py src/wikimind/engine/qa_agent.py src/wikimind/jobs/sweep.py src/wikimind/jobs/worker.py tests/unit/test_storage.py
git commit -s -m "refactor: add resolve_wiki_path/resolve_raw_path helpers, remove inline is_absolute checks"
```

---

### Task 12: Final integration test and cleanup

**Files:**
- Test: `tests/unit/test_storage.py` (add integration test)
- Modify: `tests/conftest.py` (clear storage caches)

- [ ] **Step 1: Clear storage caches in test fixture**

In `tests/conftest.py`, update the `_isolated_data_dir` fixture to clear storage singletons:

```python
@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point WIKIMIND_DATA_DIR at a tmp dir for every test."""
    data_dir = tmp_path / "wikimind"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    # Clear storage singletons so they pick up the new data_dir
    from wikimind.storage import get_wiki_storage, get_raw_storage
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()
    yield data_dir
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()
```

- [ ] **Step 2: Add integration test**

Add to `tests/unit/test_storage.py`:

```python
@pytest.mark.asyncio
async def test_local_storage_is_file_storage_protocol():
    """LocalFileStorage satisfies the FileStorage protocol."""
    from wikimind.storage import FileStorage, LocalFileStorage
    storage = LocalFileStorage(root=Path("/tmp/test"))
    assert isinstance(storage, FileStorage)


def test_get_wiki_storage_returns_local(tmp_path, monkeypatch):
    """get_wiki_storage() returns a LocalFileStorage rooted at wiki_dir."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    from wikimind.config import get_settings
    from wikimind.storage import LocalFileStorage, get_wiki_storage
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
    from wikimind.config import get_settings
    from wikimind.storage import LocalFileStorage, get_raw_storage
    get_settings.cache_clear()
    get_raw_storage.cache_clear()
    storage = get_raw_storage()
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == tmp_path / "raw"
    get_settings.cache_clear()
    get_raw_storage.cache_clear()
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --timeout=120`
Expected: All pass

- [ ] **Step 4: Run pre-commit**

Run: `make pre-commit`
Expected: All hooks pass

- [ ] **Step 5: Run mypy on changed files**

Run: `mypy src/wikimind/storage.py src/wikimind/engine/compiler.py src/wikimind/engine/concept_compiler.py src/wikimind/engine/qa_agent.py src/wikimind/engine/frontmatter_validator.py src/wikimind/services/wiki_index.py src/wikimind/services/wiki.py src/wikimind/engine/linter/contradictions.py src/wikimind/jobs/sweep.py src/wikimind/jobs/worker.py src/wikimind/ingest/service.py src/wikimind/database.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/unit/test_storage.py
git commit -s -m "test: add integration tests and clear storage caches in test fixtures"
```
