"""WebSocket endpoint for real-time event streaming to the UI.

Clients subscribe once and receive job progress, compilation results,
linter alerts, and sync status as they happen.

Connections are tracked per ``user_id`` so broadcasts reach only the
owning user.

Multi-replica support
---------------------
When ``Settings.redis_url`` is set, broadcasts are published to a Redis
Pub/Sub channel so that every gateway replica receives the event and
forwards it to its local WebSocket connections. Without Redis the manager
falls back to local-only delivery (single-replica dev mode).
"""

import asyncio
import contextlib
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

try:
    from redis.exceptions import RedisError
except ImportError:  # redis package not installed
    RedisError = OSError  # type: ignore[assignment,misc]

from wikimind.api.deps import get_ws_user_id
from wikimind.config import get_settings

log = structlog.get_logger()

router = APIRouter()

# Sentinel key for connections with no user_id (single-user / legacy mode).
_NO_USER: str = "__no_user__"

# Redis Pub/Sub channel name for cross-replica WebSocket broadcasts.
_REDIS_WS_CHANNEL: str = "wikimind:ws:broadcast"


# ---------------------------------------------------------------------------
# Redis Pub/Sub helpers
# ---------------------------------------------------------------------------

_redis_publish_pool = None
_subscriber_task: asyncio.Task | None = None


async def _get_redis():
    """Return a shared ``redis.asyncio.Redis`` connection for publishing.

    Lazily created on first call. Returns ``None`` when Redis is not
    configured or the ``redis`` package is unavailable.
    """
    global _redis_publish_pool
    if _redis_publish_pool is not None:
        return _redis_publish_pool

    redis_url = get_settings().redis_url
    if not redis_url:
        return None

    try:
        _redis_publish_pool = Redis.from_url(redis_url, decode_responses=True)
        return _redis_publish_pool
    except (RedisError, OSError):
        log.debug("Redis unavailable for WebSocket pub/sub — local-only mode")
        return None


async def _publish_to_redis(event: dict, user_id: str) -> bool:
    """Publish a broadcast payload to the Redis Pub/Sub channel.

    Returns ``True`` if the message was published, ``False`` otherwise
    (no Redis, connection error, etc.).
    """
    redis = await _get_redis()
    if redis is None:
        return False

    payload = json.dumps({"event": event, "user_id": user_id})
    try:
        await redis.publish(_REDIS_WS_CHANNEL, payload)
        return True
    except (RedisError, OSError):
        log.warning("Failed to publish WebSocket event to Redis", exc_info=True)
        return False


async def _start_redis_subscriber() -> None:
    """Start a background task that subscribes to the Redis Pub/Sub channel.

    Received messages are forwarded to local WebSocket connections via
    ``manager._local_broadcast()``. Safe to call multiple times — only
    one subscriber is started per process.
    """
    global _subscriber_task
    if _subscriber_task is not None:
        return

    redis_url = get_settings().redis_url
    if not redis_url:
        return

    try:
        subscriber_redis = Redis.from_url(redis_url, decode_responses=True)
    except (RedisError, OSError):
        log.debug("Redis unavailable — skipping WebSocket subscriber")
        return

    async def _listen() -> None:
        """Subscribe to the Redis channel and relay events to local clients."""
        pubsub = subscriber_redis.pubsub()
        try:
            await pubsub.subscribe(_REDIS_WS_CHANNEL)
            log.info("WebSocket Redis subscriber started", channel=_REDIS_WS_CHANNEL)
            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue
                try:
                    payload = json.loads(raw_message["data"])
                    event = payload["event"]
                    uid = payload["user_id"]
                    await manager._local_broadcast(event, user_id=uid)
                except (json.JSONDecodeError, KeyError, TypeError):
                    log.debug("Ignoring malformed Redis WS message")
        except asyncio.CancelledError:
            await pubsub.unsubscribe(_REDIS_WS_CHANNEL)
            await subscriber_redis.aclose()
        except (RedisError, OSError):
            log.warning("Redis WebSocket subscriber error", exc_info=True)

    _subscriber_task = asyncio.create_task(_listen())


async def stop_redis_subscriber() -> None:
    """Cancel the Redis subscriber task (called on shutdown)."""
    global _subscriber_task, _redis_publish_pool
    if _subscriber_task is not None:
        _subscriber_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _subscriber_task
        _subscriber_task = None
    if _redis_publish_pool is not None:
        await _redis_publish_pool.aclose()
        _redis_publish_pool = None


