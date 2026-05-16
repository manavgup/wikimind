"""Compilation schema service — CRUD for user-defined compilation rules.

Compilation schemas define how sources are compiled into wiki articles:
article structure, style preferences, extraction directives, and concept
taxonomy rules. Only one schema per user can be active at a time.
"""

import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.errors import NotFoundError
from wikimind.models import (
    CompilationSchema,
    CompilationSchemaResponse,
)

log = structlog.get_logger()


def _json_loads_or_none(value: str | None) -> list[str] | None:
    """Parse a JSON string into a list, returning None for empty/null."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _to_response(schema: CompilationSchema) -> CompilationSchemaResponse:
    """Project a CompilationSchema row into the API-facing response."""
    return CompilationSchemaResponse(
        id=schema.id,
        name=schema.name,
        description=schema.description,
        is_active=schema.is_active,
        article_max_length=schema.article_max_length,
        required_sections=_json_loads_or_none(schema.required_sections),
        style=schema.style,
        focus=schema.focus,
        concept_max_depth=schema.concept_max_depth,
        concept_naming=schema.concept_naming,
        extraction_always_note=_json_loads_or_none(schema.extraction_always_note),
        extraction_ignore=_json_loads_or_none(schema.extraction_ignore),
        custom_directives=schema.custom_directives,
        created_at=schema.created_at,
        updated_at=schema.updated_at,
    )


class CompilationSchemaService:
    """Manage user-defined compilation schemas."""

    async def create_schema(
        self,
        session: AsyncSession,
        user_id: str,
        name: str,
        description: str | None = None,
        is_active: bool = False,
        article_max_length: int | None = None,
        required_sections: list[str] | None = None,
        style: str | None = None,
        focus: str | None = None,
        concept_max_depth: int | None = None,
        concept_naming: str | None = None,
        extraction_always_note: list[str] | None = None,
        extraction_ignore: list[str] | None = None,
        custom_directives: str | None = None,
    ) -> CompilationSchemaResponse:
        """Create a new compilation schema for the user.

        Args:
            session: Async database session.
            user_id: Owner of the schema.
            name: Display name (must be unique per user).
            description: Optional description of this schema's purpose.
            is_active: Whether this schema is the active one for compilation.
            article_max_length: Max word count for compiled articles.
            required_sections: List of section names articles must have.
            style: Freeform style directive for the LLM.
            focus: What to emphasize during compilation.
            concept_max_depth: Max taxonomy depth for concepts.
            concept_naming: Concept naming convention.
            extraction_always_note: Items to always extract from sources.
            extraction_ignore: Items to ignore during extraction.
            custom_directives: Freeform additional directives.

        Returns:
            The newly created schema.
        """
        # Deactivate other schemas if this one is active
        if is_active:
            await self._deactivate_all(session, user_id)

        schema = CompilationSchema(
            user_id=user_id,
            name=name,
            description=description,
            is_active=is_active,
            article_max_length=article_max_length,
            required_sections=json.dumps(required_sections) if required_sections else None,
            style=style,
            focus=focus,
            concept_max_depth=concept_max_depth,
            concept_naming=concept_naming,
            extraction_always_note=(json.dumps(extraction_always_note) if extraction_always_note else None),
            extraction_ignore=(json.dumps(extraction_ignore) if extraction_ignore else None),
            custom_directives=custom_directives,
        )
        session.add(schema)
        await session.flush()
        await session.refresh(schema)
        return _to_response(schema)

    async def list_schemas(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[CompilationSchemaResponse]:
        """List all compilation schemas for a user.

        Args:
            session: Async database session.
            user_id: Owner of the schemas.

        Returns:
            List of schemas ordered by creation time.
        """
        result = await session.execute(
            select(CompilationSchema).where(CompilationSchema.user_id == user_id).order_by(CompilationSchema.created_at)  # type: ignore[arg-type]
        )
        return [_to_response(s) for s in result.scalars().all()]

    async def get_schema(
        self,
        session: AsyncSession,
        schema_id: str,
        user_id: str,
    ) -> CompilationSchemaResponse:
        """Get a single compilation schema by ID.

        Args:
            session: Async database session.
            schema_id: Schema to retrieve.
            user_id: Must match the schema owner.

        Returns:
            The schema.

        Raises:
            NotFoundError: If the schema does not exist for this user.
        """
        schema = await self._get_schema(session, schema_id, user_id)
        return _to_response(schema)

    async def update_schema(
        self,
        session: AsyncSession,
        schema_id: str,
        user_id: str,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        article_max_length: int | None = None,
        required_sections: list[str] | None = None,
        style: str | None = None,
        focus: str | None = None,
        concept_max_depth: int | None = None,
        concept_naming: str | None = None,
        extraction_always_note: list[str] | None = None,
        extraction_ignore: list[str] | None = None,
        custom_directives: str | None = None,
    ) -> CompilationSchemaResponse:
        """Update a compilation schema.

        Args:
            session: Async database session.
            schema_id: Schema to update.
            user_id: Must match the schema owner.
            name: New name (optional).
            description: New description (optional).
            is_active: New active status (optional).
            article_max_length: New max length (optional).
            required_sections: New required sections (optional).
            style: New style directive (optional).
            focus: New focus directive (optional).
            concept_max_depth: New concept depth (optional).
            concept_naming: New naming convention (optional).
            extraction_always_note: New extraction notes (optional).
            extraction_ignore: New extraction ignores (optional).
            custom_directives: New custom directives (optional).

        Returns:
            The updated schema.

        Raises:
            NotFoundError: If the schema does not exist for this user.
        """
        schema = await self._get_schema(session, schema_id, user_id)

        if is_active is True:
            await self._deactivate_all(session, user_id)

        # Apply scalar field updates
        updates: dict[str, object] = {
            "name": name,
            "description": description,
            "is_active": is_active,
            "article_max_length": article_max_length,
            "style": style,
            "focus": focus,
            "concept_max_depth": concept_max_depth,
            "concept_naming": concept_naming,
            "custom_directives": custom_directives,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(schema, field, value)

        # Apply JSON list field updates
        json_updates: dict[str, list[str] | None] = {
            "required_sections": required_sections,
            "extraction_always_note": extraction_always_note,
            "extraction_ignore": extraction_ignore,
        }
        for field, value in json_updates.items():
            if value is not None:
                setattr(schema, field, json.dumps(value))

        schema.updated_at = utcnow_naive()
        session.add(schema)
        await session.flush()
        await session.refresh(schema)
        return _to_response(schema)

    async def delete_schema(
        self,
        session: AsyncSession,
        schema_id: str,
        user_id: str,
    ) -> None:
        """Delete a compilation schema.

        Args:
            session: Async database session.
            schema_id: Schema to delete.
            user_id: Must match the schema owner.

        Raises:
            NotFoundError: If the schema does not exist for this user.
        """
        schema = await self._get_schema(session, schema_id, user_id)
        await session.delete(schema)

    async def get_active_schema(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> CompilationSchema | None:
        """Return the active compilation schema for the user, or None.

        Args:
            session: Async database session.
            user_id: Owner of the schema.

        Returns:
            The active CompilationSchema row, or None if no schema is active.
        """
        result = await session.execute(
            select(CompilationSchema).where(
                CompilationSchema.user_id == user_id,
                CompilationSchema.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def _deactivate_all(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> None:
        """Deactivate all schemas for a user (ensures only one is active)."""
        result = await session.execute(
            select(CompilationSchema).where(
                CompilationSchema.user_id == user_id,
                CompilationSchema.is_active == True,  # noqa: E712
            )
        )
        for schema in result.scalars().all():
            schema.is_active = False
            session.add(schema)

    async def _get_schema(
        self,
        session: AsyncSession,
        schema_id: str,
        user_id: str,
    ) -> CompilationSchema:
        """Look up a schema by ID, scoped to the user."""
        result = await session.execute(
            select(CompilationSchema).where(
                CompilationSchema.id == schema_id,
                CompilationSchema.user_id == user_id,
            )
        )
        schema = result.scalar_one_or_none()
        if schema is None:
            msg = "Compilation schema not found"
            raise NotFoundError(msg)
        return schema
