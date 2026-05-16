"""Endpoints for user-defined compilation schemas (issue #420)."""

import structlog
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CompilationSchemaResponse,
    CreateCompilationSchemaRequest,
    UpdateCompilationSchemaRequest,
)
from wikimind.services.compilation_schema import CompilationSchemaService
from wikimind.services.factories import get_compilation_schema_service

log = structlog.get_logger()

router = APIRouter()


@router.post("", response_model=CompilationSchemaResponse, status_code=201)
async def create_schema(
    body: CreateCompilationSchemaRequest,
    session: AsyncSession = Depends(get_session),
    service: CompilationSchemaService = Depends(get_compilation_schema_service),
    user_id: str = Depends(get_current_user_id),
) -> CompilationSchemaResponse:
    """Create a new compilation schema."""
    return await service.create_schema(
        session,
        user_id=user_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        article_max_length=body.article_max_length,
        required_sections=body.required_sections,
        style=body.style,
        focus=body.focus,
        concept_max_depth=body.concept_max_depth,
        concept_naming=body.concept_naming,
        extraction_always_note=body.extraction_always_note,
        extraction_ignore=body.extraction_ignore,
        custom_directives=body.custom_directives,
    )


@router.get("", response_model=list[CompilationSchemaResponse])
async def list_schemas(
    session: AsyncSession = Depends(get_session),
    service: CompilationSchemaService = Depends(get_compilation_schema_service),
    user_id: str = Depends(get_current_user_id),
) -> list[CompilationSchemaResponse]:
    """List all compilation schemas for the current user."""
    return await service.list_schemas(session, user_id=user_id)


@router.get(
    "/{schema_id}",
    response_model=CompilationSchemaResponse,
    responses={404: {"description": "Schema not found"}},
)
async def get_schema(
    schema_id: str,
    session: AsyncSession = Depends(get_session),
    service: CompilationSchemaService = Depends(get_compilation_schema_service),
    user_id: str = Depends(get_current_user_id),
) -> CompilationSchemaResponse:
    """Get a compilation schema by ID."""
    return await service.get_schema(session, schema_id=schema_id, user_id=user_id)


@router.patch(
    "/{schema_id}",
    response_model=CompilationSchemaResponse,
    responses={404: {"description": "Schema not found"}},
)
async def update_schema(
    schema_id: str,
    body: UpdateCompilationSchemaRequest,
    session: AsyncSession = Depends(get_session),
    service: CompilationSchemaService = Depends(get_compilation_schema_service),
    user_id: str = Depends(get_current_user_id),
) -> CompilationSchemaResponse:
    """Update a compilation schema."""
    return await service.update_schema(
        session,
        schema_id=schema_id,
        user_id=user_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        article_max_length=body.article_max_length,
        required_sections=body.required_sections,
        style=body.style,
        focus=body.focus,
        concept_max_depth=body.concept_max_depth,
        concept_naming=body.concept_naming,
        extraction_always_note=body.extraction_always_note,
        extraction_ignore=body.extraction_ignore,
        custom_directives=body.custom_directives,
    )


@router.delete(
    "/{schema_id}",
    status_code=204,
    responses={404: {"description": "Schema not found"}},
)
async def delete_schema(
    schema_id: str,
    session: AsyncSession = Depends(get_session),
    service: CompilationSchemaService = Depends(get_compilation_schema_service),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Delete a compilation schema."""
    await service.delete_schema(session, schema_id=schema_id, user_id=user_id)
