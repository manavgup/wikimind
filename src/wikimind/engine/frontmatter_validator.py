"""Post-write frontmatter validation for wiki .md files."""

from __future__ import annotations

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
