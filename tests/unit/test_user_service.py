"""Tests for services/user.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch as mock_patch

import pytest

from tests.conftest import TEST_JWT_SECRET
from wikimind.api.services import get_user_service
from wikimind.config import AuthConfig
from wikimind.errors import NotFoundError
from wikimind.models import Article, Conversation, OAuthUserInfo, PageType, Source, SourceType, User
from wikimind.services.user import UserService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def _settings(jwt_secret=TEST_JWT_SECRET, ttl=600):
    s = MagicMock()
    s.auth = AuthConfig(jwt_secret_key=jwt_secret, magic_link_ttl_seconds=ttl)
    return s


def test_singleton():
    get_user_service.cache_clear()
    assert get_user_service() is get_user_service()
    get_user_service.cache_clear()


def test_magic_link_roundtrip():
    s = UserService()
    settings = _settings()
    token = s.create_magic_link_token("u@ex.com", settings)
    assert s.verify_magic_link_token(token, settings) == "u@ex.com"


def test_magic_link_invalid():
    with pytest.raises(ValueError):
        UserService().verify_magic_link_token("bad!!!", _settings())


def test_magic_link_tampered():
    s = UserService()
    token = s.create_magic_link_token("u@ex.com", _settings())
    with pytest.raises(ValueError, match="signature"):
        s.verify_magic_link_token(token, _settings(jwt_secret="wrong-key-wrong-key-wrong-key32"))


def test_create_jwt():
    s = UserService()
    settings = _settings()
    user = User(id="u1", email="t@ex.com", name="T", auth_provider="google", auth_provider_id="g1")
    token = s.create_jwt(user, settings)
    assert len(token) > 0


async def test_get_or_create_existing(db_session: AsyncSession):
    db_session.add(User(id="eu", email="eu@ex.com", name="E", auth_provider="jwt", auth_provider_id="eu"))
    await db_session.commit()
    r = await UserService().get_or_create(db_session, "eu")
    assert r.id == "eu"


async def test_get_or_create_new(db_session: AsyncSession):
    r = await UserService().get_or_create(db_session, "nu", email="nu@ex.com")
    assert r.email == "nu@ex.com"


async def test_get_or_create_by_email_new(db_session: AsyncSession):
    r = await UserService().get_or_create_by_email(db_session, "new@ex.com")
    assert r.auth_provider == "magic_link"


async def test_exchange_google_token():
    s = UserService()
    settings = _settings()
    settings.auth.google_client_id = "gid"
    settings.auth.google_client_secret = "gs"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"access_token": "at", "token_type": "Bearer"})
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=False)
    mc.post = AsyncMock(return_value=mock_resp)
    with mock_patch("wikimind.services.user.httpx.AsyncClient", return_value=mc):
        r = await s.exchange_google_token("code", settings, "http://cb")
    assert r.access_token == "at"


async def test_exchange_github_token():
    s = UserService()
    settings = _settings()
    settings.auth.github_client_id = "ghid"
    settings.auth.github_client_secret = "ghs"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"access_token": "ghat", "token_type": "bearer"})
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=False)
    mc.post = AsyncMock(return_value=mock_resp)
    with mock_patch("wikimind.services.user.httpx.AsyncClient", return_value=mc):
        r = await s.exchange_github_token("code", settings)
    assert r.access_token == "ghat"


async def test_fetch_google_userinfo():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"id": "g1", "email": "u@g.com", "name": "U"})
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=False)
    mc.get = AsyncMock(return_value=mock_resp)
    with mock_patch("wikimind.services.user.httpx.AsyncClient", return_value=mc):
        r = await UserService().fetch_google_userinfo("token")
    assert r.email == "u@g.com"


async def test_fetch_github_userinfo_no_email():
    ur = MagicMock()
    ur.raise_for_status = MagicMock()
    ur.json = MagicMock(return_value={"id": 1, "email": None, "name": "N", "login": "l"})
    er = MagicMock()
    er.raise_for_status = MagicMock()
    er.json = MagicMock(return_value=[{"email": "p@g.com", "primary": True, "verified": True}])
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__ = AsyncMock(return_value=False)
    mc.get = AsyncMock(side_effect=[ur, er])
    with mock_patch("wikimind.services.user.httpx.AsyncClient", return_value=mc):
        r = await UserService().fetch_github_userinfo("token")
    assert r.email == "p@g.com"


async def test_upsert_google_user(db_session: AsyncSession):
    info = OAuthUserInfo(id="g1", email="g@ex.com", name="G")
    r = await UserService().upsert_oauth_user(db_session, "google", info)
    assert r.email == "g@ex.com"


async def test_upsert_github_user(db_session: AsyncSession):
    info = OAuthUserInfo(id="gh1", email="gh@ex.com", name=None, login="ghuser")
    r = await UserService().upsert_oauth_user(db_session, "github", info)
    assert r.name == "ghuser"


async def test_delete_account_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await UserService().delete_account(db_session, "bad")


async def test_delete_account_empty(db_session: AsyncSession):
    u = User(email="del@ex.com", name="D", auth_provider="jwt", auth_provider_id="d")
    db_session.add(u)
    await db_session.commit()
    await UserService().delete_account(db_session, u.id)
    assert await db_session.get(User, u.id) is None


async def test_delete_account_with_data(db_session: AsyncSession):
    u = User(email="full@ex.com", name="F", auth_provider="jwt", auth_provider_id="f")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    db_session.add(Source(source_type=SourceType.TEXT, title="s", user_id=u.id))
    db_session.add(Article(slug="da", title="DA", file_path="wiki/da.md", page_type=PageType.SOURCE, user_id=u.id))
    db_session.add(Conversation(user_id=u.id, title="C"))
    await db_session.commit()
    await UserService().delete_account(db_session, u.id)
    assert await db_session.get(User, u.id) is None
