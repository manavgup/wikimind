"""FastAPI application entry point and lifespan management.

Runs as a local daemon on localhost:7842. Initializes the database,
registers all routers, and configures CORS for Electron and web dev servers.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select
from starlette.responses import FileResponse, HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from wikimind.api.routes import admin, api_keys, auth, export, ingest, jobs, lint, query, wiki, ws
from wikimind.api.routes import settings as settings_router
from wikimind.api.routes.settings import apply_runtime_llm_preferences
from wikimind.api.routes.ws import _start_redis_subscriber, stop_redis_subscriber
from wikimind.config import get_settings
from wikimind.database import close_db, get_session_factory, init_db
from wikimind.errors import WikiMindError
from wikimind.middleware.auth import AuthMiddleware
from wikimind.middleware.correlation import CorrelationIdMiddleware
from wikimind.middleware.error_handling import ErrorHandlingMiddleware
from wikimind.middleware.logging_config import configure_logging
from wikimind.middleware.request_logging import RequestLoggingMiddleware
from wikimind.middleware.security_headers import SecurityHeadersMiddleware
from wikimind.models import Article, IngestStatus, Source

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# SPA fallback middleware — intercepts browser navigations that would
# otherwise hit API routes sharing the same path (e.g. /settings, /health).
# ---------------------------------------------------------------------------
# Paths/prefixes that should always be handled by FastAPI, never the SPA.
_API_ONLY_PREFIXES = (
    "/api/",
    "/assets/",
    "/images/",
    "/auth/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/ws",
)


class SPAFallbackMiddleware:
    """Serve index.html for browser navigations to SPA routes.

    When the frontend static build is present, browser requests (Accept:
    text/html) to paths that are *not* API-only are answered with
    index.html before FastAPI routing runs.  This prevents API route
    handlers mounted at top-level paths (e.g. /settings, /health) from
    returning JSON when the user refreshes a browser page.

    Programmatic API calls (Accept: application/json) are always passed
    through to FastAPI unchanged.
    """

    def __init__(self, app: ASGIApp, *, static_dir: Path) -> None:
        self._app = app
        self._index_bytes = (static_dir / "index.html").read_bytes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Intercept browser navigations and serve index.html for SPA routes."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        headers = dict(scope.get("headers", []))
        accept = (headers.get(b"accept", b"") or b"").decode("latin-1")

        is_html_request = "text/html" in accept and "application/json" not in accept
        is_api_path = any(path.startswith(p) for p in _API_ONLY_PREFIXES)

        if is_html_request and not is_api_path:
            response = HTMLResponse(self._index_bytes)
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown lifecycle."""
    configure_logging()

    settings = get_settings()
    settings.ensure_dirs()

    # Verify write permissions to data directories (fail fast before DB init)
    if settings.storage_backend == "local":
        for subdir in ("wiki", "raw"):
            test_dir = Path(settings.data_dir) / subdir
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / ".write-test"
            try:
                test_file.write_text("ok")
                test_file.unlink()
            except PermissionError:
                log.critical("No write permission", path=str(test_dir))
                raise SystemExit(1) from None

    log.info("WikiMind gateway starting", port=settings.gateway_port)
    await init_db()
    await apply_runtime_llm_preferences()
    log.info("Database initialized")

    # Reset sources stuck in PROCESSING from a prior crash/restart.
    # If the server is starting, no worker is mid-compilation, so any
    # source still in PROCESSING was interrupted.
    async with get_session_factory()() as session:
        result = await session.execute(select(Source).where(Source.status == IngestStatus.PROCESSING))
        stuck = list(result.scalars().all())
        for source in stuck:
            source.status = IngestStatus.FAILED
            source.error_message = "Compilation interrupted — retry when ready"
            session.add(source)
        if stuck:
            await session.commit()
            log.info("Reset stuck processing sources", count=len(stuck))

    # Backfill article.user_id from linked source for articles created
    # before user_id propagation was fixed. One-time migration that
    # becomes a no-op once all articles have a user_id set.
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Article).where(Article.user_id.is_(None))  # type: ignore[union-attr]
        )
        orphan_articles = list(result.scalars().all())
        backfilled = 0
        for article in orphan_articles:
            source_ids = json.loads(article.source_ids) if article.source_ids else []
            if not source_ids:
                continue
            source = await session.get(Source, source_ids[0])
            if source and source.user_id:
                article.user_id = source.user_id
                session.add(article)
                backfilled += 1
        if backfilled:
            await session.commit()
            log.info("Backfilled article user_id from source", count=backfilled)

    # Start Redis Pub/Sub subscriber for cross-replica WebSocket broadcasts.
    # Idempotent — no-op when Redis is not configured (single-replica dev mode).
    await _start_redis_subscriber()

    yield

    log.info("WikiMind gateway shutting down")
    await stop_redis_subscriber()
    await close_db()


