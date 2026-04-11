# vulture whitelist -- items that appear unused but are used by frameworks
#
# FastAPI route handlers are called by the framework, not directly.
# SQLModel / Pydantic fields are accessed by the ORM, not referenced in code.
# ARQ worker settings are read by the arq runtime.

# FastAPI route handlers (called by the framework, not directly)
from wikimind.api.routes import ingest, jobs, query, settings, wiki, ws  # noqa: F401

# SQLModel table fields (used by ORM, not directly referenced)
from wikimind.models import *  # noqa: F403

# Pydantic model_config
_.model_config  # noqa

# ARQ worker settings
_.cron_jobs  # noqa
_.functions  # noqa
_.on_startup  # noqa
_.redis_settings  # noqa
