# syntax=docker/dockerfile:1.6
# Multi-stage Dockerfile for WikiMind gateway.
#
# Stages:
#   base   — common Python runtime + system deps
#   dev    — editable install with dev/test/lint extras (used by docker-compose)
#   prod   — slim runtime with only production dependencies

# ---------------------------------------------------------------------------
# PyTorch index — defaults to CPU-only wheels (~1.7 GB image).
# For GPU/CUDA support, rebuild with:
#   docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121 .
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libraries required by pymupdf, sqlite, healthchecks, and keyring.
# The upgrade step patches OS-level CVEs (e.g. openssl) so the Trivy scan
# passes even when the base image ships with a known vulnerability.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libmupdf-dev \
        libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

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

# Install the dev extras (tests + lint + pdf) but NOT `search` by default.
# The `[search]` extras pull chromadb + sentence-transformers (~4.7 GB);
# rebuild with `--build-arg EXTRAS=dev,search` if you need the search stack.
# The `[pdf]` extra pulls docling + PyTorch; CPU-only wheels keep the image
# under 2 GB (see TORCH_INDEX above). GPU builds use cu121 wheels (~9 GB).
ARG EXTRAS=dev
ARG TORCH_INDEX
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Use uv for reproducible installs pinned by uv.lock.
# UV_EXTRA_INDEX_URL provides CPU-only PyTorch wheels when needed.
ENV UV_EXTRA_INDEX_URL=${TORCH_INDEX}
RUN uv sync --frozen --extra ${EXTRAS}

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
#
# Worker auto-tuning:
#   gunicorn.conf.py sets workers = min(2 * CPU + 1, 8).
#   Override at runtime with WEB_CONCURRENCY env var:
#     docker run -e WEB_CONCURRENCY=4 wikimind:latest
# ---------------------------------------------------------------------------
FROM base AS prod

ARG TORCH_INDEX
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Use uv for reproducible installs pinned by uv.lock.
# Install with [pdf] extra for structured PDF extraction via docling.
# Playwright is needed by docling's HTML backend for URL ingestion.
ENV UV_EXTRA_INDEX_URL=${TORCH_INDEX}
RUN uv sync --frozen --extra pdf \
    && uv pip install gunicorn playwright onnxruntime \
    && uv run playwright install --with-deps chromium

# Pre-download RapidOCR models so they don't need to be fetched at runtime
# from modelscope.cn (unreliable from US datacenters). Non-fatal if it fails.
RUN uv run python -c "from rapidocr import RapidOCR; RapidOCR()" \
    || echo "WARN: RapidOCR model pre-download failed (non-fatal)"

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

# Run as a non-root user in production.
# Pre-create model cache dirs so rapidocr/docling can write model files at runtime.
RUN useradd --create-home --uid 1000 wikimind \
    && mkdir -p /home/wikimind/.wikimind \
    && chown -R wikimind:wikimind /home/wikimind /app \
    && chown -R wikimind:wikimind /usr/local/lib/python3.11/site-packages/rapidocr/models/ 2>/dev/null || true
USER wikimind

ENV WIKIMIND_DATA_DIR=/home/wikimind/.wikimind \
    WIKIMIND_SERVER__HOST=0.0.0.0

EXPOSE 7842

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7842/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "wikimind.main:app", "-c", "gunicorn.conf.py"]
