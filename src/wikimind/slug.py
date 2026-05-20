"""Shared slug generation for wiki articles.

Centralizes the ``title -> unique slug`` logic that was previously
duplicated across compiler, wiki service, synthesis compiler, and
crystallization modules.  All call sites now delegate here so the
max-attempts cap and per-user scoping are consistent everywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slugify import slugify
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.models import Article

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


async def generate_unique_slug(
    title: str,
    session: AsyncSession,
    *,
    user_id: str,
    prefix: str = "",
    max_length: int = 80,
    max_attempts: int | None = None,
) -> str:
    """Generate a URL-safe slug from *title*, avoiding per-user collisions.

    Tries the base slug first; if it already exists for this user,
    appends ``-2``, ``-3``, etc. until a unique value is found or the
    attempt limit is reached.

    Args:
        title: The title to slugify.
        session: Async database session for collision checks.
        user_id: Owner user ID -- slugs are unique per user.
        prefix: Optional prefix (e.g. ``"synthesis-"``) prepended to the slug.
        max_length: Maximum slug length before prefix.
        max_attempts: Cap on collision retries.  Defaults to
            ``settings.compiler.slug_max_attempts`` when ``None``.

    Returns:
        A unique slug string.

    Raises:
        ValueError: If no unique slug is found within *max_attempts*.
    """
    if max_attempts is None:
        max_attempts = get_settings().compiler.slug_max_attempts
    base = f"{prefix}{slugify(title, max_length=max_length)}"
    candidate = base
    suffix = 2
    for _ in range(max_attempts):
        existing = (
            await session.exec(
                select(Article).where(
                    Article.slug == candidate,
                    Article.user_id == user_id,
                )
            )
        ).first()
        if existing is None:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1
    msg = f"Could not generate unique slug for {title!r} after {max_attempts} attempts"
    raise ValueError(msg)
