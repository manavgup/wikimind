"""MkDocs hook that auto-generates the Features page from evidence HTML files.

Parses docs/evidence/index.html to extract feature cards grouped by wave,
then writes docs/docs/overview/features.md with a hand-written intro section
followed by an auto-generated evidence catalogue.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.features")

# ---------------------------------------------------------------------------
# Evidence index parser
# ---------------------------------------------------------------------------

_WAVE_RE = re.compile(
    r'<h2 class="wave-header">(.*?)</h2>\s*<div class="card-grid">(.*?)</div>\s*</div>',
    re.DOTALL,
)

_CARD_RE = re.compile(
    r'<a class="card" href="(?P<href>[^"]+)">\s*'
    r'<div class="card-title">(?P<title>.*?)</div>\s*'
    r'<div class="card-pr">(?P<pr>.*?)</div>\s*'
    r'<div class="card-description">(?P<desc>.*?)</div>\s*'
    r"</a>",
    re.DOTALL,
)

_BADGE_RE = re.compile(r'<span class="badge[^"]*">([^<]+)</span>')

_STAT_RE = re.compile(
    r'<div class="stat-value">([^<]+)</div>\s*<div class="stat-label">([^<]+)</div>',
    re.DOTALL,
)


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _BADGE_RE.sub("", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _extract_badges(text: str) -> list[str]:
    return _BADGE_RE.findall(text)


def _parse_evidence_index(index_path: Path) -> tuple[dict[str, str], list[tuple[str, list[dict]]]]:
    """Return (stats_dict, [(wave_name, [card_dict, ...]), ...])."""
    content = index_path.read_text(encoding="utf-8")

    # Stats
    stats: dict[str, str] = {}
    for match in _STAT_RE.finditer(content):
        stats[match.group(2).strip()] = match.group(1).strip()

    # Waves
    waves: list[tuple[str, list[dict]]] = []
    for wave_match in _WAVE_RE.finditer(content):
        wave_name = _strip_html(wave_match.group(1))
        cards_html = wave_match.group(2)
        cards: list[dict] = []
        for card_match in _CARD_RE.finditer(cards_html):
            badges = _extract_badges(card_match.group("desc"))
            cards.append(
                {
                    "href": card_match.group("href"),
                    "title": _strip_html(card_match.group("title")),
                    "pr": _strip_html(card_match.group("pr")),
                    "description": _strip_html(card_match.group("desc")),
                    "badges": badges,
                }
            )
        waves.append((wave_name, cards))

    return stats, waves


# ---------------------------------------------------------------------------
# Markdown generator
# ---------------------------------------------------------------------------

_INTRO = """\
# Features

WikiMind transforms raw information into a structured, interconnected knowledge
base.  This page is **auto-generated** from the
[evidence catalogue](https://github.com/manavgup/wikimind/tree/main/docs/evidence).

"""


def _generate_markdown(stats: dict[str, str], waves: list[tuple[str, list[dict]]]) -> str:
    lines: list[str] = [_INTRO]

    # Stats banner
    if stats:
        lines.append("| " + " | ".join(stats.values()) + " |")
        lines.append("| " + " | ".join("---" for _ in stats) + " |")
        lines.append("| " + " | ".join(f"**{k}**" for k in stats) + " |")
        lines.append("")

    for wave_name, cards in waves:
        lines.append(f"## {wave_name}")
        lines.append("")
        if not cards:
            lines.append("_No features documented yet._")
            lines.append("")
            continue
        for card in cards:
            badge_str = ""
            if card["badges"]:
                badge_str = " ".join(f'<span class="badge">{b}</span>' for b in card["badges"])
                badge_str = f"  {badge_str}"
            lines.append(f"### {card['title']}")
            lines.append("")
            lines.append(f"**{card['pr']}**{badge_str}")
            lines.append("")
            lines.append(card["description"])
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*This page is generated automatically by the `features.py` MkDocs hook.*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MkDocs hook entry point
# ---------------------------------------------------------------------------


def on_pre_build(config: dict, **_kwargs: object) -> None:
    """Generate overview/features.md from evidence/index.html before build."""
    docs_root = Path(config["docs_dir"])  # docs/docs/
    evidence_index = docs_root.parent / "evidence" / "index.html"

    if not evidence_index.exists():
        log.warning("features hook: %s not found, skipping generation", evidence_index)
        return

    stats, waves = _parse_evidence_index(evidence_index)
    if not waves:
        log.warning("features hook: no waves parsed from %s, skipping", evidence_index)
        return

    md = _generate_markdown(stats, waves)
    target = docs_root / "overview" / "features.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")
    total_features = sum(len(cards) for _, cards in waves)
    log.info(
        "features hook: generated %s (%d waves, %d features)",
        target,
        len(waves),
        total_features,
    )
