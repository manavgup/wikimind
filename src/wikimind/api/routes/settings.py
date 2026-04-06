"""Endpoints for LLM provider configuration, API keys, and cost tracking."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import func, select

from wikimind.config import get_api_key, get_settings, set_api_key
from wikimind.database import get_session_factory
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import CompletionRequest, CostLog, Provider, TaskType

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


@router.get("")
async def get_all_settings():
    """Return all application settings."""
    settings = get_settings()
    return {
        "data_dir": settings.data_dir,
        "gateway_port": settings.gateway_port,
        "llm": {
            "default_provider": settings.llm.default_provider,
            "fallback_enabled": settings.llm.fallback_enabled,
            "monthly_budget_usd": settings.llm.monthly_budget_usd,
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
        },
    }


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
    try:
        request = CompletionRequest(
            system="You are a test assistant.",
            messages=[{"role": "user", "content": "Say 'ok' in one word."}],
            max_tokens=10,
            task_type=TaskType.QA,
            preferred_provider=Provider(provider),
        )
        response = await router_instance.complete(request)
        return {"provider": provider, "status": "ok", "latency_ms": response.latency_ms}
    except Exception as e:
        return {"provider": provider, "status": "error", "error": str(e)}


@router.get("/llm/cost")
async def get_llm_cost():
    """Cost summary for current month."""
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)

    async with get_session_factory()() as session:
        result = await session.execute(select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month))
        total = result.scalar() or 0.0

    settings = get_settings()
    return {
        "cost_this_month_usd": round(total, 4),
        "budget_usd": settings.llm.monthly_budget_usd,
        "budget_remaining_usd": round(settings.llm.monthly_budget_usd - total, 4),
    }
