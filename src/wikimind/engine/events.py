"""Event emitter protocol for the engine layer.

Defines the interface that the engine uses to emit budget alerts
without coupling to a specific transport (WebSocket, logging, etc.).
"""

from __future__ import annotations

from typing import Protocol


class BudgetEventEmitter(Protocol):
    """Protocol for emitting budget threshold notifications.

    Implementations live in the API or transport layer; the engine
    depends only on this interface.
    """

    async def emit_budget_warning(
        self,
        spend_usd: float,
        budget_usd: float,
        pct: float,
        *,
        user_id: str,
    ) -> None:
        """Emitted once when monthly spend crosses the warning threshold."""
        ...  # type: ignore[empty-body]

    async def emit_budget_exceeded(
        self,
        spend_usd: float,
        budget_usd: float,
        *,
        user_id: str,
    ) -> None:
        """Emitted once when monthly spend crosses 100% of budget."""
        ...  # type: ignore[empty-body]


class NullBudgetEventEmitter:
    """No-op emitter used when no concrete implementation is injected."""

    async def emit_budget_warning(
        self,
        spend_usd: float,
        budget_usd: float,
        pct: float,
        *,
        user_id: str,
    ) -> None:
        """No-op."""

    async def emit_budget_exceeded(
        self,
        spend_usd: float,
        budget_usd: float,
        *,
        user_id: str,
    ) -> None:
        """No-op."""
