"""Shared test fixtures — hermetic by default (in-memory SQLite, no network)."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

# Set development mode before any wikimind imports. Module-level code in
# worker.py calls get_settings() at import time, which would fail the
# production jwt_secret_key validation if WIKIMIND_ENV is not set.
os.environ.setdefault("WIKIMIND_ENV", "development")
# Force self-hosted mode in tests — billing requires Postgres plan tables
# that don't exist in the in-memory SQLite test DB.
os.environ["WIKIMIND_DEPLOYMENT_MODE"] = "self_hosted"

import keyring
import pytest
from httpx import ASGITransport, AsyncClient
from keyring.backend import KeyringBackend
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

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
TEST_JWT_SECRET = "test-secret-key-for-unit-tests!!"  # pragma: allowlist secret  # 32 bytes


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
        "WIKIMIND_AUTH__JWT_SECRET_KEY",
        "WIKIMIND_AUTH__GOOGLE_CLIENT_ID",
        "WIKIMIND_AUTH__GOOGLE_CLIENT_SECRET",
        "WIKIMIND_AUTH__GITHUB_CLIENT_ID",
        "WIKIMIND_AUTH__GITHUB_CLIENT_SECRET",
        "WIKIMIND_AUTH__DEV_AUTO_AUTH",
        "WIKIMIND_AUTH__DEV_USER_EMAIL",
    ]
    saved = {k: os.environ.pop(k, None) for k in scrubbed}
    # Set dev mode at session scope so that any early get_settings() calls
    # (e.g. during module import via worker.py) don't fail the production
    # jwt_secret_key requirement.
    saved_env = os.environ.get("WIKIMIND_ENV")
    os.environ["WIKIMIND_ENV"] = "development"
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        if saved_env is not None:
            os.environ["WIKIMIND_ENV"] = saved_env
        else:
            os.environ.pop("WIKIMIND_ENV", None)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point WIKIMIND_DATA_DIR at a tmp dir for every test (filesystem isolation).

    Tests run in development mode with dev_auto_auth disabled by default.
    The ``client`` fixture patches the auth middleware to inject TEST_USER_ID
    instead, giving tests a deterministic, database-independent user identity.
    """
    data_dir = tmp_path / "wikimind"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(data_dir))
    # Development mode — so jwt_secret_key is not required and dev_auto_auth works
    monkeypatch.setenv("WIKIMIND_ENV", "development")
    monkeypatch.setenv("WIKIMIND_AUTH__DEV_AUTO_AUTH", "true")
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
    import wikimind.services.search as _search_mod

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
def session_factory(async_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Reusable async session factory backed by the in-memory test engine.

    Prefer this fixture whenever a test (or its helper) needs to open
    multiple independent sessions against the same test database — e.g.
    for seeding data before exercising a route, or for verifying state
    after a service call.
    """
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Async database session backed by in-memory SQLite."""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        # Explicitly close the session connection before the event loop ends,
        # giving aiosqlite's background thread time to finish. Without this,
        # the thread tries to post results to an already-closed loop.
        await session.close()


@pytest.fixture
async def client(async_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client wired to in-memory database.

    Both the FastAPI dependency (``get_session``) and the module-level
    ``get_session_factory`` singleton are redirected to the same in-memory
    engine so that route handlers that call ``get_session_factory()`` directly
    (rather than through FastAPI's DI) also use the hermetic test DB.

    Authentication is handled via ``dev_auto_auth=True`` — the middleware
    auto-authenticates as a dev user whose ID matches ``TEST_USER_ID``.
    ``get_dev_user_id`` is patched to return ``TEST_USER_ID``.
    """
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    # Seed the test user row so FK constraints are satisfied.
    from wikimind.models import User

    async with factory() as seed_session:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = (
            sqlite_insert(User)
            .values(
                id=TEST_USER_ID,
                email="test@wikimind.local",
                name="Test User",
                auth_provider="test",
                auth_provider_id=TEST_USER_ID,
                is_admin=True,
            )
            .on_conflict_do_nothing()
        )
        await seed_session.execute(stmt)
        await seed_session.commit()

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

    # Patch get_dev_user_id to return TEST_USER_ID so the middleware's
    # dev-auto-auth path uses our test user, and reset the cached value.
    from wikimind.middleware.auth import reset_dev_user_cache

    reset_dev_user_cache()

    async def _mock_get_dev_user_id() -> str:
        return TEST_USER_ID

    with contextlib.ExitStack() as stack:
        for target in _patch_targets:
            stack.enter_context(patch(target, _factory_fn))
        # Patch get_dev_user_id in the database module — the middleware
        # imports it lazily via `from wikimind.database import get_dev_user_id`.
        stack.enter_context(patch("wikimind.database.get_dev_user_id", _mock_get_dev_user_id))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    reset_dev_user_cache()
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
