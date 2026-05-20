"""FastAPI application entry point and lifespan management.

Runs as a local daemon on localhost:7842. Initializes the database,
registers all routers, and configures CORS for Electron and web dev servers.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlmodel import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from wikimind.api.routes import (
    admin,
    api_keys,
    auth,
    capture,
    compilation_schemas,
    discussion,
    drafts,
    export,
    health,
    ingest,
    jobs,
    lint,
    mcp_oauth,
    mcp_tokens,
    query,
    saved_searches,
    sharing,
    synthesis,
    tags,
    wiki,
    ws,
)
from wikimind.api.routes import settings as settings_router
from wikimind.api.routes.settings import apply_runtime_llm_preferences
from wikimind.api.routes.ws import WebSocketBudgetEmitter, _start_redis_subscriber, stop_redis_subscriber
from wikimind.config import get_settings
from wikimind.database import close_db, get_session_factory, init_db
from wikimind.engine.llm_router import configure_llm_router
from wikimind.jobs.background import get_background_compiler
from wikimind.mcp.client import get_mcp_client_manager
from wikimind.middleware.auth import AuthMiddleware
from wikimind.middleware.correlation import CorrelationIdMiddleware
from wikimind.middleware.error_handling import ErrorHandlingMiddleware
from wikimind.middleware.logging_config import configure_logging
from wikimind.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from wikimind.middleware.request_logging import RequestLoggingMiddleware
from wikimind.middleware.security_headers import SecurityHeadersMiddleware
from wikimind.models import IngestStatus, Source
from wikimind.services.quota import QuotaExceededError

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# SPA fallback middleware — intercepts browser navigations that would
# otherwise hit API routes sharing the same path (e.g. /settings, /health).
# ---------------------------------------------------------------------------
# Paths/prefixes that should always be handled by FastAPI, never the SPA.
_API_ONLY_PREFIXES = (
    "/api/",
    "/assets/",
    "/auth/",
    "/docs",
    "/health",
    "/mcp/",
    "/metrics",
    "/public/",
    "/redoc",
    "/openapi.json",
    "/.well-known/",
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


async def _verify_write_permissions(settings) -> None:
    """Verify write permissions to data directories (fail fast before DB init)."""
    if settings.storage_backend != "local":
        return
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


async def _reset_stuck_sources() -> None:
    """Reset sources stuck in PROCESSING from a prior crash/restart.

    If the server is starting, no worker is mid-compilation, so any
    source still in PROCESSING was interrupted.
    """
    async with get_session_factory()() as session:
        result = await session.exec(select(Source).where(Source.status == IngestStatus.PROCESSING))
        stuck = list(result.all())
        for source in stuck:
            source.status = IngestStatus.FAILED
            source.error_message = "Compilation interrupted — retry when ready"
            session.add(source)
        if stuck:
            await session.commit()
            log.info("Reset stuck processing sources", count=len(stuck))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup and shutdown lifecycle."""
    configure_logging()

    if dsn := os.environ.get("SENTRY_DSN"):
        import sentry_sdk  # noqa: PLC0415 — conditional: only loaded when SENTRY_DSN is set

        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)
        log.info("Sentry initialized")

    settings = get_settings()
    settings.ensure_dirs()

    await _verify_write_permissions(settings)

    log.info("WikiMind gateway starting", port=settings.gateway_port)
    await init_db()
    configure_llm_router(event_emitter=WebSocketBudgetEmitter())
    await apply_runtime_llm_preferences()
    log.info("Database initialized")

    await _reset_stuck_sources()
    await _start_redis_subscriber()

    # Start MCP client connections to external servers (if configured)
    if settings.mcp.client_enabled:
        mcp_manager = get_mcp_client_manager()
        await mcp_manager.start()

    yield

    log.info("WikiMind gateway shutting down")

    # Stop MCP client connections
    if settings.mcp.client_enabled:
        mcp_manager = get_mcp_client_manager()
        await mcp_manager.stop()

    await get_background_compiler().close()
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
        {"name": "Capture", "description": "Ambient capture inbox and RSS feeds"},
        {"name": "Query", "description": "Ask questions against the wiki"},
        {"name": "Jobs", "description": "Manage async compilation and linting jobs"},
        {"name": "Lint", "description": "Wiki health audit reports and findings"},
        {"name": "Settings", "description": "LLM provider configuration and cost tracking"},
        {"name": "Admin", "description": "System diagnostics and maintenance"},
        {"name": "Auth", "description": "OAuth2 authentication"},
        {"name": "Export", "description": "Export wiki articles as PDF, LinkedIn, or slides"},
        {"name": "Tags", "description": "User-created organizational tags"},
        {"name": "SavedSearches", "description": "Saved searches with tag and concept filters"},
        {"name": "Sharing", "description": "Per-article share links and public access"},
        {"name": "Synthesis", "description": "Cross-cutting synthesis pages across multiple sources"},
        {"name": "CompilationSchemas", "description": "User-defined compilation rules for wiki articles"},
        {"name": "Billing", "description": "Subscription plans, usage quotas, checkout, and webhooks"},
        {"name": "WebSocket", "description": "Real-time progress streams"},
    ],
)

