# vulture whitelist -- items that appear unused but are used by frameworks
#
# This file exists solely to suppress false-positive "unused code" warnings
# from vulture (dead-code detector).  Every import and attribute access below
# is intentionally unreferenced in application code because the symbols are
# consumed by frameworks at runtime (FastAPI, SQLModel/Pydantic, ARQ).
#
# FastAPI route handlers are called by the framework, not directly.
# SQLModel / Pydantic fields are accessed by the ORM, not referenced in code.
# ARQ worker settings are read by the arq runtime.

# FastAPI route handlers (called by the framework, not directly)
# CodeQL: unused-import — intentional vulture whitelist entries
from wikimind.api.routes import ingest, jobs, query, settings, wiki, ws  # noqa: F401

# CLI entry point and subcommands (invoked by click framework, not directly)
# CodeQL: unused-import — intentional vulture whitelist entry
from wikimind.cli import main  # noqa: F401

# SQLModel table fields (used by ORM, not directly referenced)
from wikimind.models import *  # noqa: F403

# Pydantic model_config
_.model_config

# ARQ worker settings
_.cron_jobs
_.functions
_.on_startup
_.redis_settings
