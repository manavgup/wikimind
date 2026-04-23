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
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from wikimind.api.routes import admin, api_keys, auth, export, ingest, jobs, lint, query, wiki, ws
from wikimind.api.routes import settings as settings_router
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
from wikimind.models import Article, IngestStatus, Source, UserPreference

log = structlog.get_logger()


async def _apply_db_preferences() -> None:
    """Apply persisted user preferences to the in-memory settings singleton."""
    async with get_session_factory()() as session:
        result = await session.execute(select(UserPreference))
        for pref in result.scalars().all():
            settings = get_settings()
            if pref.key == "llm.default_provider":
                settings.llm.default_provider = pref.value
            elif pref.key == "llm.monthly_budget_usd":
                settings.llm.monthly_budget_usd = float(pref.value)
            elif pref.key == "llm.fallback_enabled":
                settings.llm.fallback_enabled = pref.value.lower() == "true"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown lifecycle."""
    configure_logging()

    settings = get_settings()
    settings.ensure_dirs()

    log.info("WikiMind gateway starting", port=settings.gateway_port)
    await init_db()
    await _apply_db_preferences()
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

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve index.html for all SPA routes (catch-all)."""
        # Check if the path matches a real static file
        assert _static_dir is not None  # guarded by outer `if`
        static_file = (_static_dir / path).resolve()
        if static_file.is_file() and static_file.is_relative_to(_static_dir):
            return FileResponse(str(static_file))
        return HTMLResponse(_index_html)
