"""Contradiction detection -- LLM-powered cross-article claim comparison.

For each concept bucket, enumerate article pairs and ask the LLM to identify
contradictory claims. Returns a list of ContradictionFinding instances that
the runner persists directly.

Phase 4 (issue #143): also creates ``contradicts`` typed Backlink rows so
contradictions are modelled as first-class edges in the knowledge graph.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.config import LinterConfig, Settings
from wikimind.engine.linter.prompts import (
    CONTRADICTION_BATCH_SYSTEM,
    CONTRADICTION_BATCH_USER,
    CONTRADICTION_SYSTEM_PROMPT,
    CONTRADICTION_USER_TEMPLATE,
    format_batch_pair_section,
)
from wikimind.engine.llm_router import LLMRouter
from wikimind.models import (
    Article,
    Backlink,
    CompletionRequest,
    Concept,
    ContradictionFinding,
    LintFindingKind,
    LintPairCache,
    LintReport,
    LintSeverity,
    RelationType,
    TaskType,
)
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()

_MAX_TITLE = 200
_MAX_CLAIM = 500
_MAX_CLAIMS_TEXT = 2000


def _content_hash(article_a_id: str, article_b_id: str) -> str:
    """Compute a stable sha256 for cross-run dedup of dismissed findings."""
    ids = sorted([article_a_id, article_b_id])
    raw = f"{LintFindingKind.CONTRADICTION}|{ids[0]}|{ids[1]}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _extract_claims(article: Article) -> list[str]:
    """Extract key claims from an article's markdown file."""
    try:
        content = resolve_wiki_path(article.file_path).read_text(encoding="utf-8")
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
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                claims.append(stripped)
                if len(claims) >= 10:
                    break

    return claims


async def _get_articles_for_concept(session: AsyncSession, concept_name: str) -> list[Article]:
    """Load articles whose concept_ids JSON array contains the given concept name."""
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


async def _create_contradiction_backlink(
    session: AsyncSession,
    article_a_id: str,
    article_b_id: str,
    context: str,
) -> None:
    """Create a ``contradicts`` typed Backlink for an article pair (bidirectional)."""
    for src, tgt in [(article_a_id, article_b_id), (article_b_id, article_a_id)]:
        existing = await session.execute(
            select(Backlink).where(
                Backlink.source_article_id == src,
                Backlink.target_article_id == tgt,
            )
        )
        if existing.scalars().first() is not None:
            continue
        session.add(
            Backlink(
                source_article_id=src,
                target_article_id=tgt,
                relation_type=RelationType.CONTRADICTS,
                context=context,
            )
        )
    await session.flush()


# ---------------------------------------------------------------------------
# Batch helpers (issue #138)
# ---------------------------------------------------------------------------


def _build_batch_prompt(
    pairs_with_claims: list[tuple[Article, Article, list[str], list[str]]],
) -> tuple[str, str]:
    """Build batch system + user prompt for multiple article pairs.

    Returns (system_str, user_str).
    """
    sections: list[str] = []
    for idx, (art_a, art_b, claims_a, claims_b) in enumerate(pairs_with_claims):
        claims_a_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_a)[:_MAX_CLAIMS_TEXT]
        claims_b_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_b)[:_MAX_CLAIMS_TEXT]
        sections.append(
            format_batch_pair_section(
                idx,
                art_a.title[:_MAX_TITLE],
                claims_a_text,
                art_b.title[:_MAX_TITLE],
                claims_b_text,
            )
        )
    user_msg = CONTRADICTION_BATCH_USER.format(
        pair_count=len(pairs_with_claims),
        pair_sections="\n\n".join(sections),
    )
    return CONTRADICTION_BATCH_SYSTEM, user_msg


def _parse_batch_response(response_data: list[dict], expected_count: int) -> dict[int, list[dict]]:
    """Map LLM batch response back to individual pairs by pair_index.

    Returns a dict from pair_index to list of contradiction dicts.
    Missing indices get an empty list.
    """
    result: dict[int, list[dict]] = {i: [] for i in range(expected_count)}
    for item in response_data:
        idx = item.get("pair_index")
        if idx is not None and 0 <= idx < expected_count:
            result[idx] = item.get("contradictions", [])
    return result


