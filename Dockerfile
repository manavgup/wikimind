# syntax=docker/dockerfile:1.6
# Multi-stage Dockerfile for WikiMind gateway.
#
# Stages:
#   base   — common Python runtime + system deps
#   dev    — editable install with dev/test/lint extras (used by docker-compose)
#   prod   — slim runtime with only production dependencies

# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libraries required by pymupdf, sqlite, healthchecks, and keyring.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libmupdf-dev \
        libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
FROM base AS dev

# Install dev dependencies first so layer caches on source-only edits.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install -e ".[dev,search]"

COPY . .

EXPOSE 7842
CMD ["uvicorn", "wikimind.main:app", "--host", "0.0.0.0", "--port", "7842", "--reload"]

# ---------------------------------------------------------------------------
FROM base AS prod

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install .

# Run as a non-root user in production.
RUN useradd --create-home --uid 1000 wikimind \
    && mkdir -p /home/wikimind/.wikimind \
    && chown -R wikimind:wikimind /home/wikimind /app
USER wikimind

ENV WIKIMIND_DATA_DIR=/home/wikimind/.wikimind \
    WIKIMIND_SERVER__HOST=0.0.0.0

EXPOSE 7842

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7842/health || exit 1

CMD ["gunicorn", "wikimind.main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:7842"]
