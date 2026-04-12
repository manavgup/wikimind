#!/usr/bin/env python3
"""Docker bloat guard — prevent accidental GPU/CUDA dependencies in core.

Parses pyproject.toml and checks that known-heavy packages (docling,
sentence-transformers, torch, nvidia-*, etc.) are NOT in the core
``[project] dependencies`` list.  They belong in optional extras so
the Docker image stays small (~1.7 GB CPU-only vs ~9.7 GB with CUDA).

Exit codes:
    0 — clean, no bloat detected
    1 — GPU-pulling package found in core deps

Usage:
    python scripts/check_docker_bloat.py            # fail on bloat
    python scripts/check_docker_bloat.py --allow-gpu  # skip check (intentional GPU build)
"""

from __future__ import annotations

import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# Packages that pull PyTorch / CUDA / nvidia transitive deps.
# If any of these appear in core deps, the Docker image balloons.
HEAVY_PACKAGES = {
    "docling",
    "sentence-transformers",
    "torch",
    "torchvision",
    "torchaudio",
    "accelerate",
    "transformers",
    "openai-whisper",
    "chromadb",
}


def _normalize(name: str) -> str:
    """PEP 503 normalize: lowercase, replace [-_.] with -."""
    return (
        name.lower()
        .replace("_", "-")
        .replace(".", "-")
        .split("[")[0]
        .split(">")[0]
        .split("<")[0]
        .split("=")[0]
        .split("!")[0]
        .strip()
    )


def main() -> int:
    """Check pyproject.toml core deps for GPU-heavy packages."""
    if "--allow-gpu" in sys.argv:
        print("Bloat guard: --allow-gpu set, skipping check.")
        return 0

    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    core_deps = data.get("project", {}).get("dependencies", [])
    normalized = {_normalize(d) for d in core_deps}

    found = normalized & HEAVY_PACKAGES
    if found:
        print(f"ERROR: GPU-heavy packages in core dependencies: {', '.join(sorted(found))}")
        print("These belong in optional extras ([pdf], [search], [transcribe]).")
        print("Move them to [project.optional-dependencies] in pyproject.toml.")
        print("If this is intentional, run with --allow-gpu.")
        return 1

    print(f"Bloat guard: OK — {len(core_deps)} core deps, none GPU-heavy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
