"""Shared test fixtures — hermetic by default (in-memory SQLite, no network)."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import keyring
import pytest
from httpx import ASGITransport, AsyncClient
from keyring.backend import KeyringBackend
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.main import app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical test-user constant & fixture
# ---------------------------------------------------------------------------

TEST_USER_ID = "test-user"


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
    yield data_dir
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_fts_ready() -> Iterator[None]:
    """Reset the FTS readiness flag between tests.

    The ``_fts_ready`` module flag is set by ``create_fts_table`` during
    ``init_db`` and stays True for the lifetime of the process.  Tests that
    use a fresh in-memory SQLite (without FTS5 table) would hit
    ``OperationalError`` if a prior test left the flag True.  Resetting it
    before every test ensures FTS write helpers no-op unless the current
    test explicitly creates the FTS table.
    """
    import wikimind.services.search as _search_mod  # noqa: PLC0415

    _search_mod._fts_ready = False
    yield
    _search_mod._fts_ready = False


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
            await session.commit()

    app.dependency_overrides[get_session] = _override_session

    # Patch get_session_factory in every module that imported it via
    # `from wikimind.database import get_session_factory`.  Each such import
    # creates an independent name binding, so we must patch each site for
    # the override to take effect on direct callers (e.g. _get_preference).
    _factory_fn = lambda: factory  # noqa: E731
    _patch_targets = [
        "wikimind.database.get_session_factory",
        "wikimind.api.routes.settings.get_session_factory",
        "wikimind.api.routes.query.get_session_factory",
        "wikimind.engine.compiler.get_session_factory",
        "wikimind.engine.llm_router.get_session_factory",
    ]
    with contextlib.ExitStack() as stack:
        for target in _patch_targets:
            stack.enter_context(patch(target, _factory_fn))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Optional vector-store fixture — skipped automatically when chromadb is
# not installed (it lives in the [search] extra).
# ---------------------------------------------------------------------------


@pytest.fixture
def chroma_client(tmp_path: Path) -> Any:
    """Ephemeral ChromaDB client backed by a tmp directory."""
    chromadb = pytest.importorskip("chromadb")
    return chromadb.PersistentClient(path=str(tmp_path / "chroma"))