async def _run_batch(
    pairs_with_claims: list[tuple[Article, Article, list[str], list[str]]],
    concept_id: str | None,
    router: LLMRouter,
    settings: Settings,
    report_id: str,
    session: AsyncSession,
) -> list[ContradictionFinding]:
    """Run a batched LLM call for multiple pairs.

    On failure: retry once. On second failure: fall back to per-pair
    ``_compare_article_pair()`` calls.
    """
    cfg = settings.linter
    system_msg, user_msg = _build_batch_prompt(pairs_with_claims)

    request = CompletionRequest(
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=cfg.contradiction_llm_max_tokens * len(pairs_with_claims),
        temperature=cfg.contradiction_llm_temperature,
        response_format="json",
        task_type=TaskType.LINT,
    )

    for attempt in range(2):
        try:
            response = await router.complete(request, session=None)
            data = router.parse_json_response(response)
            # The response may be a list directly or wrapped in a key
            if isinstance(data, list):
                batch_results = data
            elif isinstance(data, dict) and "results" in data:
                batch_results = data["results"]
            else:
                raise ValueError(f"Unexpected batch response shape: {type(data)}")

            parsed = _parse_batch_response(batch_results, len(pairs_with_claims))

            findings: list[ContradictionFinding] = []
            for idx, (art_a, art_b, _ca, _cb) in enumerate(pairs_with_claims):
                for c in parsed.get(idx, []):
                    claim_a = c.get("article_a_claim", "")
                    claim_b = c.get("article_b_claim", "")
                    findings.append(
                        ContradictionFinding(
                            report_id=report_id,
                            severity=LintSeverity.WARN,
                            description=c.get("description", "Contradiction detected"),
                            content_hash=_content_hash(art_a.id, art_b.id),
                            article_a_id=art_a.id,
                            article_b_id=art_b.id,
                            article_a_claim=claim_a,
                            article_b_claim=claim_b,
                            llm_confidence=c.get("confidence", "medium"),
                            shared_concept_id=concept_id,
                        )
                    )
                    ctx = f"{claim_a} vs {claim_b}"
                    await _create_contradiction_backlink(session, art_a.id, art_b.id, ctx)
            return findings

        except Exception:
            if attempt == 0:
                log.warning("Batch LLM call failed, retrying once", exc_info=True)
            else:
                log.warning(
                    "Batch LLM retry failed, falling back to per-pair calls",
                    exc_info=True,
                )

    # Fallback: per-pair calls
    fallback_findings: list[ContradictionFinding] = []
    for art_a, art_b, _ca, _cb in pairs_with_claims:
        pair_findings = await _compare_article_pair(art_a, art_b, concept_id, router, settings, report_id, session)
        fallback_findings.extend(pair_findings)
    return fallback_findings


# ---------------------------------------------------------------------------
# Work collection and processing helpers
# ---------------------------------------------------------------------------


async def _collect_work(
    session: AsyncSession,
    cfg: LinterConfig,
) -> list[tuple[str | None, str, list[tuple[Article, Article]]]]:
    """Build the list of (concept_id, concept_name, pairs) work items."""
    concept_result = await session.execute(
        select(Concept)
        .order_by(Concept.article_count.desc())  # type: ignore[attr-defined]
        .limit(cfg.max_concepts_per_run)
    )
    concepts = list(concept_result.scalars().all())

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
            cid, cname = concept_obj.id, concept_obj.name
            articles = await _get_articles_for_concept(session, cname)
            if len(articles) < 2:
                continue
            pairs = list(itertools.combinations(articles, 2))
            if len(pairs) > cfg.max_contradiction_pairs_per_concept:
                pairs = random.sample(pairs, cfg.max_contradiction_pairs_per_concept)
            all_work.append((cid, cname, pairs))

    return all_work


def _findings_from_cached(
    cached: list[dict],
    report_id: str,
    article_a: Article,
    article_b: Article,
    concept_id: str | None,
) -> list[ContradictionFinding]:
    """Convert cached pair data into ContradictionFinding objects."""
    results: list[ContradictionFinding] = []
    for c in cached:
        claim_a = c.get("article_a_claim", "")
        claim_b = c.get("article_b_claim", "")
        results.append(
            ContradictionFinding(
                report_id=report_id,
                severity=LintSeverity.WARN,
                description=c.get("description", "Contradiction detected"),
                content_hash=_content_hash(article_a.id, article_b.id),
                article_a_id=article_a.id,
                article_b_id=article_b.id,
                article_a_claim=claim_a,
                article_b_claim=claim_b,
                llm_confidence=c.get("confidence", "medium"),
                shared_concept_id=concept_id,
            )
        )
    return results


def _cache_data_from_findings(new_findings: list[ContradictionFinding]) -> list[dict]:
    """Convert findings to serialisable cache data."""
    return [
        {
            "description": f.description,
            "article_a_claim": f.article_a_claim,
            "article_b_claim": f.article_b_claim,
            "confidence": f.llm_confidence,
        }
        for f in new_findings
    ]


