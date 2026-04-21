# ADR-025: Docling-Serve Sidecar for PDF Extraction

**Status:** Accepted
**Date:** 2026-04-20

## Context

WikiMind uses Docling for structured PDF extraction (heading hierarchy, tables, OCR, multi-column layouts). Previously, Docling ran in-process within the FastAPI application, which required:

- PyTorch CPU (~1.7GB)
- Docling library + dependencies
- Playwright + Chromium (~500MB) for HTML backend
- RapidOCR models (~200MB)
- ONNX Runtime

This made the production Docker image ~3GB, CI builds took 12-14 minutes (near the 15-min timeout), cold starts were 10-15s, and each gunicorn worker consumed ~500MB RSS just for ML model loading — limiting the VM to 1 worker on a 4GB machine.

## Decision

Replace in-process Docling with [docling-serve](https://github.com/docling-project/docling-serve) — an HTTP API sidecar maintained by IBM (MIT license) that wraps Docling in a FastAPI service.

The main WikiMind container calls `POST /v1/convert/source` on the sidecar to extract PDF content. The sidecar runs as:

- A Docker Compose service in dev/staging
- A separate Fly.io app (`wikimind-docling`) on the internal network in production

## Consequences

### Positive

- Main image: ~3GB → ~400MB
- CI docker build: 12-14min → 2-3min (5x safety margin to 15-min timeout)
- Cold start: 10-15s → 2-3s
- Workers per VM: 1 → 4-8 (no ML memory overhead)
- gunicorn timeout: 120s → 30s (PDF offloaded)
- Separation of concerns: API scaling independent of PDF processing scaling

### Negative

- Network hop for PDF extraction (adds ~100ms latency per request — negligible vs 5-30s extraction time)
- Additional service to monitor (mitigated by health checks)
- Sidecar image is large (~4GB) but is pre-built by IBM — we never build it ourselves

### Neutral

- fitz (pymupdf) fallback retained for environments without the sidecar (returns plain text, no structure)
- Vision enhancement (LLM-powered slide description) is unaffected — it uses the LLM router, not docling

## Supersedes

- Partially supersedes [ADR-015](adr-015-cpu-first-docker-packaging.md) (CPU-first Docker packaging) — the PyTorch/ONNX packaging concerns no longer apply to the main image
