"""Shared test fixtures — hermetic by default (in-memory SQLite, no network)."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from typing import Any

import keyring
import pytest
from httpx import ASGITransport, AsyncClient
from keyring.backend import KeyringBackend
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import wikimind.database as _db_mod
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.main import app
from wikimind.storage import get_raw_storage, get_wiki_storage

# ---------------------------------------------------------------------------
# Hermetic environment — runs once per session, applied before any test
# constructs Settings or touches keyring.
# ---------------------------------------------------------------------------


class _InMemoryKeyring(KeyringBackend):
    """Keyring backend that never touches the OS keychain."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


@pytest.fixture(autouse=True, scope="session")
def _hermetic_env() -> Iterator[None]:
    """Force a clean, network-free environment for the entire test session."""
    keyring.set_keyring(_InMemoryKeyring())
    scrubbed = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "WIKIMIND_ANTHROPIC_API_KEY",
        "WIKIMIND_OPENAI_API_KEY",
        "WIKIMIND_GOOGLE_API_KEY",
        "WIKIMIND_AUTH__ENABLED",
        "WIKIMIND_AUTH__JWT_SECRET_KEY",
        "WIKIMIND_AUTH__GOOGLE_CLIENT_ID",
        "WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET",
        "WIKIMIND_AUTH__GITHUB_CLIENT_ID",
        "WIKIMIND_AUTH__GITHUB_CLIENT_SECRET",
    ]
    saved = {k: os.environ.pop(k, None) for k in scrubbed}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point WIKIMIND_DATA_DIR at a tmp dir for every test (filesystem isolation)."""
    data_dir = tmp_path / "wikimind"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(data_dir))
    # Force auth disabled — .env may have WIKIMIND_AUTH__ENABLED=true for local dev
    monkeypatch.setenv("WIKIMIND_AUTH__ENABLED", "false")
    get_settings.cache_clear()
    # Clear storage singletons so they pick up the new data_dir
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()
    yield data_dir
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """In-memory SQLite engine — created and destroyed per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Async database session backed by in-memory SQLite."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(async_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client wired to in-memory database.

    Both the FastAPI dependency (``get_session``) and the module-level
    ``get_session_factory`` singleton are redirected to the same in-memory
    engine so that route handlers that call ``get_session_factory()`` directly
    (rather than through FastAPI's DI) also use the hermetic test DB.
    """
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    # Patch the module-level session-factory singleton so direct callers
    # (e.g. _get_preference, _set_preference) also use the test DB.
    original_factory = _db_mod._session_factory
    _db_mod._session_factory = factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    _db_mod._session_factory = original_factory


# ---------------------------------------------------------------------------
# Optional vector-store fixture — skipped automatically when chromadb is
# not installed (it lives in the [search] extra).
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_client(tmp_path: Path) -> Any:
    """Ephemeral ChromaDB client backed by a tmp directory."""
    chromadb = pytest.importorskip("chromadb")
    return chromadb.PersistentClient(path=str(tmp_path / "chroma"))
