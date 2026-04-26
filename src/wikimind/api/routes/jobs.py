"""Endpoints for managing async compilation and linting jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import Job, JobTriggerResponse
from wikimind.services.compiler import CompilerService, get_compiler_service
from wikimind.services.linter import LinterService, get_linter_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


@router.get("", response_model=list[Job])
async def list_jobs(
    status: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    service: CompilerService = Depends(get_compiler_service),
    user_id: str = Depends(get_current_user_id),
):
    """List jobs with optional status filter."""
    return await service.list_jobs(session, status=status, limit=limit, user_id=user_id)


@router.get("/{job_id}", response_model=Job | None)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    service: CompilerService = Depends(get_compiler_service),
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
):
    """Get job by ID."""
    return await service.get_job(job_id, session)


@router.post("/compile/{source_id}", response_model=JobTriggerResponse)
async def trigger_compile(
    source_id: str,
    service: CompilerService = Depends(get_compiler_service),
    user_id: str = Depends(get_current_user_id),
):
    """Trigger compilation for a source."""
    return await service.trigger_compile(source_id, user_id=user_id)


@router.post("/lint", response_model=JobTriggerResponse)
async def trigger_lint(
    service: LinterService = Depends(get_linter_service),
    user_id: str = Depends(get_current_user_id),
):
    """Trigger wiki linting.

    DEPRECATED: Use POST /lint/run instead. This endpoint delegates
    to the new LinterService for backward compatibility.
    """
    return await service.trigger_run(user_id=user_id)


@router.post("/reindex", response_model=JobTriggerResponse)
async def trigger_reindex(
    service: CompilerService = Depends(get_compiler_service),
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
):
    """Trigger wiki reindexing."""
    return await service.trigger_reindex()
