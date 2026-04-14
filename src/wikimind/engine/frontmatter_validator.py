"""Post-write frontmatter validation for wiki .md files."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from wikimind.models import (
    AnswerFrontmatter,
    ConceptFrontmatter,
    IndexFrontmatter,
    MetaFrontmatter,
    SourceFrontmatter,
)

log = structlog.get_logger()

_FRONTMATTER_MODELS: dict[str, type] = {
    "source": SourceFrontmatter,
    "concept": ConceptFrontmatter,
    "answer": AnswerFrontmatter,
    "index": IndexFrontmatter,
    "meta": MetaFrontmatter,
}


def parse_frontmatter(file_path: Path) -> dict | None:
    """Extract YAML frontmatter from a markdown file."""
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        log.warning("frontmatter_validator: cannot read file", path=str(file_path))
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    yaml_block = text[3:end].strip()
    try:
        return yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        log.warning("frontmatter_validator: YAML parse error", path=str(file_path), error=str(exc))
        return None


def validate_frontmatter(file_path: Path) -> bool:
    """Validate frontmatter of a wiki .md file against its page-type model."""
    data = parse_frontmatter(file_path)
    if data is None:
        log.warning("frontmatter_validator: no frontmatter found", path=str(file_path))
        return False

    page_type = data.get("page_type")
    if page_type is None:
        log.warning("frontmatter_validator: missing page_type field", path=str(file_path))
        return False

    model_cls = _FRONTMATTER_MODELS.get(str(page_type))
    if model_cls is None:
        log.warning(
            "frontmatter_validator: unknown page_type",
            path=str(file_path),
            page_type=page_type,
        )
        return False

    try:
        model_cls(**data)
        return True
    except ValidationError as exc:
        log.warning(
            "frontmatter_validator: validation failed",
            path=str(file_path),
            page_type=page_type,
            errors=exc.error_count(),
            detail=str(exc),
        )
        return False
