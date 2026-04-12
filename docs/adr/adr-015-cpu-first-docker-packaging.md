# ADR-015: CPU-First Docker Packaging

**Status:** Accepted
**Date:** 2026-04-12
**Issue:** [#140](https://github.com/manavgup/wikimind/issues/140)

## Context

WikiMind uses [Docling](https://github.com/docling-project/docling) for structured PDF-to-markdown extraction. Docling depends on PyTorch for its internal layout-detection models, but WikiMind only uses CPU inference — no GPU configuration exists in the codebase.

By default, `pip install docling` pulls the full CUDA PyTorch distribution, inflating the Docker image from ~1.7 GB to ~9.7 GB, CI builds from ~3 min to ~15 min, and introducing nvidia/CUDA CVEs that do not apply to our deployment.

## Decision

1. **CPU-only PyTorch by default.** The Dockerfile uses `ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu` and passes `--extra-index-url ${TORCH_INDEX}` to pip. This installs CPU-only torch wheels, eliminating ~8 GB of CUDA libraries.

2. **GPU opt-in via build arg.** Rebuild with `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121` when GPU inference is needed (high-volume PDF ingestion, VLM extras, Whisper transcription).

3. **Docling is an optional extra `[pdf]`.** Moved from core dependencies to `[project.optional-dependencies] pdf`. Users who only need URL/text/YouTube ingestion skip the entire torch stack. A `pymupdf` (fitz) fallback provides basic PDF text extraction when docling is absent.

4. **Bloat guard prevents regression.** A static check (`scripts/check_docker_bloat.py`) runs in pre-commit and CI to ensure GPU-heavy packages (torch, nvidia, docling, sentence-transformers, etc.) do not re-enter core dependencies.

## Consequences

### Positive

- Docker prod image: ~9.7 GB → ~1.7 GB (82% reduction)
- CI build time: ~15 min → ~3-5 min
- Trivy CVE scan passes (no nvidia/CUDA vulnerabilities)
- `pip install wikimind` no longer forces ~4 GB of ML dependencies
- GPU path preserved for future use via build arg

### Negative

- Users who want structured PDF extraction must install with `pip install "wikimind[pdf]"` instead of bare `pip install wikimind`
- Without `[pdf]`, PDF uploads fall back to pymupdf plain-text extraction (no heading hierarchy or layout awareness)

### When to switch to GPU

- High-volume PDF ingestion (>100 PDFs/day) where CPU is a bottleneck
- Adding Docling's `[vlm]` extra for vision-language document understanding
- Adding Whisper `[transcribe]` extra for audio transcription
- Any future feature requiring CUDA-accelerated inference

## References

- [Reducing Docling Docker image size](https://shekhargulati.com/2025/02/05/reducing-size-of-docling-pytorch-docker-image/)
- [Docling installation docs](https://docling-project.github.io/docling/getting_started/installation/)
- [Docling CPU-only discussion](https://github.com/docling-project/docling/discussions/1349)
