"""Ambient capture adapter management service (issue #442).

Manages ambient adapter configurations and dispatches polls. Adapters
are registered by type and instantiated from persisted settings. The
``poll_adapters`` method runs all enabled adapters for a user and creates
CaptureSource rows for each discovered item.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.errors import NotFoundError
from wikimind.ingest.adapters.ambient import AdapterConfig, AmbientAdapter, CapturedItem
from wikimind.ingest.adapters.browser_history import BrowserHistoryAdapter
from wikimind.models import (
    AmbientAdapterConfigureRequest,
    AmbientAdapterListResponse,
    AmbientAdapterSetting,
    AmbientAdapterStatusResponse,
    AmbientPollResponse,
    CaptureSource,
    CaptureStatus,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

# Registry of supported ambient adapter types → constructor callables
_ADAPTER_REGISTRY: dict[str, type[AmbientAdapter]] = {
    "browser_history": BrowserHistoryAdapter,
}


def _build_adapter(setting: AmbientAdapterSetting) -> AmbientAdapter | None:
    """Instantiate an adapter from a persisted setting row.

    Returns None if the adapter type is not in the registry.
    """
    adapter_cls = _ADAPTER_REGISTRY.get(setting.adapter_type)
    if adapter_cls is None:
        log.warning("unknown adapter type", adapter_type=setting.adapter_type)
        return None

    settings_dict = json.loads(setting.settings_json) if setting.settings_json else {}
    config = AdapterConfig(
        enabled=setting.enabled,
        adapter_type=setting.adapter_type,
        settings=settings_dict,
    )
    adapter = adapter_cls(config)
    adapter.last_polled_at = setting.last_polled_at
    return adapter


def _setting_to_response(setting: AmbientAdapterSetting) -> AmbientAdapterStatusResponse:
    """Convert a DB row to an API response."""
    settings_dict = json.loads(setting.settings_json) if setting.settings_json else {}
    return AmbientAdapterStatusResponse(
        adapter_type=setting.adapter_type,
        enabled=setting.enabled,
        last_polled_at=setting.last_polled_at,
        settings=settings_dict,
    )


class AmbientService:
    """Manages ambient adapter configurations and polling."""

    async def configure_adapter(
        self,
        request: AmbientAdapterConfigureRequest,
        session: AsyncSession,
        user_id: str,
    ) -> AmbientAdapterStatusResponse:
        """Configure (create or update) an ambient adapter for a user.

        Args:
            request: Adapter configuration request.
            session: Async database session.
            user_id: Owner of this adapter config.

        Returns:
            AmbientAdapterStatusResponse for the configured adapter.
        """
        if request.adapter_type not in _ADAPTER_REGISTRY:
            msg = f"Unsupported adapter type: {request.adapter_type}"
            raise ValueError(msg)

        # Strip history_db_path — never allow user-supplied filesystem paths
        # to prevent arbitrary local file read (security fix).
        sanitised_settings = {k: v for k, v in request.settings.items() if k != "history_db_path"}

        # Upsert: find existing or create new
        result = await session.execute(
            select(AmbientAdapterSetting).where(
                AmbientAdapterSetting.user_id == user_id,
                AmbientAdapterSetting.adapter_type == request.adapter_type,
            )
        )
        setting = result.scalars().first()

        if setting is None:
            setting = AmbientAdapterSetting(
                user_id=user_id,
                adapter_type=request.adapter_type,
                enabled=request.enabled,
                settings_json=json.dumps(sanitised_settings),
            )
        else:
            setting.enabled = request.enabled
            setting.settings_json = json.dumps(sanitised_settings)

        session.add(setting)
        await session.commit()
        await session.refresh(setting)

        log.info(
            "ambient adapter configured",
            adapter_type=request.adapter_type,
            enabled=request.enabled,
            user_id=user_id,
        )
        return _setting_to_response(setting)

    async def list_adapters(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> AmbientAdapterListResponse:
        """List all configured ambient adapters for a user.

        Args:
            session: Async database session.
            user_id: Owner filter.

        Returns:
            AmbientAdapterListResponse with all adapters.
        """
        result = await session.execute(
            select(AmbientAdapterSetting).where(
                AmbientAdapterSetting.user_id == user_id,
            )
        )
        settings = list(result.scalars().all())
        return AmbientAdapterListResponse(
            adapters=[_setting_to_response(s) for s in settings],
        )

    async def get_adapter_setting(
        self,
        adapter_type: str,
        session: AsyncSession,
        user_id: str,
    ) -> AmbientAdapterSetting:
        """Retrieve a single adapter setting.

        Args:
            adapter_type: The adapter type string.
            session: Async database session.
            user_id: Owner verification.

        Returns:
            The AmbientAdapterSetting record.

        Raises:
            NotFoundError: If the adapter config doesn't exist for this user.
        """
        result = await session.execute(
            select(AmbientAdapterSetting).where(
                AmbientAdapterSetting.user_id == user_id,
                AmbientAdapterSetting.adapter_type == adapter_type,
            )
        )
        setting = result.scalars().first()
        if setting is None:
            msg = f"Adapter config not found: {adapter_type}"
            raise NotFoundError(msg)
        return setting

    async def poll_adapter(
        self,
        adapter_type: str,
        session: AsyncSession,
        user_id: str,
    ) -> AmbientPollResponse:
        """Manually trigger a poll for a specific adapter.

        Args:
            adapter_type: The adapter type to poll.
            session: Async database session.
            user_id: Owner.

        Returns:
            AmbientPollResponse with the number of new captures.
        """
        setting = await self.get_adapter_setting(adapter_type, session, user_id)
        adapter = _build_adapter(setting)
        if adapter is None:
            msg = f"Cannot instantiate adapter: {adapter_type}"
            raise ValueError(msg)

        items = await adapter.poll(session, user_id)
        new_count = await self._save_captured_items(items, session, user_id)

        # Update last_polled_at on the setting
        setting.last_polled_at = utcnow_naive()
        session.add(setting)
        await session.commit()

        return AmbientPollResponse(
            adapter_type=adapter_type,
            new_captures=new_count,
        )

    async def poll_all_adapters(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> int:
        """Poll all enabled adapters for a user.

        Args:
            session: Async database session.
            user_id: Owner filter.

        Returns:
            Total number of new captures across all adapters.
        """
        result = await session.execute(
            select(AmbientAdapterSetting).where(
                AmbientAdapterSetting.user_id == user_id,
                AmbientAdapterSetting.enabled == True,  # noqa: E712
            )
        )
        settings = list(result.scalars().all())

        total_new = 0
        for setting in settings:
            adapter = _build_adapter(setting)
            if adapter is None:
                continue

            try:
                items = await adapter.poll(session, user_id)
                new_count = await self._save_captured_items(items, session, user_id)
                total_new += new_count

                setting.last_polled_at = utcnow_naive()
                session.add(setting)
            except Exception:
                log.exception(
                    "ambient adapter poll failed",
                    adapter_type=setting.adapter_type,
                    user_id=user_id,
                )

        await session.commit()
        return total_new

    async def _save_captured_items(
        self,
        items: list[CapturedItem],
        session: AsyncSession,
        user_id: str,
    ) -> int:
        """Persist captured items as CaptureSource rows.

        Deduplicates by content_hash before inserting.

        Args:
            items: List of items from an adapter poll.
            session: Async database session.
            user_id: Owner.

        Returns:
            Number of new captures created.
        """
        new_count = 0
        for item in items:
            content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()

            # Dedup check
            existing = await session.execute(
                select(CaptureSource).where(
                    CaptureSource.user_id == user_id,
                    CaptureSource.content_hash == content_hash,
                )
            )
            if existing.scalars().first() is not None:
                continue

            capture = CaptureSource(
                user_id=user_id,
                kind=item.kind,
                title=item.title,
                raw_payload=item.content,
                content_hash=content_hash,
                source_url=item.source_url,
                external_id=item.external_id,
                status=CaptureStatus.CAPTURED,
            )
            session.add(capture)
            new_count += 1

        if new_count > 0:
            await session.commit()

        return new_count
