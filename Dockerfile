# syntax=docker/dockerfile:1.6
# Multi-stage Dockerfile for WikiMind gateway.
#
# Stages:
#   base   — common Python runtime + system deps
#   dev    — editable install with dev/test/lint extras (used by docker-compose)
#   prod   — slim runtime with only production dependencies

# ---------------------------------------------------------------------------
# Pin to specific Python version to prevent upstream breakage.
# Update deliberately via PR, not silently via :latest.
ARG PYTHON_VERSION=3.11.12
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1

# System libraries required by pymupdf, sqlite, healthchecks, and keyring.
# The upgrade step patches OS-level CVEs (e.g. openssl) so the Trivy scan
# passes even when the base image ships with a known vulnerability.
# Also upgrade pip/setuptools/wheel to patch CVE-2026-23949 & CVE-2026-24049.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        gosu \
        libmupdf-dev \
        libnghttp2-14 \
        libsqlite3-0 \
    && pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

WORKDIR /app

# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
FROM base AS dev

# Install the dev extras (tests + lint) for local development.
# PDF extraction is handled by the docling-serve sidecar container.
ARG EXTRAS=dev
COPY pyproject.toml uv.lock README.md ./

# Sync dependencies without installing the project to cache them
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra ${EXTRAS}

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra ${EXTRAS}

COPY . .

EXPOSE 7842
CMD ["uv", "run", "uvicorn", "wikimind.main:app", "--host", "0.0.0.0", "--port", "7842", "--reload"]

# ---------------------------------------------------------------------------
# Production stage — slim runtime image.
#
# Build flow:
#   1. "frontend" stage (node:20-alpine) builds React app → /app/dist/
#   2. "base" stage installs Python + system libs
#   3. This stage installs production Python deps, then copies in:
#      - built frontend from stage 1
#      - Alembic migrations (for Postgres deployments)
#      - gunicorn.conf.py (auto-tunes workers to CPU)
#      - docker-entrypoint.sh (runs migrations before starting gunicorn)
#      - start-combined.sh (optional: runs redis + arq worker + gunicorn in
#        one container for combined/scale-to-zero single-machine deployments)
#
# Worker auto-tuning:
#   gunicorn.conf.py sets workers = min(2 * CPU + 1, 8).
#   Override at runtime with WEB_CONCURRENCY env var:
#     docker run -e WEB_CONCURRENCY=4 wikimind:latest
# ---------------------------------------------------------------------------
FROM base AS prod

# redis-server — required for the optional combined-process mode
# (start-combined.sh runs redis, arq worker, and gunicorn in one container).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        redis-server \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./

# Sync dependencies without installing the project to cache them.
# Install only production dependencies — no ML libs, no playwright.
# PDF extraction is handled by the docling-serve sidecar container.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen \
    && uv pip install gunicorn

# Alembic migrations for Postgres deployments
COPY alembic.ini ./
COPY alembic ./alembic

# Built frontend from the "frontend" multi-stage build
COPY --from=frontend /app/dist ./static/

# Gunicorn config — auto-tunes workers to available CPU cores.
# See gunicorn.conf.py for formula and WEB_CONCURRENCY override.
COPY gunicorn.conf.py ./

# Entrypoint: run Alembic migrations (Postgres only), then exec CMD
COPY docker/entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

# Optional combined-process startup (redis + arq worker + gunicorn).
# Invoked via: docker run ... --entrypoint ./docker-entrypoint.sh image ./start-combined.sh
COPY docker/start-combined.sh ./start-combined.sh
RUN chmod +x start-combined.sh

# Run as a non-root user in production.
RUN useradd --create-home --uid 1000 wikimind \
    && mkdir -p /home/wikimind/.wikimind \
    && chown -R wikimind:wikimind /home/wikimind /app
ENV WIKIMIND_DATA_DIR=/home/wikimind/.wikimind \
    WIKIMIND_SERVER__HOST=0.0.0.0

EXPOSE 7842

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7842/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "wikimind.main:app", "-c", "gunicorn.conf.py"]
