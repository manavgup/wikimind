"""Plan-aware LLM routing — selects provider/model based on billing plan.

In self-hosted mode (``deployment_mode == "self_hosted"``), this is a
transparent pass-through. In hosted mode, the user's plan determines
which LLM provider and model are used. BYOK (bring-your-own-key) users
on Pro bypass plan restrictions and use their own key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wikimind.config import get_settings
from wikimind.models import CompletionRequest, CompletionResponse, Provider

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.engine.llm_router import LLMRouter


async def plan_aware_complete(
    router: LLMRouter,
    request: CompletionRequest,
    user_id: str,
    session: AsyncSession | None = None,
) -> CompletionResponse | None:
    """Wrap router.complete() with plan-based provider/model selection.

    In self-hosted mode or when no session is available, passes through
    directly to the router. In hosted mode, applies the plan's provider
    and model restrictions unless the user has a BYOK key.

    Args:
        router: The LLM router instance.
        request: The completion request to execute.
        user_id: User ID for BYOK key lookup and cost logging.
        session: Async database session for plan resolution. When ``None``,
            falls back to pass-through (self-hosted behaviour).

    Returns:
        :class:`CompletionResponse` on success, or ``None`` if the
        underlying call fails and the caller handles ``None`` returns.
    """
    settings = get_settings()
    if not settings.billing_enabled or session is None:
        return await router.complete(request, user_id=user_id)

    from wikimind.services.quota import get_effective_plan  # noqa: PLC0415

    try:
        plan = await get_effective_plan(session, user_id)
    except Exception:
        # No plan table (e.g. test environment without billing migration).
        # Fall back to pass-through.
        return await router.complete(request, user_id=user_id)

    # BYOK override: if the user has their own key for any provider,
    # let them use it with full fallback (Pro plan required for BYOK)
    if plan.byok_allowed:
        has_key = await router.has_user_key(Provider(plan.llm_provider), user_id)
        if has_key:
            return await router.complete(request, user_id=user_id)

    # Apply plan restrictions
    request.preferred_provider = Provider(plan.llm_provider)
    request.model_override = plan.llm_model
    request.disable_fallback = True

    return await router.complete(request, user_id=user_id)
