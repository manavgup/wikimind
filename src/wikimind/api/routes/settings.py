"""Endpoints for LLM provider configuration, API keys, and cost tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from wikimind._datetime import utcnow_naive
from wikimind.api.deps import ANONYMOUS_USER_ID, get_current_user_id
from wikimind.config import get_api_key, get_settings
from wikimind.database import get_session, get_session_factory
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import Article, CompletionRequest, CostLog, Provider, TaskType, UserPreference
from wikimind.services.api_keys import get_user_api_key

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.config import Settings

log = structlog.get_logger()

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""

    monthly_budget_usd: float | None = None
    default_provider: str | None = None
    fallback_enabled: bool | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_model: str | None = None
    openai_compatible_supports_json_response_format: bool | None = None
    openai_compatible_supports_stream_usage: bool | None = None
    openai_compatible_supports_reasoning_effort: bool | None = None
    openai_compatible_max_tokens_field: str | None = None
    openai_compatible_reasoning_format: str | None = None


class DefaultProviderRequest(BaseModel):
    """Request to set the default LLM provider."""

    provider: str


class ProviderDetail(BaseModel):
    """Provider status."""

    enabled: bool
    model: str
    configured: bool
    base_url: str | None = None


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


_OPENAI_COMPATIBLE_PREF_MAP = {
    "llm.openai_compatible.base_url": "base_url",
    "llm.openai_compatible.model": "model",
    "llm.openai_compatible.supports_json_response_format": "supports_json_response_format",
    "llm.openai_compatible.supports_stream_usage": "supports_stream_usage",
    "llm.openai_compatible.supports_reasoning_effort": "supports_reasoning_effort",
    "llm.openai_compatible.max_tokens_field": "max_tokens_field",
    "llm.openai_compatible.reasoning_format": "reasoning_format",
}
_OPENAI_COMPATIBLE_TOKEN_FIELDS = {"max_tokens", "max_completion_tokens"}
_OPENAI_COMPATIBLE_REASONING_FORMATS = {"none", "openai", "openrouter"}
_OPENAI_COMPATIBLE_RUNTIME_REQUEST_FIELDS = (
    "openai_compatible_base_url",
    "openai_compatible_model",
    "openai_compatible_supports_json_response_format",
    "openai_compatible_supports_stream_usage",
    "openai_compatible_supports_reasoning_effort",
    "openai_compatible_max_tokens_field",
    "openai_compatible_reasoning_format",
)


async def apply_runtime_llm_preferences() -> None:
    """Apply persisted LLM runtime preferences to the in-memory settings singleton."""
    settings = get_settings()
    async with get_session_factory()() as session:
        result = await session.execute(select(UserPreference))
        for pref in result.scalars().all():
            if pref.key == "llm.default_provider":
                settings.llm.default_provider = pref.value
            elif pref.key == "llm.monthly_budget_usd":
                settings.llm.monthly_budget_usd = float(pref.value)
            elif pref.key == "llm.fallback_enabled":
                settings.llm.fallback_enabled = pref.value.lower() == "true"
            elif pref.key in _OPENAI_COMPATIBLE_PREF_MAP:
                field_name = _OPENAI_COMPATIBLE_PREF_MAP[pref.key]
                current_value = getattr(settings.llm.openai_compatible, field_name)
                value = pref.value.lower() == "true" if isinstance(current_value, bool) else pref.value
                setattr(settings.llm.openai_compatible, field_name, value)

    cfg = settings.llm.openai_compatible
    cfg.enabled = bool((cfg.enabled or get_api_key(Provider.OPENAI_COMPATIBLE.value)) and cfg.base_url and cfg.model)


def _has_required_provider_config(provider: Provider) -> bool:
    """Return whether non-secret runtime config exists for a provider."""
    if provider != Provider.OPENAI_COMPATIBLE:
        return True
    cfg = get_settings().llm.openai_compatible
    return bool(cfg.base_url and cfg.model)


def _refresh_openai_compatible_enabled(settings: Settings) -> None:
    """Refresh derived enabled state after runtime config changes."""
    cfg = settings.llm.openai_compatible
    cfg.enabled = bool((cfg.enabled or get_api_key(Provider.OPENAI_COMPATIBLE.value)) and cfg.base_url and cfg.model)
    get_llm_router()._provider_cache.pop(Provider.OPENAI_COMPATIBLE, None)


def _has_openai_compatible_runtime_update(request: SettingsUpdateRequest) -> bool:
    """Return true when a request changes global OpenAI-compatible runtime config."""
    return any(getattr(request, field_name) is not None for field_name in _OPENAI_COMPATIBLE_RUNTIME_REQUEST_FIELDS)


# ---------------------------------------------------------------------------
# DB preference helpers
# ---------------------------------------------------------------------------


async def _get_preference(key: str) -> str | None:
    async with get_session_factory()() as session:
        pref = await session.get(UserPreference, key)
        return pref.value if pref else None


async def _set_preference(key: str, value: str, user_id: str = ANONYMOUS_USER_ID) -> None:
    async with get_session_factory()() as session:
        pref = await session.get(UserPreference, key)
        if pref:
            pref.value = value
            pref.updated_at = utcnow_naive()
        else:
            pref = UserPreference(key=key, value=value, user_id=user_id)
        session.add(pref)
        await session.commit()


async def _update_openai_compatible_base_url(request: SettingsUpdateRequest, settings: Settings) -> bool:
    """Persist the configured OpenAI-compatible base URL if present."""
    if request.openai_compatible_base_url is None:
        return False

    base_url = request.openai_compatible_base_url.strip().rstrip("/")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="OpenAI-compatible base URL must start with http:// or https://")

    await _set_preference("llm.openai_compatible.base_url", base_url)
    settings.llm.openai_compatible.base_url = base_url
    return True


async def _update_openai_compatible_model(request: SettingsUpdateRequest, settings: Settings) -> bool:
    """Persist the configured OpenAI-compatible model if present."""
    if request.openai_compatible_model is None:
        return False

    model = request.openai_compatible_model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="OpenAI-compatible model must not be empty")

    await _set_preference("llm.openai_compatible.model", model)
    settings.llm.openai_compatible.model = model
    return True


async def _update_openai_compatible_bools(request: SettingsUpdateRequest, settings: Settings) -> bool:
    """Persist OpenAI-compatible boolean capability flags."""
    updated = False
    cfg = settings.llm.openai_compatible
    bool_updates = {
        "supports_json_response_format": request.openai_compatible_supports_json_response_format,
        "supports_stream_usage": request.openai_compatible_supports_stream_usage,
        "supports_reasoning_effort": request.openai_compatible_supports_reasoning_effort,
    }
    for field_name, value in bool_updates.items():
        if value is None:
            continue
        await _set_preference(f"llm.openai_compatible.{field_name}", str(value).lower())
        setattr(cfg, field_name, value)
        updated = True
    return updated


async def _update_openai_compatible_max_tokens_field(request: SettingsUpdateRequest, settings: Settings) -> bool:
    """Persist the max-tokens field selection if present."""
    if request.openai_compatible_max_tokens_field is None:
        return False

    max_tokens_field = request.openai_compatible_max_tokens_field.strip()
    if max_tokens_field not in _OPENAI_COMPATIBLE_TOKEN_FIELDS:
        raise HTTPException(
            status_code=400,
            detail="OpenAI-compatible max token field must be max_tokens or max_completion_tokens",
        )

    await _set_preference("llm.openai_compatible.max_tokens_field", max_tokens_field)
    settings.llm.openai_compatible.max_tokens_field = max_tokens_field
    return True


async def _update_openai_compatible_reasoning_format(
    request: SettingsUpdateRequest,
    settings: Settings,
) -> bool:
    """Persist the reasoning payload style if present."""
    if request.openai_compatible_reasoning_format is None:
        return False

    reasoning_format = request.openai_compatible_reasoning_format.strip()
    if reasoning_format not in _OPENAI_COMPATIBLE_REASONING_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="OpenAI-compatible reasoning format must be none, openai, or openrouter",
        )

    await _set_preference("llm.openai_compatible.reasoning_format", reasoning_format)
    if reasoning_format == "none":
        settings.llm.openai_compatible.reasoning_format = "none"
    elif reasoning_format == "openai":
        settings.llm.openai_compatible.reasoning_format = "openai"
    else:
        settings.llm.openai_compatible.reasoning_format = "openrouter"
    return True


async def _update_openai_compatible_settings(request: SettingsUpdateRequest, settings: Settings) -> bool:
    """Persist runtime OpenAI-compatible settings and update the singleton."""
    updated = False

    if settings.auth.enabled and _has_openai_compatible_runtime_update(request):
        raise HTTPException(
            status_code=403,
            detail="OpenAI-compatible runtime settings are global and cannot be changed by users when auth is enabled",
        )

    updated = await _update_openai_compatible_base_url(request, settings) or updated
    updated = await _update_openai_compatible_model(request, settings) or updated
    updated = await _update_openai_compatible_bools(request, settings) or updated
    updated = await _update_openai_compatible_max_tokens_field(request, settings) or updated
    updated = await _update_openai_compatible_reasoning_format(request, settings) or updated

    return updated


@router.get("", response_model=AllSettingsResponse)
async def get_all_settings(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Return all application settings, with DB overrides applied."""
    settings = get_settings()

    # Apply DB overrides
    default_provider = await _get_preference("llm.default_provider") or settings.llm.default_provider
    budget_pref = await _get_preference("llm.monthly_budget_usd")
    monthly_budget = float(budget_pref) if budget_pref else settings.llm.monthly_budget_usd
    fallback_pref = await _get_preference("llm.fallback_enabled")
    fallback_enabled = (fallback_pref.lower() == "true") if fallback_pref else settings.llm.fallback_enabled

    # Check both env var/keyring keys and per-user BYOK database keys
    providers = {}
    for p in Provider:
        has_system_key = bool(get_api_key(p.value))
        has_user_key = bool(await get_user_api_key(session, user_id, p)) if not has_system_key else False
        config_enabled = getattr(settings.llm, p.value).enabled
        has_required_config = _has_required_provider_config(p)
        providers[p.value] = ProviderDetail(
            enabled=(config_enabled or has_user_key) and has_required_config,
            model=getattr(settings.llm, p.value).model,
            configured=has_system_key or has_user_key,
            base_url=getattr(settings.llm, p.value).base_url if p == Provider.OPENAI_COMPATIBLE else None,
        )

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
async def set_default_provider(
    request: DefaultProviderRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Set the default LLM provider. Persists to DB, survives restarts."""
    valid_providers = [p.value for p in Provider]
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {request.provider}",
        )

    settings = get_settings()
    provider_cfg = getattr(settings.llm, request.provider, None)
    has_user_key = bool(await get_user_api_key(session, user_id, Provider(request.provider)))
    if not provider_cfg or (not provider_cfg.enabled and not has_user_key):
        raise HTTPException(
            status_code=400,
            detail=f"Provider {request.provider} is not enabled",
        )
    if not _has_required_provider_config(Provider(request.provider)):
        raise HTTPException(
            status_code=400,
            detail=f"Provider {request.provider} is missing required configuration",
        )

    # Providers that need API keys
    no_key_providers = {Provider.OLLAMA.value, Provider.MOCK.value}
    if request.provider not in no_key_providers:
        has_system_key = bool(get_api_key(request.provider))
        if not has_system_key and not has_user_key:
            raise HTTPException(
                status_code=400,
                detail=f"Provider {request.provider} has no API key configured",
            )

    await _set_preference("llm.default_provider", request.provider)
    settings.llm.default_provider = request.provider
    return DefaultProviderResponse(provider=request.provider, status="ok")


@router.patch("", response_model=SettingsUpdateResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    user_id: str = Depends(get_current_user_id),  # noqa: ARG001
):
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

    if await _update_openai_compatible_settings(request, settings):
        _refresh_openai_compatible_enabled(settings)

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


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(
    provider: str,
    user_id: str = Depends(get_current_user_id),  # noqa: PT028
):
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
            max_tokens=32,
            task_type=TaskType.QA,
            preferred_provider=Provider(provider),
        )
        response = await router_instance.complete(request, user_id=user_id)
        return LLMTestResponse(
            provider=provider,
            status="ok",
            latency_ms=response.latency_ms,
        )
    except Exception as e:  # TODO: narrow once provider error hierarchy is unified
        log.warning("LLM connection test failed", provider=provider, error=str(e))
        return LLMTestResponse(
            provider=provider,
            status="error",
            error="Provider connection failed",
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


def _onboarding_key(base: str, user_id: str) -> str:
    """Namespace onboarding preference keys per user."""
    return f"{base}:{user_id}"


@router.get("/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Return onboarding wizard progress for the current user.

    If the user has never explicitly completed onboarding but already has
    articles in the wiki, treat onboarding as implicitly complete — they
    are clearly past the first-run stage.
    """
    completed_key = _onboarding_key("onboarding.completed", user_id)
    step_key = _onboarding_key("onboarding.step", user_id)

    completed_val = await _get_preference(completed_key)
    if completed_val == "true":
        step_val = await _get_preference(step_key)
        return OnboardingStatusResponse(completed=True, step=int(step_val) if step_val else 5)

    # Implicit completion: existing articles for THIS user mean they know the app.
    result = await session.execute(select(Article.id).where(Article.user_id == user_id).limit(1))
    if result.scalar_one_or_none() is not None:
        return OnboardingStatusResponse(completed=True, step=5)

    step_val = await _get_preference(step_key)
    return OnboardingStatusResponse(
        completed=False,
        step=int(step_val) if step_val else 0,
    )


@router.post("/onboarding-status", response_model=OnboardingStatusResponse)
async def complete_onboarding(
    user_id: str = Depends(get_current_user_id),
):
    """Mark onboarding as complete for the current user."""
    await _set_preference(_onboarding_key("onboarding.completed", user_id), "true")
    await _set_preference(_onboarding_key("onboarding.step", user_id), "5")
    return OnboardingStatusResponse(completed=True, step=5)