# ---------------------------------------------------------------------------
# Rate limiting — register slowapi limiter and 429 handler
# ---------------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Prometheus metrics — exposes /metrics for scraping
# ---------------------------------------------------------------------------
from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402

Instrumentator(
    excluded_handlers=["/health", "/health/deep", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")

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

# Mount routers — all API routes live under /api for clean SPA separation.
# Health, docs, and auth remain at root level.
api_router = APIRouter(prefix="/api")
api_router.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
api_router.include_router(capture.router, prefix="/capture", tags=["Capture"])
api_router.include_router(drafts.router, prefix="/ingest", tags=["Ingest"])
api_router.include_router(wiki.router, prefix="/wiki", tags=["Wiki"])
api_router.include_router(discussion.router, prefix="/wiki", tags=["Wiki"])
api_router.include_router(query.router, prefix="/query", tags=["Query"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
api_router.include_router(lint.router, prefix="/lint", tags=["Lint"])
api_router.include_router(settings_router.router, prefix="/settings", tags=["Settings"])
api_router.include_router(api_keys.router, prefix="/settings/api-keys", tags=["Settings"])
api_router.include_router(mcp_tokens.router, prefix="/settings/mcp-tokens", tags=["Settings"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
api_router.include_router(export.router, prefix="/wiki", tags=["Export"])
api_router.include_router(tags.router, prefix="/tags", tags=["Tags"])
api_router.include_router(saved_searches.router, prefix="/saved-searches", tags=["SavedSearches"])
api_router.include_router(sharing.router, prefix="/wiki", tags=["Sharing"])
api_router.include_router(synthesis.router, prefix="/wiki", tags=["Synthesis"])
api_router.include_router(compilation_schemas.router, prefix="/compilation-schemas", tags=["CompilationSchemas"])

# Billing routes — only in hosted mode (deployment_mode == "hosted").
# In self-hosted mode billing is disabled and these endpoints are not mounted.
if get_settings().billing_enabled:
    from wikimind.api.routes import billing as billing_router_mod

    api_router.include_router(billing_router_mod.router, prefix="/billing", tags=["Billing"])

app.include_router(api_router)

# Public share links — no auth required. Mounted at root level so the
# auth middleware EXEMPT_PREFIXES can skip these paths.
app.include_router(sharing.public_router, tags=["Sharing"])

# Health, Auth, and WebSocket remain at root — auth redirects require stable
# paths, and WebSocket connections are not prefixed.
app.include_router(health.router, tags=["Admin"])
app.include_router(ws.router, tags=["WebSocket"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])

# MCP OAuth 2.1 Authorization Server — metadata at /.well-known/... (root),
# authorization/token/revocation at /mcp/* (root).
app.include_router(mcp_oauth.metadata_router, tags=["Auth"])
app.include_router(mcp_oauth.router, prefix="/mcp", tags=["Auth"])

# ---------------------------------------------------------------------------
# Exception handlers — normalize all error responses to the standard envelope
# ---------------------------------------------------------------------------

_STATUS_TO_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Wrap FastAPI HTTPException in the standard JSON error envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    code = _STATUS_TO_CODE.get(exc.status_code, f"http_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Wrap Pydantic validation errors in the standard JSON error envelope."""
    request_id = getattr(request.state, "request_id", "unknown")
    messages = []
    for err in exc.errors():
        loc = " -> ".join(str(part) for part in err.get("loc", []))
        msg = err.get("msg", "")
        messages.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "; ".join(messages),
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_handler(request: Request, exc: QuotaExceededError) -> JSONResponse:
    """Return 429 with quota details when a plan limit is exceeded."""
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "quota_exceeded",
                "message": str(exc),
                "resource": exc.resource,
                "limit": exc.limit,
                "used": exc.used,
                "upgrade_url": "/settings/billing",
                "request_id": request_id,
            }
        },
    )


@app.get("/health")
async def health_check():
    """Health check — used by Electron to confirm daemon is ready."""
    settings = get_settings()
    background_mode = "arq" if settings.redis_url else "in-process"
    return {"status": "ok", "version": "0.1.0", "background_mode": background_mode}


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
