"""ConceptKindDef registry — seeds built-in kinds and validates prompt templates."""

import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.models import ConceptKindDef

PROMPT_TEMPLATES: dict[str, str] = {
    "concept_synthesis_topic": "",
    "concept_synthesis_person": "",
    "concept_synthesis_org": "",
    "concept_synthesis_product": "",
    "concept_synthesis_paper": "",
}

_BUILTIN_KINDS: list[dict[str, str | None]] = [
    {
        "name": "topic",
        "prompt_template_key": "concept_synthesis_topic",
        "required_sections": json.dumps(
            ["overview", "key_themes", "consensus_conflicts", "open_questions", "timeline", "sources"]
        ),
        "linter_rules": json.dumps(["has_summary", "has_sources"]),
        "description": "General topic concept page",
    },
    {
        "name": "person",
        "prompt_template_key": "concept_synthesis_person",
        "required_sections": json.dumps(["overview", "contributions", "timeline", "associated_work", "sources"]),
        "linter_rules": json.dumps(["has_known_facts", "has_summary"]),
        "description": "Person or individual concept page",
    },
    {
        "name": "organization",
        "prompt_template_key": "concept_synthesis_org",
        "required_sections": json.dumps(["overview", "products", "key_people", "research", "sources"]),
        "linter_rules": json.dumps(["has_summary", "has_sources"]),
        "description": "Organization or company concept page",
    },
    {
        "name": "product",
        "prompt_template_key": "concept_synthesis_product",
        "required_sections": json.dumps(["overview", "features", "claims", "evolution", "sources"]),
        "linter_rules": json.dumps(["has_summary", "has_sources"]),
        "description": "Product or tool concept page",
    },
    {
        "name": "paper",
        "prompt_template_key": "concept_synthesis_paper",
        "required_sections": json.dumps(["overview", "key_claims", "methodology", "limitations", "sources"]),
        "linter_rules": json.dumps(["has_summary", "has_sources"]),
        "description": "Academic paper or research concept page",
    },
]


async def seed_builtin_kinds(session: AsyncSession) -> None:
    """Idempotently create the five built-in ConceptKindDef rows."""
    for kind_data in _BUILTIN_KINDS:
        name = kind_data["name"]
        result = await session.execute(select(ConceptKindDef).where(ConceptKindDef.name == name))
        existing = result.scalar_one_or_none()
        if existing is None:
            kind = ConceptKindDef(**kind_data)  # type: ignore[arg-type]
            session.add(kind)
    await session.commit()


class RegistryTemplateMismatchError(Exception):
    """Raised when a ConceptKindDef references a missing prompt template."""


async def validate_registry_against_prompts(session: AsyncSession) -> None:
    """Check that every ConceptKindDef prompt_template_key exists in PROMPT_TEMPLATES."""
    result = await session.execute(select(ConceptKindDef))
    kinds = result.scalars().all()
    missing: list[str] = []
    for kind in kinds:
        if kind.prompt_template_key not in PROMPT_TEMPLATES:
            missing.append(f"{kind.name} -> {kind.prompt_template_key}")
    if missing:
        raise RegistryTemplateMismatchError(
            f"ConceptKindDef rows reference missing prompt templates: {', '.join(missing)}"
        )
