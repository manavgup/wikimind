"""Endpoints for LLM provider configuration, API keys, and cost tracking."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_api_key, get_settings, set_api_key
from wikimind.database import get_session_factory
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import CompletionRequest, CostLog, Provider, TaskType, UserPreference

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


@router.get("")
async def get_all_settings():
    """Return all application settings, with DB overrides applied."""
    settings = get_settings()

    # Apply DB overrides
    default_provider = await _get_preference("llm.default_provider") or settings.llm.default_provider
    budget_pref = await _get_preference("llm.monthly_budget_usd")
    monthly_budget = float(budget_pref) if budget_pref else settings.llm.monthly_budget_usd
    fallback_pref = await _get_preference("llm.fallback_enabled")
    fallback_enabled = (fallback_pref.lower() == "true") if fallback_pref else settings.llm.fallback_enabled

    return {
        "data_dir": settings.data_dir,
        "gateway_port": settings.gateway_port,
        "llm": {
            "default_provider": default_provider,
            "fallback_enabled": fallback_enabled,
            "monthly_budget_usd": monthly_budget,
            "providers": {
                p.value: {
                    "enabled": getattr(settings.llm, p.value).enabled,
                    "model": getattr(settings.llm, p.value).model,
                    "configured": bool(get_api_key(p.value)),
                }
                for p in Provider
            },
        },
        "sync": {
            "enabled": settings.sync.enabled,
            "interval_minutes": settings.sync.interval_minutes,
            "bucket": settings.sync.bucket,
        },
    }


@router.post("/llm/default-provider")
async def set_default_provider(request: DefaultProviderRequest):
    """Set the default LLM provider. Persists to DB, survives restarts."""
    valid_providers = [p.value for p in Provider]
    if request.provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {request.provider}")

    settings = get_settings()
    provider_cfg = getattr(settings.llm, request.provider, None)
    if not provider_cfg or not provider_cfg.enabled:
        raise HTTPException(status_code=400, detail=f"Provider {request.provider} is not enabled")

    # Providers that need API keys
    if request.provider not in ("ollama", "mock") and not get_api_key(request.provider):
        raise HTTPException(status_code=400, detail=f"Provider {request.provider} has no API key configured")

    await _set_preference("llm.default_provider", request.provider)
    settings.llm.default_provider = request.provider
    return {"provider": request.provider, "status": "ok"}


@router.patch("")
async def update_settings(request: SettingsUpdateRequest):
    """Update runtime settings. Changes persist to DB across restarts."""
    settings = get_settings()

    if request.monthly_budget_usd is not None:
        if request.monthly_budget_usd <= 0:
            raise HTTPException(status_code=400, detail="Budget must be positive")
        await _set_preference("llm.monthly_budget_usd", str(request.monthly_budget_usd))
        settings.llm.monthly_budget_usd = request.monthly_budget_usd

    if request.fallback_enabled is not None:
        await _set_preference("llm.fallback_enabled", str(request.fallback_enabled).lower())
        settings.llm.fallback_enabled = request.fallback_enabled

    if request.default_provider is not None:
        valid_providers = [p.value for p in Provider]
        if request.default_provider not in valid_providers:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {request.default_provider}")
        await _set_preference("llm.default_provider", request.default_provider)
        settings.llm.default_provider = request.default_provider

    return {"status": "ok"}


@router.post("/llm/api-key")
async def set_provider_api_key(request: APIKeyRequest):
    """Store API key in OS keychain."""
    valid_providers = [p.value for p in Provider]
    if request.provider not in valid_providers:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {request.provider}")

    set_api_key(request.provider, request.api_key)
    return {"provider": request.provider, "configured": True}


@router.post("/llm/test")
async def test_llm_connection(provider: str):
    """Test if a provider is configured and reachable."""
    router_instance = get_llm_router()
    # Temporarily disable fallback so we only test the requested provider
    original_fallback = router_instance.settings.llm.fallback_enabled
    router_instance.settings.llm.fallback_enabled = False
    try:
        request = CompletionRequest(
            system="You are a test assistant.",
            messages=[{"role": "user", "content": 'Respond with the json object: {"status": "ok"}'}],
            max_tokens=10,
            task_type=TaskType.QA,
            preferred_provider=Provider(provider),
        )
        response = await router_instance.complete(request)
        return {"provider": provider, "status": "ok", "latency_ms": response.latency_ms}
    except Exception as e:
        return {"provider": provider, "status": "error", "error": str(e)}
    finally:
        router_instance.settings.llm.fallback_enabled = original_fallback


@router.get("/llm/cost/breakdown")
async def get_llm_cost_breakdown():
    """Cost breakdown by provider and task type for current month."""
    start_of_month = utcnow_naive().replace(day=1, hour=0, minute=0, second=0)
    settings = get_settings()

    async with get_session_factory()() as session:
        total_result = await session.execute(
            select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month)
        )
        total = total_result.scalar() or 0.0

        provider_result = await session.execute(
            select(CostLog.provider, func.sum(CostLog.cost_usd), func.count())
            .where(CostLog.created_at >= start_of_month)
            .group_by(CostLog.provider)
        )
        provider_rows = provider_result.all()

        task_result = await session.execute(
            select(CostLog.task_type, func.sum(CostLog.cost_usd), func.count())
            .where(CostLog.created_at >= start_of_month)
            .group_by(CostLog.task_type)
        )
        task_rows = task_result.all()

    budget = settings.llm.monthly_budget_usd
    budget_pct = round(total / budget * 100, 1) if budget else 0.0
    month = utcnow_naive().strftime("%Y-%m")

    by_provider = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): {
            "cost_usd": round(row[1] or 0.0, 4),
            "call_count": row[2],
        }
        for row in provider_rows
    }
    by_task_type = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): {
            "cost_usd": round(row[1] or 0.0, 4),
            "call_count": row[2],
        }
        for row in task_rows
    }

    return {
        "month": month,
        "total_usd": round(total, 4),
        "budget_usd": budget,
        "budget_pct": budget_pct,
        "by_provider": by_provider,
        "by_task_type": by_task_type,
    }


@router.get("/llm/cost")
async def get_llm_cost():
    """Cost summary for current month."""
    start_of_month = utcnow_naive().replace(day=1, hour=0, minute=0, second=0)

    async with get_session_factory()() as session:
        result = await session.execute(select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month))
        total = result.scalar() or 0.0

    settings = get_settings()
    return {
        "cost_this_month_usd": round(total, 4),
        "budget_usd": settings.llm.monthly_budget_usd,
        "budget_remaining_usd": round(settings.llm.monthly_budget_usd - total, 4),
    }
