"""Contradiction detection — LLM-powered cross-article claim comparison.

For each concept bucket, enumerate article pairs and ask the LLM to identify
contradictory claims. Returns a list of ContradictionFinding instances that
the runner persists directly.
"""

from __future__ import annotations

import hashlib
import itertools
import random
from pathlib import Path

import structlog
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import Settings
from wikimind.engine.linter.prompts import CONTRADICTION_SYSTEM_PROMPT, CONTRADICTION_USER_TEMPLATE
from wikimind.engine.llm_router import LLMRouter
from wikimind.models import (
    Article,
    CompletionRequest,
    ContradictionFinding,
    LintFindingKind,
    LintSeverity,
    TaskType,
)

log = structlog.get_logger()


def _content_hash(article_a_id: str, article_b_id: str, description: str) -> str:
    """Compute a stable sha256 for cross-run dedup of dismissed findings."""
    ids = sorted([article_a_id, article_b_id])
    raw = f"{LintFindingKind.CONTRADICTION}|{ids[0]}|{ids[1]}|{description}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _extract_claims(article: Article, data_dir: str) -> list[str]:
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


async def _get_articles_for_concept(session: AsyncSession, concept_id: str) -> list[Article]:
    """Load articles whose concept_ids JSON array contains the given concept id."""
    result = await session.execute(
        text(
            "SELECT article.id, article.slug, article.title, article.file_path, "
            "article.concept_ids, article.confidence, article.linter_score, "
            "article.summary, article.created_at, article.updated_at, "
            "article.source_ids, article.provider "
            "FROM article, json_each(article.concept_ids) AS je "
            "WHERE je.value = :concept_id"
        ),
        {"concept_id": concept_id},
    )
    rows = result.fetchall()
    articles = []
    for row in rows:
        articles.append(
            Article(
                id=row[0],
                slug=row[1],
                title=row[2],
                file_path=row[3],
                concept_ids=row[4],
                confidence=row[5],
                linter_score=row[6],
                summary=row[7],
                created_at=row[8],
                updated_at=row[9],
                source_ids=row[10],
                provider=row[11],
            )
        )
    return articles


async def detect_contradictions(
    session: AsyncSession,
    router: LLMRouter,
    settings: Settings,
    report_id: str,
) -> list[ContradictionFinding]:
    """For each concept, LLM-compare article pairs within that concept bucket.

    Args:
        session: Async database session.
        router: LLM router for making completion calls.
        settings: Application settings with linter config.
        report_id: The parent LintReport ID.

    Returns:
        List of ContradictionFinding instances ready for persistence.
    """
    cfg = settings.linter
    findings: list[ContradictionFinding] = []

    # Load concepts, ordered by most recently updated articles first
    result = await session.execute(
        text("SELECT c.id, c.name FROM concept c ORDER BY c.article_count DESC LIMIT :limit"),
        {"limit": cfg.max_concepts_per_run},
    )
    concepts = result.fetchall()

    if not concepts:
        # Fallback: no concepts exist — compare top articles by updated_at
        log.info("No concepts found, falling back to top-N article comparison")
        result = await session.execute(
            text(
                "SELECT id, slug, title, file_path, concept_ids, confidence, "
                "linter_score, summary, created_at, updated_at, source_ids, provider "
                "FROM article ORDER BY updated_at DESC "
                "LIMIT :limit"
            ),
            {"limit": cfg.max_contradiction_pairs_per_concept * 2},
        )
        rows = result.fetchall()
        all_articles = [
            Article(
                id=r[0],
                slug=r[1],
                title=r[2],
                file_path=r[3],
                concept_ids=r[4],
                confidence=r[5],
                linter_score=r[6],
                summary=r[7],
                created_at=r[8],
                updated_at=r[9],
                source_ids=r[10],
                provider=r[11],
            )
            for r in rows
        ]
        pairs = list(itertools.combinations(all_articles, 2))
        if len(pairs) > cfg.max_contradiction_pairs_per_concept:
            pairs = random.sample(pairs, cfg.max_contradiction_pairs_per_concept)

        for article_a, article_b in pairs:
            new_findings = await _compare_article_pair(article_a, article_b, None, router, settings, report_id)
            findings.extend(new_findings)
        return findings

    for concept_row in concepts:
        concept_id, concept_name = concept_row
        articles = await _get_articles_for_concept(session, concept_id)

        if len(articles) < 2:
            continue

        pairs = list(itertools.combinations(articles, 2))
        if len(pairs) > cfg.max_contradiction_pairs_per_concept:
            pairs = random.sample(pairs, cfg.max_contradiction_pairs_per_concept)

        log.info(
            "Checking contradictions in concept",
            concept=concept_name,
            pairs=len(pairs),
        )

        for article_a, article_b in pairs:
            new_findings = await _compare_article_pair(article_a, article_b, concept_id, router, settings, report_id)
            findings.extend(new_findings)

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
    claims_a = _extract_claims(article_a, settings.data_dir)
    claims_b = _extract_claims(article_b, settings.data_dir)

    if not claims_a or not claims_b:
        return []

    claims_a_text = "\n".join(f"- {c}" for c in claims_a)
    claims_b_text = "\n".join(f"- {c}" for c in claims_b)

    user_msg = CONTRADICTION_USER_TEMPLATE.format(
        title_a=article_a.title,
        claims_a=claims_a_text,
        title_b=article_b.title,
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
            content_hash=_content_hash(article_a.id, article_b.id, description),
            article_a_id=article_a.id,
            article_b_id=article_b.id,
            article_a_claim=c.get("article_a_claim", ""),
            article_b_claim=c.get("article_b_claim", ""),
            llm_confidence=c.get("confidence", "medium"),
            shared_concept_id=concept_id,
        )
        findings.append(finding)

    return findings
