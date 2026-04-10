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
FROM base AS dev

# Install the dev extras (tests + lint) but NOT the `search` extras by
# default — the `chromadb` and `sentence-transformers` deps in `[search]`
# pull PyTorch and the HuggingFace transformers stack (~4.7GB) and nothing
# in `src/wikimind/` actually imports them yet. A test fixture in
# `tests/conftest.py` uses `pytest.importorskip("chromadb")` so tests
# skip cleanly when the extras aren't present. Keeping `[search]` out of
# the default dev image drops it from ~6.3GB to ~1.6GB; rebuild with
# `--build-arg EXTRAS=dev,search` if you need the search stack.
ARG EXTRAS=dev
COPY pyproject.toml README.md ./
COPY src ./src
# Upgrade pip, setuptools, AND wheel before installing — the python:3.11-slim
# base ships with older versions that Trivy flags for:
#   CVE-2026-23949 (jaraco.context ≤5.3.0, vendored inside setuptools)
#   CVE-2026-24049 (wheel ≤0.45.1, both top-level and vendored in setuptools)
# Both are build-time tools, not runtime deps, but HIGH severity with fixes
# available — cheaper to upgrade than to justify a .trivyignore exception.
RUN pip install --upgrade pip setuptools wheel \
    && pip install -e ".[${EXTRAS}]"

COPY . .

EXPOSE 7842
CMD ["uvicorn", "wikimind.main:app", "--host", "0.0.0.0", "--port", "7842", "--reload"]

# ---------------------------------------------------------------------------
FROM base AS prod

COPY pyproject.toml README.md ./
COPY src ./src
# Same CVE upgrade as the dev stage — see comment above.
RUN pip install --upgrade pip setuptools wheel \
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
