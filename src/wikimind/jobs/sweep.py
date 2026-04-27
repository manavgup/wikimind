"""Incremental wikilink resolution sweep (B3 backfill).

Walks every article's .md file, finds unresolved ``[[brackets]]``, runs
them through :func:`resolve_backlink_candidates`, and promotes matches
to real ``[text](/wiki/<id>)`` markdown links with corresponding
:class:`Backlink` rows.

No LLM calls -- pure deterministic resolution against the current
Article table. Idempotent: re-running on a wiki with nothing to
promote is a no-op.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import or_
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.database import get_session_factory
from wikimind.engine.wikilink_resolver import resolve_backlink_candidates
from wikimind.models import Article, Backlink, Job, JobStatus, JobType, PageType
from wikimind.storage import resolve_wiki_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Matches [[Title]] — the double-bracket syntax for unresolved wikilinks.
# Resolved links use single-bracket markdown syntax [Title](/wiki/id),
# which this pattern does not match because it requires `[[` to open.
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


async def _sweep_single_article(
    article_id: str,
    session: AsyncSession,
) -> bool:
    """Resolve unresolved brackets in a single article's .md file.

    Each article gets its own session (passed in by the caller) to avoid
    identity-map conflicts when multiple articles create Backlinks for
    overlapping article pairs (issue #163).

    The article is re-loaded from the database inside this session to
    prevent greenlet_spawn errors caused by accessing attributes on an
    object bound to a different session (issue #168).

    Returns True if any replacement was made (file rewritten + backlinks
    persisted), False if the file was unchanged.
    """
    article = await session.get(Article, article_id)
    if article is None:
        log.warning("sweep: article not found, skipping", article_id=article_id)
        return False

    file_path = resolve_wiki_path(article.file_path, user_id=article.user_id)
    if not file_path.exists():
        log.warning("sweep: file not found, skipping", article_id=article.id, path=str(file_path))
        return False

    content = file_path.read_text(encoding="utf-8")

    # Collect all unique bracket texts
    matches = _WIKILINK_RE.findall(content)
    if not matches:
        return False

    # Deduplicate while preserving order
    unique_candidates = list(dict.fromkeys(matches))

    resolved, _unresolved = await resolve_backlink_candidates(
        unique_candidates,
        session,
        exclude_article_id=article.id,
        user_id=article.user_id,
    )

    if not resolved:
        return False

    # Build a lookup: candidate_text (case-insensitive) -> resolved backlink
    resolved_map: dict[str, tuple[str, str]] = {}
    for rb in resolved:
        resolved_map[rb.candidate_text.lower()] = (rb.target_id, rb.candidate_text)

    # Replace [[Title]] -> [Title](/wiki/{target_id}) using a replacement function
    def _replace_match(m: re.Match) -> str:
        bracket_text = m.group(1)
        entry = resolved_map.get(bracket_text.lower())
        if entry is not None:
            target_id, _candidate = entry
            return f"[{bracket_text}](/wiki/{target_id})"
        return m.group(0)  # Leave unresolved brackets as-is

    new_content = _WIKILINK_RE.sub(_replace_match, content)

    if new_content == content:
        return False  # pragma: no cover — defensive; resolved non-empty implies change

    # Write the updated file
    file_path.write_text(new_content, encoding="utf-8")

    # Persist Backlink rows — use get-or-create to handle duplicates
    # gracefully. We check each backlink by composite PK and only insert
    # when it doesn't already exist, avoiding identity-map conflicts
    # (#163) and SAWarning/IntegrityError from merge().
    for rb in resolved:
        existing = await session.get(Backlink, (article.id, rb.target_id))
        if existing is not None:
            existing.context = rb.candidate_text
        else:
            bl = Backlink(
                source_article_id=article.id,
                target_article_id=rb.target_id,
                context=rb.candidate_text,
                user_id=article.user_id,
            )
            session.add(bl)

    # Single commit for all backlinks of this article.
    await session.commit()

    log.info(
        "sweep: article updated",
        article_id=article.id,
        resolved_count=len(resolved),
    )
    return True


async def _cleanup_orphaned_concept_pages(
    session: AsyncSession,
    user_id: str | None = None,
) -> int:
    """Delete concept-page Article rows whose markdown files are missing on disk.

    When a concept page's file disappears (e.g. interrupted write, manual
    deletion, or failed recompilation), the DB row becomes orphaned.  This
    removes the Article and its Backlink rows so downstream code no longer
    warns about missing files (#169).

    Returns the number of orphaned rows cleaned up.
    """
    stmt = select(Article).where(Article.page_type == PageType.CONCEPT)
    if user_id is not None:
        stmt = stmt.where(Article.user_id == user_id)
    result = await session.execute(stmt)
    concept_articles = list(result.scalars().all())

    cleaned = 0
    for article in concept_articles:
        file_path = resolve_wiki_path(article.file_path, user_id=article.user_id)
        if file_path.exists():
            continue

        # Bulk-delete backlinks referencing the orphaned article to avoid
        # SQLAlchemy cascade conflicts with the Article delete below.
        await session.execute(
            sa_delete(Backlink).where(
                or_(
                    Backlink.source_article_id == article.id,  # type: ignore[arg-type]
                    Backlink.target_article_id == article.id,  # type: ignore[arg-type]
                )
            )
        )
        await session.execute(
            sa_delete(Article).where(Article.id == article.id)  # type: ignore[arg-type]
        )
        cleaned += 1
        log.warning(
            "sweep: removed orphaned concept page (file missing)",
            article_id=article.id,
            slug=article.slug,
            path=str(file_path),
        )

    if cleaned:
        await session.commit()

    return cleaned


async def sweep_wikilinks(_ctx, user_id: str | None = None) -> None:
    """Walk articles' .md files, promote unresolved [[brackets]] to real links.

    For each article:
    1. Read the file from disk.
    2. Find all [[Title]] tokens via regex.
    3. Run them through resolve_backlink_candidates() against the current
       Article table (excluding self).
    4. For each newly-resolved link:
       a. Replace the [[Title]] in the file with [Title](/wiki/{target_id}).
       b. Create a Backlink row (skip if it already exists from a prior
          sweep or fresh compile).
    5. If any replacements were made, write the file back to disk.

    Each article is processed in its own database session to avoid
    identity-map conflicts between articles (issue #163). The Job
    record is managed by a separate outer session.

    Idempotent: running the sweep on a wiki with no unresolved brackets
    is a no-op (no file writes, no DB changes).

    Args:
        ctx: ARQ context (unused in dev mode).
        user_id: Optional owner — when provided, only that user's articles
            are swept. ``None`` sweeps articles with no user_id (legacy).
    """
    log.info("sweep_wikilinks started", user_id=user_id)

    session_factory = get_session_factory()

    async with session_factory() as job_session:
        # Create job record
        job = Job(
            job_type=JobType.SWEEP_WIKILINKS,
            status=JobStatus.RUNNING,
            user_id=user_id,
            started_at=utcnow_naive(),
        )
        job_session.add(job)
        await job_session.commit()

        try:
            # Clean up orphaned concept pages before sweeping (#169).
            async with session_factory() as cleanup_session:
                orphan_count = await _cleanup_orphaned_concept_pages(cleanup_session, user_id=user_id)
            if orphan_count:
                log.info("sweep: cleaned orphaned concept pages", count=orphan_count)

            # Load article IDs in a separate short-lived session so the
            # objects are not bound to job_session.  This avoids greenlet_spawn
            # errors when per-article sessions access overlapping Backlink
            # rows that would conflict with job_session's identity map (#168).
            async with session_factory() as list_session:
                stmt = select(Article.id)
                if user_id is not None:
                    stmt = stmt.where(Article.user_id == user_id)
                result = await list_session.execute(stmt)
                article_ids: list[str] = list(result.scalars().all())

            if not article_ids:
                job.status = JobStatus.COMPLETE
                job.result_summary = "No articles to sweep"
                job_session.add(job)
                await job_session.commit()
                log.info("sweep_wikilinks complete: no articles")
                return

            updated_count = 0
            for aid in article_ids:
                # Each article gets its own session to prevent identity-map
                # conflicts when both the source compiler and the sweep
                # create Backlinks for overlapping article pairs (#163, #168).
                async with session_factory() as article_session:
                    changed = await _sweep_single_article(aid, article_session)
                    if changed:
                        updated_count += 1

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Swept {len(article_ids)} articles, updated {updated_count}"
            job_session.add(job)
            await job_session.commit()

            log.info(
                "sweep_wikilinks complete",
                total=len(article_ids),
                updated=updated_count,
            )

        except Exception as e:  # Intentional broad catch — job runner must not crash
            log.error("sweep_wikilinks failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utcnow_naive()
            job_session.add(job)
            await job_session.commit()
