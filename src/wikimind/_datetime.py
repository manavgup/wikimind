"""Internal datetime helpers.

This module provides drop-in replacements for deprecated datetime APIs.
Lives at the package root with an underscore prefix to mark it as internal.
"""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Return the current UTC time as a NAIVE datetime.

    Replacement for the deprecated ``datetime.datetime.utcnow()``.
    Preserves the "naive datetime in UTC" semantics that the rest of the
    codebase and SQLite's default datetime serialization rely on.

    Why naive? SQLAlchemy / SQLModel serialize aware and naive datetimes
    differently, and the existing schema + tests assume naive UTC. A
    pure ``datetime.now(UTC)`` would return an aware datetime, causing
    naive-vs-aware comparison errors throughout the codebase. This
    helper sidesteps that by stripping tzinfo immediately.

    A future PR may migrate the whole codebase to timezone-aware
    datetimes; until then, this is the cleanest non-deprecated path.
    """
    return datetime.now(UTC).replace(tzinfo=None)