app = FastAPI(
    title="WikiMind Gateway",
    description="Local LLM Knowledge OS — Personal API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Wiki", "description": "Browse wiki articles, knowledge graph, and search"},
        {"name": "Ingest", "description": "Ingest sources (URLs, PDFs, text, YouTube)"},
        {"name": "Query", "description": "Ask questions against the wiki"},
        {"name": "Jobs", "description": "Manage async compilation and linting jobs"},
        {"name": "Lint", "description": "Wiki health audit reports and findings"},
        {"name": "Settings", "description": "LLM provider configuration and cost tracking"},
        {"name": "Admin", "description": "System diagnostics and maintenance"},
        {"name": "Auth", "description": "OAuth2 authentication"},
        {"name": "Export", "description": "Export wiki articles as PDF, LinkedIn, or slides"},
        {"name": "WebSocket", "description": "Real-time progress streams"},
    ],
)

# ---------------------------------------------------------------------------
# Middleware stack — evaluated bottom-to-top.
# Request flow: Correlation → Logging → Auth → SecurityHeaders → ErrorHandling → CORS → routes
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Trust X-Forwarded-Proto from reverse proxies (Fly.io, nginx) so that
# request.url_for() generates https:// URLs for OAuth redirect URIs.
# trusted_hosts=["*"] is acceptable because Fly.io's edge proxy strips/overrides
# X-Forwarded-* headers before forwarding to the app.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Allow Electron renderer, web dev server, and browser extensions to connect
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^http://localhost:\d+$"  # Dev servers (React, Vite, etc.)
        r"|^app://\.$"  # Electron renderer
        r"|^chrome-extension://.*$"  # Chrome browser extension
        r"|^moz-extension://.*$"  # Firefox browser extension
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve extracted PDF images (issue #142)
_images_dir = Path(get_settings().data_dir) / "images"
_images_dir.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")

# Mount routers
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(wiki.router, prefix="/wiki", tags=["Wiki"])
app.include_router(query.router, prefix="/query", tags=["Query"])
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
app.include_router(lint.router, prefix="/lint", tags=["Lint"])
app.include_router(settings_router.router, prefix="/settings", tags=["Settings"])
app.include_router(api_keys.router, prefix="/api/settings/api-keys", tags=["Settings"])
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(export.router, prefix="/wiki", tags=["Export"])

# ---------------------------------------------------------------------------
# Exception handlers — catch domain errors raised inside route handlers
# ---------------------------------------------------------------------------


@app.exception_handler(WikiMindError)
async def wikimind_error_handler(request: Request, exc: WikiMindError) -> JSONResponse:
    """Map WikiMindError subclasses to the standard JSON error envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


@app.get("/health")
async def health():
    """Health check — used by Electron to confirm daemon is ready."""
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Frontend static files — MUST be last (catch-all "/" mount)
# ---------------------------------------------------------------------------
# Serve built frontend in production (Docker image copies dist to /app/static/).
# In dev, Vite on :5173 serves the frontend — this dir won't exist.
#
# StaticFiles(html=True) serves index.html for "/" but NOT for SPA routes
# like /inbox, /wiki, /ask. The catch-all route below handles those by
# returning index.html for any path that doesn't match a static file.
_static_dir: Path | None = None
for _candidate in [Path("/app/static"), Path(__file__).resolve().parent.parent.parent / "static"]:
    if _candidate.is_dir():
        _static_dir = _candidate
        app.mount("/assets", StaticFiles(directory=str(_candidate / "assets")), name="assets")
        break

if _static_dir is not None:
    _index_html = (_static_dir / "index.html").read_text()

    # Middleware intercepts browser navigations to SPA routes that would
    # otherwise collide with top-level API routes (e.g. /settings, /health).
    # Must be added here (after static dir discovery) so the index.html
    # content is available.  Starlette evaluates middleware outermost-first,
    # so this wraps all preceding middleware and runs first on every request.
    app.add_middleware(SPAFallbackMiddleware, static_dir=_static_dir)

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve index.html for all SPA routes (catch-all).

        Handles SPA routes that do NOT collide with an API route (e.g.
        /inbox, /wiki, /ask).  Colliding paths (/settings, /health) are
        handled earlier by ``SPAFallbackMiddleware`` for browser requests.
        """
        # Check if the path matches a real static file
        assert _static_dir is not None  # guarded by outer `if`
        static_file = (_static_dir / path).resolve()
        if static_file.is_file() and static_file.is_relative_to(_static_dir):
            return FileResponse(str(static_file))
        return HTMLResponse(_index_html)
