"""WebSocket endpoint for real-time event streaming to the UI.

Clients subscribe once and receive job progress, compilation results,
linter alerts, and sync status as they happen.
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger()

router = APIRouter()


# Global connection manager
class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        """Accept and register a WebSocket connection."""
        await ws.accept()
        self.active.add(ws)
        log.info("WebSocket connected", total=len(self.active))

    def disconnect(self, ws: WebSocket):
        """Remove a WebSocket connection."""
        self.active.discard(ws)
        log.info("WebSocket disconnected", total=len(self.active))

    async def broadcast(self, event: dict):
        """Broadcast event to all connected clients."""
        if not self.active:
            return
        message = json.dumps(event)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.active -= dead

    async def send_to(self, ws: WebSocket, event: dict):
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
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections for real-time events."""
    await manager.connect(websocket)
    try:
        # Send initial connection ack
        await manager.send_to(websocket, {"event": "connected", "message": "WikiMind real-time stream active"})

        # Keep connection alive, handle pings
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
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


async def emit_job_progress(job_id: str, pct: int, message: str = ""):
    """Emit job progress event to all clients."""
    await manager.broadcast(
        {
            "event": "job.progress",
            "job_id": job_id,
            "pct": pct,
            "message": message,
        }
    )


async def emit_source_progress(source_id: str, message: str) -> None:
    """Broadcast a human-readable status message for a source.

    The message is the progress — e.g. ``"Compiling chunk 3/10..."``.
    No percentages, no phase enums, no weight math.

    Args:
        source_id: The source being processed.
        message: What the pipeline is doing right now.
    """
    await manager.broadcast(
        {
            "event": "source.progress",
            "source_id": source_id,
            "message": message,
        }
    )


async def emit_compilation_complete(article_slug: str, article_title: str):
    """Emit compilation complete event."""
    await manager.broadcast(
        {
            "event": "compilation.complete",
            "article_slug": article_slug,
            "article_title": article_title,
        }
    )


async def emit_compilation_failed(source_id: str, error: str):
    """Emit compilation failed event."""
    await manager.broadcast(
        {
            "event": "compilation.failed",
            "source_id": source_id,
            "error": error,
        }
    )


async def emit_sync_complete(pushed: int, pulled: int):
    """Emit sync complete event."""
    await manager.broadcast(
        {
            "event": "sync.complete",
            "pushed": pushed,
            "pulled": pulled,
        }
    )


async def emit_linter_alert(alert_type: str, articles: list):
    """Emit linter alert event."""
    await manager.broadcast(
        {
            "event": "linter.alert",
            "type": alert_type,
            "articles": articles,
        }
    )


async def emit_article_recompiled(article_id: str, page_type: str, status: str = "complete"):
    """Emit article recompiled event."""
    await manager.broadcast(
        {
            "event": "article.recompiled",
            "article_id": article_id,
            "page_type": page_type,
            "status": status,
        }
    )


async def emit_budget_warning(spend_usd: float, budget_usd: float, pct: float):
    """Emitted once when monthly spend crosses the warning threshold."""
    await manager.broadcast(
        {
            "event": "budget.warning",
            "spend_usd": round(spend_usd, 4),
            "budget_usd": budget_usd,
            "pct": round(pct, 1),
        }
    )


async def emit_budget_exceeded(spend_usd: float, budget_usd: float):
    """Emitted once when monthly spend crosses 100% of budget."""
    await manager.broadcast(
        {
            "event": "budget.exceeded",
            "spend_usd": round(spend_usd, 4),
            "budget_usd": budget_usd,
        }
    )
