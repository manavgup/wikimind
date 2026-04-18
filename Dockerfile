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
COPY pyproject.toml README.md ./
COPY src ./src
# Upgrade pip, setuptools, AND wheel before installing — the python:3.11-slim
# base ships with older versions that Trivy flags for:
#   CVE-2026-23949 (jaraco.context ≤5.3.0, vendored inside setuptools)
#   CVE-2026-24049 (wheel ≤0.45.1, both top-level and vendored in setuptools)
# Both are build-time tools, not runtime deps, but HIGH severity with fixes
# available — cheaper to upgrade than to justify a .trivyignore exception.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url ${TORCH_INDEX} -e ".[${EXTRAS}]"

COPY . .

EXPOSE 7842
CMD ["uvicorn", "wikimind.main:app", "--host", "0.0.0.0", "--port", "7842", "--reload"]

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
COPY pyproject.toml README.md ./
COPY src ./src
# Same CVE upgrade as the dev stage — see comment above.
# Install with [pdf] extra for structured PDF extraction via docling.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --extra-index-url ${TORCH_INDEX} ".[pdf]" gunicorn

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
RUN useradd --create-home --uid 1000 wikimind \
    && mkdir -p /home/wikimind/.wikimind \
    && chown -R wikimind:wikimind /home/wikimind /app
USER wikimind

ENV WIKIMIND_DATA_DIR=/home/wikimind/.wikimind \
    WIKIMIND_SERVER__HOST=0.0.0.0

EXPOSE 7842

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7842/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "wikimind.main:app", "-c", "gunicorn.conf.py"]