async def _process_uncached_pairs(
    uncached_pairs: list[tuple[Article, Article, list[str], list[str]]],
    concept_id: str | None,
    router: LLMRouter,
    settings: Settings,
    report: LintReport,
    session: AsyncSession,
    checked: int,
) -> tuple[list[ContradictionFinding], int]:
    """Process uncached pairs via batch or per-pair LLM calls.

    Returns (findings, updated_checked_count).
    """
    cfg = settings.linter
    findings: list[ContradictionFinding] = []

    if cfg.contradiction_batch_enabled and len(uncached_pairs) > 1:
        for batch_start in range(0, len(uncached_pairs), cfg.contradiction_batch_size):
            batch = uncached_pairs[batch_start : batch_start + cfg.contradiction_batch_size]
            batch_findings = await _run_batch(batch, concept_id, router, settings, report.id, session)
            findings.extend(batch_findings)

            for _idx, (art_a, art_b, _ca, _cb) in enumerate(batch):
                if cfg.enable_pair_cache:
                    pair_findings = [
                        f for f in batch_findings if f.article_a_id == art_a.id and f.article_b_id == art_b.id
                    ]
                    await _save_pair_cache(session, art_a, art_b, _cache_data_from_findings(pair_findings))
                checked += 1
                report.checked_pairs = checked
                session.add(report)
                await session.flush()
    else:
        for art_a, art_b, _ca, _cb in uncached_pairs:
            new_findings = await _compare_article_pair(art_a, art_b, concept_id, router, settings, report.id, session)
            findings.extend(new_findings)
            if cfg.enable_pair_cache:
                await _save_pair_cache(session, art_a, art_b, _cache_data_from_findings(new_findings))
            checked += 1
            report.checked_pairs = checked
            session.add(report)
            await session.flush()

    return findings, checked


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def detect_contradictions(
    session: AsyncSession,
    router: LLMRouter,
    settings: Settings,
    report: LintReport,
) -> list[ContradictionFinding]:
    """For each concept, LLM-compare article pairs within that concept bucket."""
    cfg = settings.linter
    findings: list[ContradictionFinding] = []

    all_work = await _collect_work(session, cfg)

    total_pairs = sum(len(pairs) for _, _, pairs in all_work)
    report.total_pairs = total_pairs
    report.checked_pairs = 0
    session.add(report)
    await session.flush()

    checked = 0
    for concept_id, concept_name, pairs in all_work:  # type: ignore[assignment]
        log.info(
            "Checking contradictions in concept",
            concept=concept_name,
            pairs=len(pairs),
        )

        # Separate cached pairs from uncached pairs that need LLM calls
        uncached_pairs: list[tuple[Article, Article, list[str], list[str]]] = []
        for article_a, article_b in pairs:
            if cfg.enable_pair_cache:
                cached = await _check_pair_cache(session, article_a, article_b)
                if cached is not None:
                    log.info(
                        "Pair cache hit",
                        a=article_a.title[:30],
                        b=article_b.title[:30],
                    )
                    cached_findings = _findings_from_cached(cached, report.id, article_a, article_b, concept_id)
                    findings.extend(cached_findings)
                    for f in cached_findings:
                        ctx = f"{f.article_a_claim} vs {f.article_b_claim}"
                        await _create_contradiction_backlink(session, article_a.id, article_b.id, ctx)
                    checked += 1
                    report.checked_pairs = checked
                    session.add(report)
                    await session.flush()
                    continue

            # Collect claims for uncached pair
            claims_a = _extract_claims(article_a)
            claims_b = _extract_claims(article_b)
            if claims_a and claims_b:
                uncached_pairs.append((article_a, article_b, claims_a, claims_b))
            else:
                checked += 1
                report.checked_pairs = checked
                session.add(report)
                await session.flush()

        # Process uncached pairs: batch or per-pair
        new_findings, checked = await _process_uncached_pairs(
            uncached_pairs, concept_id, router, settings, report, session, checked
        )
        findings.extend(new_findings)

    return findings


# ---------------------------------------------------------------------------
# Single-pair comparison (used as fallback and for non-batched mode)
# ---------------------------------------------------------------------------


async def _compare_article_pair(
    article_a: Article,
    article_b: Article,
    concept_id: str | None,
    router: LLMRouter,
    settings: Settings,
    report_id: str,
    session: AsyncSession | None = None,
) -> list[ContradictionFinding]:
    """Compare a single article pair via LLM and return any findings."""
    cfg = settings.linter
    claims_a = _extract_claims(article_a)
    claims_b = _extract_claims(article_b)

    if not claims_a or not claims_b:
        return []

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
        claim_a = c.get("article_a_claim", "")
        claim_b = c.get("article_b_claim", "")
        finding = ContradictionFinding(
            report_id=report_id,
            severity=LintSeverity.WARN,
            description=description,
            content_hash=_content_hash(article_a.id, article_b.id),
            article_a_id=article_a.id,
            article_b_id=article_b.id,
            article_a_claim=claim_a,
            article_b_claim=claim_b,
            llm_confidence=c.get("confidence", "medium"),
            shared_concept_id=concept_id,
        )
        findings.append(finding)

        if session is not None:
            ctx = f"{claim_a} vs {claim_b}"
            await _create_contradiction_backlink(session, article_a.id, article_b.id, ctx)

    return findings
