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


# Phase weights for the unified source progress bar.  Each phase reports
# its own 0-100 local progress; the helper below maps it to the overall
# 0-100 scale.  Weights must sum to 1.0.
_PHASE_WEIGHTS: dict[str, tuple[float, float]] = {
    #              (start, width)
    "extraction": (0.0, 0.30),    # 0-30%
    "compilation": (0.30, 0.50),  # 30-80%
    "saving": (0.80, 0.15),       # 80-95%
    "done": (0.95, 0.05),         # 95-100%
}


async def emit_source_progress(
    source_id: str,
    phase: str,
    phase_pct: int,
    message: str = "",
) -> None:
    """Emit unified source-level progress to all clients.

    Each caller reports its own 0-100 local progress within its phase.
    This helper maps ``(phase, phase_pct)`` to the overall 0-100 scale
    using the weights defined in ``_PHASE_WEIGHTS``.

    Args:
        source_id: The source being processed.
        phase: Pipeline phase (extraction, compilation, saving, done).
        phase_pct: Progress within the phase (0-100).
        message: Human-readable status message.
    """
    start, width = _PHASE_WEIGHTS.get(phase, (0.0, 1.0))
    overall = int((start + width * (min(phase_pct, 100) / 100)) * 100)
    await manager.broadcast(
        {
            "event": "source.progress",
            "source_id": source_id,
            "pct": min(overall, 100),
            "phase": phase,
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
