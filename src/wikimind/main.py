"""FastAPI application entry point and lifespan management.

Runs as a local daemon on localhost:7842. Initializes the database,
registers all routers, and configures CORS for Electron and web dev servers.
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from wikimind.api.routes import ingest, jobs, lint, query, wiki, ws
from wikimind.api.routes import settings as settings_router
from wikimind.config import get_settings
from wikimind.database import close_db, init_db
from wikimind.errors import WikiMindError
from wikimind.ingest.service import _DOCLING_AVAILABLE, _get_docling_converter
from wikimind.middleware.correlation import CorrelationIdMiddleware
from wikimind.middleware.error_handling import ErrorHandlingMiddleware
from wikimind.middleware.logging_config import configure_logging
from wikimind.middleware.request_logging import RequestLoggingMiddleware
from wikimind.middleware.security_headers import SecurityHeadersMiddleware

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    configure_logging()

    settings = get_settings()
    settings.ensure_dirs()

    log.info("WikiMind gateway starting", port=settings.gateway_port)
    await init_db()
    log.info("Database initialized")

    # Warm up the Docling converter in a background thread so ML model
    # weights (~500 MB) are downloaded and loaded before the first PDF
    # arrives.  Without this, the first PDF ingest blocks for 30-60 s
    # while models are fetched and the UI appears stuck.
    try:
        if _DOCLING_AVAILABLE:
            log.info("Warming up Docling converter (background thread)…")
            await asyncio.to_thread(_get_docling_converter)
            log.info("Docling converter ready")
    except Exception:
        log.warning("Docling warm-up failed — will retry on first PDF ingest")

    yield

    log.info("WikiMind gateway shutting down")
    await close_db()


app = FastAPI(
    title="WikiMind Gateway",
    description="Local LLM Knowledge OS — Personal API",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware stack — evaluated bottom-to-top.
# Request flow: Correlation → Logging → SecurityHeaders → ErrorHandling → CORS → routes
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Allow Electron renderer and web dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React dev server
        "http://localhost:5173",  # Vite dev server
        "app://.",  # Electron
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(ingest.router, prefix="/ingest", tags=["Ingest"])
app.include_router(wiki.router, prefix="/wiki", tags=["Wiki"])
app.include_router(query.router, prefix="/query", tags=["Query"])
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
app.include_router(lint.router, prefix="/lint", tags=["Lint"])
app.include_router(settings_router.router, prefix="/settings", tags=["Settings"])
app.include_router(ws.router, tags=["WebSocket"])


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
