"""WebSocket endpoint for real-time event streaming to the UI.

Clients subscribe once and receive job progress, compilation results,
linter alerts, and sync status as they happen.

Connections are tracked per ``user_id`` so broadcasts reach only the
owning user. When ``user_id`` is ``None`` (single-user / legacy mode),
broadcasts go to all connections.
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from wikimind.config import get_settings

log = structlog.get_logger()

router = APIRouter()

# Sentinel key for connections with no user_id (single-user / legacy mode).
_NO_USER: str = "__no_user__"


# Global connection manager
class ConnectionManager:
    """Manage active WebSocket connections, scoped per user_id."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    @property
    def active(self) -> set[WebSocket]:
        """Return all active connections across every user (compat helper)."""
        result: set[WebSocket] = set()
        for conns in self._connections.values():
            result.update(conns)
        return result

    async def connect(self, ws: WebSocket, user_id: str | None = None) -> None:
        """Accept and register a WebSocket connection under *user_id*."""
        await ws.accept()
        key = user_id or _NO_USER
        self._connections.setdefault(key, set()).add(ws)
        log.info("WebSocket connected", user_id=user_id, total=len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection from all user buckets."""
        for key, conns in list(self._connections.items()):
            conns.discard(ws)
            if not conns:
                del self._connections[key]
        log.info("WebSocket disconnected", total=len(self.active))

    async def broadcast(self, event: dict, user_id: str | None = None) -> None:
        """Broadcast *event* to a specific user's connections.

        When *user_id* is ``None``, the event is sent to **all**
        connections (backward-compatible single-user behaviour).
        """
        targets = self.active if user_id is None else self._connections.get(user_id, set())

        if not targets:
            return

        message = json.dumps(event)
        dead: set[WebSocket] = set()
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, event: dict) -> None:
        """Send an event to a specific client."""
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            self.disconnect(ws)


manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Return the global connection manager."""
    return manager


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle WebSocket connections for real-time events.

    The optional ``user_id`` query parameter associates the connection
    with a specific user so broadcasts are scoped correctly.
    """
    user_id: str | None = websocket.query_params.get("user_id")
    await manager.connect(websocket, user_id=user_id)
    try:
        # Send initial connection ack
        await manager.send_to(websocket, {"event": "connected", "message": "WikiMind real-time stream active"})

        # Keep connection alive, handle pings
        while True:
            try:
                keepalive = get_settings().server.ws_keepalive_seconds
                data = await asyncio.wait_for(websocket.receive_text(), timeout=keepalive)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await manager.send_to(websocket, {"event": "pong"})
            except TimeoutError:
                # Send keepalive
                await manager.send_to(websocket, {"event": "keepalive"})
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Event emission helpers — called from job workers
# ---------------------------------------------------------------------------


async def emit_job_progress(job_id: str, pct: int, message: str = "", *, user_id: str | None = None) -> None:
    """Emit job progress event to the owning user's clients."""
    await manager.broadcast(
        {
            "event": "job.progress",
            "job_id": job_id,
            "pct": pct,
            "message": message,
        },
        user_id=user_id,
    )


async def emit_source_progress(source_id: str, message: str, *, user_id: str | None = None) -> None:
    """Broadcast a human-readable status message for a source.

    The message is the progress — e.g. ``"Compiling chunk 3/10..."``.
    No percentages, no phase enums, no weight math.

    Args:
        source_id: The source being processed.
        message: What the pipeline is doing right now.
        user_id: Scope broadcast to this user's connections.
    """
    await manager.broadcast(
        {
            "event": "source.progress",
            "source_id": source_id,
            "message": message,
        },
        user_id=user_id,
    )


async def emit_compilation_complete(article_slug: str, article_title: str, *, user_id: str | None = None) -> None:
    """Emit compilation complete event."""
    await manager.broadcast(
        {
            "event": "compilation.complete",
            "article_slug": article_slug,
            "article_title": article_title,
        },
        user_id=user_id,
    )


async def emit_compilation_failed(source_id: str, error: str, *, user_id: str | None = None) -> None:
    """Emit compilation failed event."""
    await manager.broadcast(
        {
            "event": "compilation.failed",
            "source_id": source_id,
            "error": error,
        },
        user_id=user_id,
    )


async def emit_sync_complete(pushed: int, pulled: int, *, user_id: str | None = None) -> None:
    """Emit sync complete event."""
    await manager.broadcast(
        {
            "event": "sync.complete",
            "pushed": pushed,
            "pulled": pulled,
        },
        user_id=user_id,
    )


async def emit_linter_alert(alert_type: str, articles: list, *, user_id: str | None = None) -> None:
    """Emit linter alert event."""
    await manager.broadcast(
        {
            "event": "linter.alert",
            "type": alert_type,
            "articles": articles,
        },
        user_id=user_id,
    )


async def emit_article_recompiled(
    article_id: str,
    page_type: str,
    status: str = "complete",
    *,
    user_id: str | None = None,
) -> None:
    """Emit article recompiled event."""
    await manager.broadcast(
        {
            "event": "article.recompiled",
            "article_id": article_id,
            "page_type": page_type,
            "status": status,
        },
        user_id=user_id,
    )


async def emit_budget_warning(spend_usd: float, budget_usd: float, pct: float, *, user_id: str | None = None) -> None:
    """Emitted once when monthly spend crosses the warning threshold."""
    await manager.broadcast(
        {
            "event": "budget.warning",
            "spend_usd": round(spend_usd, 4),
            "budget_usd": budget_usd,
            "pct": round(pct, 1),
        },
        user_id=user_id,
    )


async def emit_budget_exceeded(spend_usd: float, budget_usd: float, *, user_id: str | None = None) -> None:
    """Emitted once when monthly spend crosses 100% of budget."""
    await manager.broadcast(
        {
            "event": "budget.exceeded",
            "spend_usd": round(spend_usd, 4),
            "budget_usd": budget_usd,
        },
        user_id=user_id,
    )
