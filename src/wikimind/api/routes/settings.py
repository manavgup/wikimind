"""Endpoints for LLM provider configuration, API keys, and cost tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from wikimind._datetime import utcnow_naive
from wikimind.api.deps import get_current_user_id
from wikimind.config import get_api_key, get_settings, set_api_key
from wikimind.database import get_session, get_session_factory
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import Article, CompletionRequest, CostLog, Provider, TaskType, UserPreference

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


class APIKeyRequest(BaseModel):
    """Request to set an API key."""

    provider: str
    api_key: str


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""

    monthly_budget_usd: float | None = None
    default_provider: str | None = None
    fallback_enabled: bool | None = None


class DefaultProviderRequest(BaseModel):
    """Request to set the default LLM provider."""

    provider: str


class ProviderDetail(BaseModel):
    """Provider status."""

    enabled: bool
    model: str
    configured: bool


class LLMSettingsResponse(BaseModel):
    """LLM configuration section."""

    default_provider: str
    fallback_enabled: bool
    monthly_budget_usd: float
    providers: dict[str, ProviderDetail]


class SyncSettingsResponse(BaseModel):
    """Cloud sync configuration section."""

    enabled: bool
    interval_minutes: int
    bucket: str | None


class AllSettingsResponse(BaseModel):
    """Full application settings response."""

    data_dir: str
    gateway_port: int
    llm: LLMSettingsResponse
    sync: SyncSettingsResponse


class SettingsUpdateResponse(BaseModel):
    """Response after updating settings."""

    status: str


class ProviderKeyResponse(BaseModel):
    """Response after setting a provider API key."""

    provider: str
    configured: bool


class DefaultProviderResponse(BaseModel):
    """Response after setting default provider."""

    provider: str
    status: str


class LLMTestResponse(BaseModel):
    """Response from LLM connection test."""

    provider: str
    status: str
    latency_ms: float | None = None
    error: str | None = None


class CostBreakdownEntry(BaseModel):
    """Cost and call count for a single category."""

    cost_usd: float
    call_count: int


class CostBreakdownResponse(BaseModel):
    """Full cost breakdown for current month."""

    month: str
    total_usd: float
    budget_usd: float
    budget_pct: float
    by_provider: dict[str, CostBreakdownEntry]
    by_task_type: dict[str, CostBreakdownEntry]


class CostSummaryResponse(BaseModel):
    """Simple cost summary for current month."""

    cost_this_month_usd: float
    budget_usd: float
    budget_remaining_usd: float


class OnboardingStatusResponse(BaseModel):
    """Onboarding wizard progress."""

    completed: bool
    step: int


class OnboardingCompleteRequest(BaseModel):
    """Request to mark onboarding as complete."""


# ---------------------------------------------------------------------------
# DB preference helpers
# ---------------------------------------------------------------------------


async def _get_preference(key: str) -> str | None:
    async with get_session_factory()() as session:
        pref = await session.get(UserPreference, key)
        return pref.value if pref else None


async def _set_preference(key: str, value: str) -> None:
    async with get_session_factory()() as session:
        pref = await session.get(UserPreference, key)
        if pref:
            pref.value = value
            pref.updated_at = utcnow_naive()
        else:
            pref = UserPreference(key=key, value=value)
        session.add(pref)
        await session.commit()


@router.get("", response_model=AllSettingsResponse)
async def get_all_settings():
    """Return all application settings, with DB overrides applied."""
    settings = get_settings()

    # Apply DB overrides
    default_provider = await _get_preference("llm.default_provider") or settings.llm.default_provider
    budget_pref = await _get_preference("llm.monthly_budget_usd")
    monthly_budget = float(budget_pref) if budget_pref else settings.llm.monthly_budget_usd
    fallback_pref = await _get_preference("llm.fallback_enabled")
    fallback_enabled = (fallback_pref.lower() == "true") if fallback_pref else settings.llm.fallback_enabled

    providers = {
        p.value: ProviderDetail(
            enabled=getattr(settings.llm, p.value).enabled,
            model=getattr(settings.llm, p.value).model,
            configured=bool(get_api_key(p.value)),
        )
        for p in Provider
    }

    return AllSettingsResponse(
        data_dir=settings.data_dir,
        gateway_port=settings.gateway_port,
        llm=LLMSettingsResponse(
            default_provider=default_provider,
            fallback_enabled=fallback_enabled,
            monthly_budget_usd=monthly_budget,
            providers=providers,
        ),
        sync=SyncSettingsResponse(
            enabled=settings.sync.enabled,
            interval_minutes=settings.sync.interval_minutes,
            bucket=settings.sync.bucket,
        ),
    )


@router.post(
    "/llm/default-provider",
    response_model=DefaultProviderResponse,
)
async def set_default_provider(request: DefaultProviderRequest):
    """Set the default LLM provider. Persists to DB, survives restarts."""
    valid_providers = [p.value for p in Provider]
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {request.provider}",
        )

    settings = get_settings()
    provider_cfg = getattr(settings.llm, request.provider, None)
    if not provider_cfg or not provider_cfg.enabled:
        raise HTTPException(
            status_code=400,
            detail=f"Provider {request.provider} is not enabled",
        )

    # Providers that need API keys
    no_key_providers = {Provider.OLLAMA.value, Provider.MOCK.value}
    if request.provider not in no_key_providers and not get_api_key(request.provider):
        raise HTTPException(
            status_code=400,
            detail=f"Provider {request.provider} has no API key configured",
        )

    await _set_preference("llm.default_provider", request.provider)
    settings.llm.default_provider = request.provider
    return DefaultProviderResponse(provider=request.provider, status="ok")


@router.patch("", response_model=SettingsUpdateResponse)
async def update_settings(request: SettingsUpdateRequest):
    """Update runtime settings. Changes persist to DB across restarts."""
    settings = get_settings()

    if request.monthly_budget_usd is not None:
        if request.monthly_budget_usd <= 0:
            raise HTTPException(status_code=400, detail="Budget must be positive")
        await _set_preference(
            "llm.monthly_budget_usd",
            str(request.monthly_budget_usd),
        )
        settings.llm.monthly_budget_usd = request.monthly_budget_usd

    if request.fallback_enabled is not None:
        await _set_preference(
            "llm.fallback_enabled",
            str(request.fallback_enabled).lower(),
        )
        settings.llm.fallback_enabled = request.fallback_enabled

    if request.default_provider is not None:
        valid_providers = [p.value for p in Provider]
        if request.default_provider not in valid_providers:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown provider: {request.default_provider}"),
            )
        await _set_preference("llm.default_provider", request.default_provider)
        settings.llm.default_provider = request.default_provider

    return SettingsUpdateResponse(status="ok")


@router.post("/llm/api-key", response_model=ProviderKeyResponse)
async def set_provider_api_key(request: APIKeyRequest):
    """Store API key in OS keychain."""
    valid_providers = [p.value for p in Provider]
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {request.provider}",
        )

    set_api_key(request.provider, request.api_key)
    return ProviderKeyResponse(provider=request.provider, configured=True)


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(provider: str):
    """Test if a provider is configured and reachable."""
    router_instance = get_llm_router()
    # Temporarily disable fallback so we only test the requested provider
    original_fallback = router_instance.settings.llm.fallback_enabled
    router_instance.settings.llm.fallback_enabled = False
    try:
        request = CompletionRequest(
            system="You are a test assistant.",
            messages=[
                {
                    "role": "user",
                    "content": ('Respond with the json object: {"status": "ok"}'),
                }
            ],
            max_tokens=10,
            task_type=TaskType.QA,
            preferred_provider=Provider(provider),
        )
        response = await router_instance.complete(request)
        return LLMTestResponse(
            provider=provider,
            status="ok",
            latency_ms=response.latency_ms,
        )
    except Exception as e:  # TODO: narrow once provider error hierarchy is unified
        return LLMTestResponse(
            provider=provider,
            status="error",
            error=str(e),
        )
    finally:
        router_instance.settings.llm.fallback_enabled = original_fallback


@router.get(
    "/llm/cost/breakdown",
    response_model=CostBreakdownResponse,
)
async def get_llm_cost_breakdown(
    user_id: str = Depends(get_current_user_id),
):
    """Cost breakdown by provider and task type for current month."""
    start_of_month = utcnow_naive().replace(day=1, hour=0, minute=0, second=0)
    settings = get_settings()

    async with get_session_factory()() as session:
        total_stmt = select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month)
        if user_id:
            total_stmt = total_stmt.where(CostLog.user_id == user_id)
        total_result = await session.execute(total_stmt)
        total = total_result.scalar() or 0.0

        provider_stmt = (
            select(
                CostLog.provider,
                func.sum(CostLog.cost_usd),
                func.count(),
            )
            .where(CostLog.created_at >= start_of_month)
            .group_by(CostLog.provider)
        )
        if user_id:
            provider_stmt = provider_stmt.where(CostLog.user_id == user_id)
        provider_result = await session.execute(provider_stmt)
        provider_rows = provider_result.all()

        task_stmt = (
            select(
                CostLog.task_type,
                func.sum(CostLog.cost_usd),
                func.count(),
            )
            .where(CostLog.created_at >= start_of_month)
            .group_by(CostLog.task_type)
        )
        if user_id:
            task_stmt = task_stmt.where(CostLog.user_id == user_id)
        task_result = await session.execute(task_stmt)
        task_rows = task_result.all()

    budget = settings.llm.monthly_budget_usd
    budget_pct = round(total / budget * 100, 1) if budget else 0.0
    month = utcnow_naive().strftime("%Y-%m")

    by_provider = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): CostBreakdownEntry(
            cost_usd=round(row[1] or 0.0, 4),
            call_count=row[2],
        )
        for row in provider_rows
    }
    by_task_type = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): CostBreakdownEntry(
            cost_usd=round(row[1] or 0.0, 4),
            call_count=row[2],
        )
        for row in task_rows
    }

    return CostBreakdownResponse(
        month=month,
        total_usd=round(total, 4),
        budget_usd=budget,
        budget_pct=budget_pct,
        by_provider=by_provider,
        by_task_type=by_task_type,
    )


@router.get("/llm/cost", response_model=CostSummaryResponse)
async def get_llm_cost(
    user_id: str = Depends(get_current_user_id),
):
    """Cost summary for current month."""
    start_of_month = utcnow_naive().replace(day=1, hour=0, minute=0, second=0)

    async with get_session_factory()() as session:
        cost_stmt = select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month)
        if user_id:
            cost_stmt = cost_stmt.where(CostLog.user_id == user_id)
        result = await session.execute(cost_stmt)
        total = result.scalar() or 0.0

    settings = get_settings()
    return CostSummaryResponse(
        cost_this_month_usd=round(total, 4),
        budget_usd=settings.llm.monthly_budget_usd,
        budget_remaining_usd=round(settings.llm.monthly_budget_usd - total, 4),
    )


# ---------------------------------------------------------------------------
# Onboarding status
# ---------------------------------------------------------------------------

_ONBOARDING_COMPLETED_KEY = "onboarding.completed"
_ONBOARDING_STEP_KEY = "onboarding.step"


@router.get("/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    session: AsyncSession = Depends(get_session),
):
    """Return onboarding wizard progress for the current user.

    If the user has never explicitly completed onboarding but already has
    articles in the wiki, treat onboarding as implicitly complete — they
    are clearly past the first-run stage.
    """
    completed_val = await _get_preference(_ONBOARDING_COMPLETED_KEY)
    if completed_val == "true":
        step_val = await _get_preference(_ONBOARDING_STEP_KEY)
        return OnboardingStatusResponse(completed=True, step=int(step_val) if step_val else 5)

    # Implicit completion: existing articles mean the user already knows the app.
    result = await session.execute(select(Article.id).limit(1))
    if result.scalar_one_or_none() is not None:
        return OnboardingStatusResponse(completed=True, step=5)

    step_val = await _get_preference(_ONBOARDING_STEP_KEY)
    return OnboardingStatusResponse(
        completed=False,
        step=int(step_val) if step_val else 0,
    )


@router.post("/onboarding-status", response_model=OnboardingStatusResponse)
async def complete_onboarding():
    """Mark onboarding as complete."""
    await _set_preference(_ONBOARDING_COMPLETED_KEY, "true")
    await _set_preference(_ONBOARDING_STEP_KEY, "5")
    return OnboardingStatusResponse(completed=True, step=5)