# Global connection manager
class ConnectionManager:
    """Manage active WebSocket connections, scoped per user_id.

    In multi-replica mode (Redis available), ``broadcast()`` publishes to
    a Redis Pub/Sub channel. A background subscriber task on each replica
    receives the message and calls ``_local_broadcast()`` to deliver it to
    that replica's local WebSocket connections.

    In single-replica mode (no Redis), ``broadcast()`` calls
    ``_local_broadcast()`` directly.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    @property
    def active(self) -> set[WebSocket]:
        """Return all active connections across every user (compat helper)."""
        result: set[WebSocket] = set()
        for conns in self._connections.values():
            result.update(conns)
        return result

    async def connect(self, ws: WebSocket, user_id: str) -> None:
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

    async def broadcast(self, event: dict, user_id: str) -> None:
        """Broadcast *event* to a specific user's connections across all replicas.

        When Redis is available, the event is published to a Pub/Sub channel
        and the subscriber task on each replica delivers it locally. When
        Redis is unavailable, falls back to local-only delivery.
        """
        published = await _publish_to_redis(event, user_id)
        if not published:
            # No Redis — deliver locally (single-replica mode).
            await self._local_broadcast(event, user_id=user_id)

    async def _local_broadcast(self, event: dict, user_id: str) -> None:
        """Deliver *event* to this replica's local WebSocket connections only.

        Called directly in single-replica mode, or by the Redis subscriber
        in multi-replica mode. Never call this from application code — use
        :meth:`broadcast` instead.
        """
        targets = self._connections.get(user_id, set())

        if not targets:
            return

        message = json.dumps(event)
        dead: set[WebSocket] = set()
        for ws in targets:
            try:
                await ws.send_text(message)
            except (WebSocketDisconnect, RuntimeError, ConnectionError, OSError):
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, event: dict) -> None:
        """Send an event to a specific client."""
        try:
            await ws.send_text(json.dumps(event))
        except (WebSocketDisconnect, RuntimeError, ConnectionError, OSError):
            self.disconnect(ws)


manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Return the global connection manager."""
    return manager


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle WebSocket connections for real-time events.

    The user is identified from the JWT session cookie (or a ``token``
    query parameter) so broadcasts are scoped to the authenticated user.
    """
    # Ensure the Redis subscriber is running (idempotent).
    await _start_redis_subscriber()

    user_id = await get_ws_user_id(websocket)
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


async def emit_job_progress(job_id: str, pct: int, message: str = "", *, user_id: str) -> None:
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


async def emit_source_progress(source_id: str, message: str, *, user_id: str) -> None:
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


async def emit_compilation_complete(article_slug: str, article_title: str, *, user_id: str) -> None:
    """Emit compilation complete event."""
    await manager.broadcast(
        {
            "event": "compilation.complete",
            "article_slug": article_slug,
            "article_title": article_title,
        },
        user_id=user_id,
    )


async def emit_compilation_failed(source_id: str, error: str, *, user_id: str) -> None:
    """Emit compilation failed event."""
    await manager.broadcast(
        {
            "event": "compilation.failed",
            "source_id": source_id,
            "error": error,
        },
        user_id=user_id,
    )


async def emit_sync_complete(pushed: int, pulled: int, *, user_id: str) -> None:
    """Emit sync complete event."""
    await manager.broadcast(
        {
            "event": "sync.complete",
            "pushed": pushed,
            "pulled": pulled,
        },
        user_id=user_id,
    )


async def emit_linter_alert(alert_type: str, articles: list, *, user_id: str) -> None:
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
    user_id: str,
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


async def emit_budget_warning(spend_usd: float, budget_usd: float, pct: float, *, user_id: str) -> None:
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


async def emit_budget_exceeded(spend_usd: float, budget_usd: float, *, user_id: str) -> None:
    """Emitted once when monthly spend crosses 100% of budget."""
    await manager.broadcast(
        {
            "event": "budget.exceeded",
            "spend_usd": round(spend_usd, 4),
            "budget_usd": budget_usd,
        },
        user_id=user_id,
    )


async def emit_draft_ready(
    source_id: str,
    draft_id: str,
    title: str,
    *,
    user_id: str,
) -> None:
    """Emitted when a compilation draft is ready for user review."""
    await manager.broadcast(
        {
            "event": "draft.ready",
            "source_id": source_id,
            "draft_id": draft_id,
            "title": title,
        },
        user_id=user_id,
    )
