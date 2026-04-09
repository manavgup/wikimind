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
from pathlib import Path

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.database import get_session_factory
from wikimind.engine.wikilink_resolver import resolve_backlink_candidates
from wikimind.models import Article, Backlink, Job, JobStatus, JobType

log = structlog.get_logger()

# Matches [[Title]] — the double-bracket syntax for unresolved wikilinks.
# Resolved links use single-bracket markdown syntax [Title](/wiki/id),
# which this pattern does not match because it requires `[[` to open.
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


async def _sweep_single_article(
    article: Article,
    session: AsyncSession,
) -> bool:
    """Resolve unresolved brackets in a single article's .md file.

    Returns True if any replacement was made (file rewritten + backlinks
    persisted), False if the file was unchanged.
    """
    file_path = Path(article.file_path)
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

    resolved, _unresolved = await resolve_backlink_candidates(unique_candidates, session, exclude_article_id=article.id)

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

    # Persist Backlink rows (per-row commit + IntegrityError catch)
    for rb in resolved:
        bl = Backlink(
            source_article_id=article.id,
            target_article_id=rb.target_id,
            context=rb.candidate_text,
        )
        session.add(bl)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            log.debug(
                "sweep: skipped duplicate backlink",
                source=article.id,
                target=rb.target_id,
            )

    log.info(
        "sweep: article updated",
        article_id=article.id,
        resolved_count=len(resolved),
    )
    return True


async def sweep_wikilinks(ctx) -> None:
    """Walk every article's .md file, promote unresolved [[brackets]] to real links.

    For each article:
    1. Read the file from disk.
    2. Find all [[Title]] tokens via regex.
    3. Run them through resolve_backlink_candidates() against the current
       Article table (excluding self).
    4. For each newly-resolved link:
       a. Replace the [[Title]] in the file with [Title](/wiki/{target_id}).
       b. Create a Backlink row (skip on IntegrityError -- it means the
          row already exists from a prior sweep or fresh compile).
    5. If any replacements were made, write the file back to disk.

    Idempotent: running the sweep on a wiki with no unresolved brackets
    is a no-op (no file writes, no DB changes).
    """
    log.info("sweep_wikilinks started")

    async with get_session_factory()() as session:
        # Create job record
        job = Job(
            job_type=JobType.SWEEP_WIKILINKS,
            status=JobStatus.RUNNING,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()

        try:
            result = await session.execute(select(Article))
            articles = list(result.scalars().all())

            if not articles:
                job.status = JobStatus.COMPLETE
                job.result_summary = "No articles to sweep"
                session.add(job)
                await session.commit()
                log.info("sweep_wikilinks complete: no articles")
                return

            updated_count = 0
            for article in articles:
                changed = await _sweep_single_article(article, session)
                if changed:
                    updated_count += 1

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Swept {len(articles)} articles, updated {updated_count}"
            session.add(job)
            await session.commit()

            log.info(
                "sweep_wikilinks complete",
                total=len(articles),
                updated=updated_count,
            )

        except Exception as e:
            log.error("sweep_wikilinks failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utcnow_naive()
            session.add(job)
            await session.commit()
