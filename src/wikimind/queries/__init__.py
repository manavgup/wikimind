"""Composable query helpers for article data access.

Centralizes data access patterns that were previously duplicated across
``services.wiki``, ``services.query``, ``jobs.worker``, and route modules.
All article source/concept resolution — including the legacy JSON-column
fallback — lives here so callers never re-implement the same logic.
"""

from wikimind.queries.articles import (
    fetch_concept_names_for_article,
    fetch_concepts_for_articles,
    fetch_source_ids_for_article,
    fetch_sources,
    parse_json_column,
)

__all__ = [
    "fetch_concept_names_for_article",
    "fetch_concepts_for_articles",
    "fetch_source_ids_for_article",
    "fetch_sources",
    "parse_json_column",
]
