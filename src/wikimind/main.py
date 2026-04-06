"""FastAPI application entry point and lifespan management.

Runs as a local daemon on localhost:7842. Initializes the database,
registers all routers, and configures CORS for Electron and web dev servers.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wikimind.api.routes import ingest, jobs, query, wiki, ws
from wikimind.api.routes import settings as settings_router
from wikimind.config import get_settings
from wikimind.database import close_db, init_db

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    settings = get_settings()
    settings.ensure_dirs()

    log.info("WikiMind gateway starting", port=settings.gateway_port)
    await init_db()
    log.info("Database initialized")

    yield

    log.info("WikiMind gateway shutting down")
    await close_db()


app = FastAPI(
    title="WikiMind Gateway",
    description="Local LLM Knowledge OS — Personal API",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.include_router(settings_router.router, prefix="/settings", tags=["Settings"])
app.include_router(ws.router, tags=["WebSocket"])


@app.get("/health")
async def health():
    """Health check — used by Electron to confirm daemon is ready."""
    return {"status": "ok", "version": "0.1.0"}
