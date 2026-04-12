"""Endpoints for managing async compilation and linting jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.services.compiler import CompilerService, get_compiler_service
from wikimind.services.linter import LinterService, get_linter_service

router = APIRouter()


@router.get("")
async def list_jobs(
    status: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    service: CompilerService = Depends(get_compiler_service),
):
    """List jobs with optional status filter."""
    return await service.list_jobs(session, status=status, limit=limit)


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    service: CompilerService = Depends(get_compiler_service),
):
    """Get job by ID."""
    return await service.get_job(job_id, session)


@router.post("/compile/{source_id}")
async def trigger_compile(
    source_id: str,
    service: CompilerService = Depends(get_compiler_service),
):
    """Trigger compilation for a source."""
    return await service.trigger_compile(source_id)


@router.post("/lint")
async def trigger_lint(
    service: LinterService = Depends(get_linter_service),
):
    """Trigger wiki linting.

    DEPRECATED: Use POST /lint/run instead. This endpoint delegates
    to the new LinterService for backward compatibility.
    """
    return await service.trigger_run()


@router.post("/reindex")
async def trigger_reindex(
    service: CompilerService = Depends(get_compiler_service),
):
    """Trigger wiki reindexing."""
    return await service.trigger_reindex()
