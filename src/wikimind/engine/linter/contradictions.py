"""Contradiction detection — LLM-powered cross-article claim comparison.

For each concept bucket, enumerate article pairs and ask the LLM to identify
contradictory claims. Returns a list of ContradictionFinding instances that
the runner persists directly.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from pathlib import Path

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.config import Settings
from wikimind.engine.linter.prompts import CONTRADICTION_SYSTEM_PROMPT, CONTRADICTION_USER_TEMPLATE
from wikimind.engine.llm_router import LLMRouter
from wikimind.models import (
    Article,
    CompletionRequest,
    Concept,
    ContradictionFinding,
    LintFindingKind,
    LintPairCache,
    LintReport,
    LintSeverity,
    TaskType,
)

log = structlog.get_logger()


def _content_hash(article_a_id: str, article_b_id: str) -> str:
    """Compute a stable sha256 for cross-run dedup of dismissed findings.

    Keyed by sorted article pair IDs only — not the LLM description,
    which varies between runs. Dismissing any contradiction between
    articles A and B dismisses all future contradictions for that pair.
    """
    ids = sorted([article_a_id, article_b_id])
    raw = f"{LintFindingKind.CONTRADICTION}|{ids[0]}|{ids[1]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _extract_claims(article: Article) -> list[str]:
    """Extract key claims from an article's markdown file.

    Looks for a "Key Claims" section and parses bullet points.
    Falls back to the first few non-empty lines of the body if no section found.
    """
    try:
        content = Path(article.file_path).read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return []

    lines = content.split("\n")
    claims: list[str] = []
    in_claims_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## key claims") or stripped.lower().startswith("## key_claims"):
            in_claims_section = True
            continue
        if in_claims_section:
            if stripped.startswith("## "):
                break
            if stripped.startswith("- ") or stripped.startswith("* "):
                claims.append(stripped[2:].strip())

    if not claims:
        # Fallback: use first non-heading, non-empty lines (up to 10)
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                claims.append(stripped)
                if len(claims) >= 10:
                    break

    return claims


async def _get_articles_for_concept(session: AsyncSession, concept_name: str) -> list[Article]:
    """Load articles whose concept_ids JSON array contains the given concept name.

    Uses ORM query + Python filter for database portability (works on both
    SQLite and PostgreSQL without dialect-specific JSON functions).
    """
    result = await session.execute(select(Article))
    all_articles = list(result.scalars().all())
    return [a for a in all_articles if concept_name in (a.concept_ids or [])]


async def _check_pair_cache(session: AsyncSession, article_a: Article, article_b: Article) -> list[dict] | None:
    """Check if we have a cached result for this article pair."""
    ids = sorted([article_a.id, article_b.id])
    result = await session.execute(
        select(LintPairCache).where(
            LintPairCache.article_a_id == ids[0],
            LintPairCache.article_b_id == ids[1],
        )
    )
    cached = result.scalars().first()
    if not cached:
        return None
    # Check if articles have been updated since cache was written
    current_a = str(article_a.updated_at) if ids[0] == article_a.id else str(article_b.updated_at)
    current_b = str(article_b.updated_at) if ids[1] == article_b.id else str(article_a.updated_at)
    if cached.article_a_updated_at == current_a and cached.article_b_updated_at == current_b:
        return json.loads(cached.result_json)
    return None


async def _save_pair_cache(
    session: AsyncSession,
    article_a: Article,
    article_b: Article,
    result_data: list[dict],
) -> None:
    """Save LLM result to pair cache."""
    ids = sorted([article_a.id, article_b.id])
    a_art = article_a if ids[0] == article_a.id else article_b
    b_art = article_b if ids[1] == article_b.id else article_a
    # Delete old cache entry if exists
    await session.execute(
        delete(LintPairCache).where(
            LintPairCache.article_a_id == ids[0],  # type: ignore[arg-type]
            LintPairCache.article_b_id == ids[1],  # type: ignore[arg-type]
        )
    )
    session.add(
        LintPairCache(
            id=hashlib.sha256(f"{ids[0]}|{ids[1]}".encode()).hexdigest()[:32],
            article_a_id=ids[0],
            article_b_id=ids[1],
            article_a_updated_at=str(a_art.updated_at),
            article_b_updated_at=str(b_art.updated_at),
            result_json=json.dumps(result_data),
        )
    )


async def detect_contradictions(
    session: AsyncSession,
    router: LLMRouter,
    settings: Settings,
    report: LintReport,
) -> list[ContradictionFinding]:
    """For each concept, LLM-compare article pairs within that concept bucket.

    Updates report.total_pairs and report.checked_pairs for progress tracking.
    Uses pair cache to skip LLM calls for unchanged article pairs.
    """
    cfg = settings.linter
    findings: list[ContradictionFinding] = []

    # Load concepts
    concept_result = await session.execute(
        select(Concept)
        .order_by(Concept.article_count.desc())  # type: ignore[attr-defined]
        .limit(cfg.max_concepts_per_run)
    )
    concepts = list(concept_result.scalars().all())

    # Collect all pairs across concepts first (for progress tracking)
    all_work: list[tuple[str | None, str, list[tuple[Article, Article]]]] = []

    if not concepts:
        log.info("No concepts found, falling back to top-N article comparison")
        article_result = await session.execute(
            select(Article)
            .order_by(Article.updated_at.desc())  # type: ignore[attr-defined]
            .limit(cfg.max_contradiction_pairs_per_concept * 2)
        )
        articles = list(article_result.scalars().all())
        pairs = list(itertools.combinations(articles, 2))
        if len(pairs) > cfg.max_contradiction_pairs_per_concept:
            pairs = random.sample(pairs, cfg.max_contradiction_pairs_per_concept)
        all_work.append((None, "all-articles", pairs))
    else:
        for concept_obj in concepts:
            concept_id, concept_name = concept_obj.id, concept_obj.name
            articles = await _get_articles_for_concept(session, concept_name)
            if len(articles) < 2:
                continue
            pairs = list(itertools.combinations(articles, 2))
            if len(pairs) > cfg.max_contradiction_pairs_per_concept:
                pairs = random.sample(pairs, cfg.max_contradiction_pairs_per_concept)
            all_work.append((concept_id, concept_name, pairs))

    # Compute total pairs and update report for progress
    total_pairs = sum(len(pairs) for _, _, pairs in all_work)
    report.total_pairs = total_pairs
    report.checked_pairs = 0
    session.add(report)
    await session.flush()

    checked = 0
    for concept_id, concept_name, pairs in all_work:  # type: ignore[assignment]
        log.info("Checking contradictions in concept", concept=concept_name, pairs=len(pairs))

        for article_a, article_b in pairs:
            # Check cache first
            if cfg.enable_pair_cache:
                cached = await _check_pair_cache(session, article_a, article_b)
                if cached is not None:
                    log.info("Pair cache hit", a=article_a.title[:30], b=article_b.title[:30])
                    for c in cached:
                        findings.append(
                            ContradictionFinding(
                                report_id=report.id,
                                severity=LintSeverity.WARN,
                                description=c.get("description", "Contradiction detected"),
                                content_hash=_content_hash(article_a.id, article_b.id),
                                article_a_id=article_a.id,
                                article_b_id=article_b.id,
                                article_a_claim=c.get("article_a_claim", ""),
                                article_b_claim=c.get("article_b_claim", ""),
                                llm_confidence=c.get("confidence", "medium"),
                                shared_concept_id=concept_id,
                            )
                        )
                    checked += 1
                    report.checked_pairs = checked
                    session.add(report)
                    await session.flush()
                    continue

            # LLM call
            new_findings = await _compare_article_pair(article_a, article_b, concept_id, router, settings, report.id)
            findings.extend(new_findings)

            # Save to cache
            if cfg.enable_pair_cache:
                cache_data = [
                    {
                        "description": f.description,
                        "article_a_claim": f.article_a_claim,
                        "article_b_claim": f.article_b_claim,
                        "confidence": f.llm_confidence,
                    }
                    for f in new_findings
                ]
                await _save_pair_cache(session, article_a, article_b, cache_data)

            checked += 1
            report.checked_pairs = checked
            session.add(report)
            await session.flush()

    return findings


async def _compare_article_pair(
    article_a: Article,
    article_b: Article,
    concept_id: str | None,
    router: LLMRouter,
    settings: Settings,
    report_id: str,
) -> list[ContradictionFinding]:
    """Compare a single article pair via LLM and return any findings."""
    cfg = settings.linter
    claims_a = _extract_claims(article_a)
    claims_b = _extract_claims(article_b)

    if not claims_a or not claims_b:
        return []

    # Sanitize inputs to limit prompt injection surface
    _MAX_TITLE = 200
    _MAX_CLAIM = 500
    _MAX_CLAIMS_TEXT = 2000
    claims_a_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_a)[:_MAX_CLAIMS_TEXT]
    claims_b_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_b)[:_MAX_CLAIMS_TEXT]

    user_msg = CONTRADICTION_USER_TEMPLATE.format(
        title_a=article_a.title[:_MAX_TITLE],
        claims_a=claims_a_text,
        title_b=article_b.title[:_MAX_TITLE],
        claims_b=claims_b_text,
    )

    request = CompletionRequest(
        system=CONTRADICTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=cfg.contradiction_llm_max_tokens,
        temperature=cfg.contradiction_llm_temperature,
        response_format="json",
        task_type=TaskType.LINT,
    )

    try:
        response = await router.complete(request, session=None)
        data = router.parse_json_response(response)
    except Exception:
        log.warning(
            "LLM call failed for contradiction check",
            article_a=article_a.title,
            article_b=article_b.title,
            exc_info=True,
        )
        return []

    contradictions = data.get("contradictions", [])
    findings: list[ContradictionFinding] = []

    for c in contradictions:
        description = c.get("description", "Contradiction detected")
        finding = ContradictionFinding(
            report_id=report_id,
            severity=LintSeverity.WARN,
            description=description,
            content_hash=_content_hash(article_a.id, article_b.id),
            article_a_id=article_a.id,
            article_b_id=article_b.id,
            article_a_claim=c.get("article_a_claim", ""),
            article_b_claim=c.get("article_b_claim", ""),
            llm_confidence=c.get("confidence", "medium"),
            shared_concept_id=concept_id,
        )
        findings.append(finding)

    return findings
