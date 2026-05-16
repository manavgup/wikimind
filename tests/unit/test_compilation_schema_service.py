"""Tests for services/compilation_schema.py — compilation schema CRUD (DB-level)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.services.compilation_schema import CompilationSchemaService
from wikimind.services.factories import get_compilation_schema_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def test_singleton():
    get_compilation_schema_service.cache_clear()
    assert get_compilation_schema_service() is get_compilation_schema_service()
    get_compilation_schema_service.cache_clear()


async def test_create_schema(db_session: AsyncSession):
    s = CompilationSchemaService()
    schema = await s.create_schema(
        db_session,
        TEST_USER_ID,
        name="technical",
        style="concise, technical",
    )
    assert schema.name == "technical"
    assert schema.style == "concise, technical"
    assert schema.id is not None
    assert schema.is_active is False


async def test_create_schema_with_all_fields(db_session: AsyncSession):
    s = CompilationSchemaService()
    schema = await s.create_schema(
        db_session,
        TEST_USER_ID,
        name="full",
        description="Full schema",
        is_active=True,
        article_max_length=2000,
        required_sections=["summary", "key_claims"],
        style="concise",
        focus="practical applications",
        concept_max_depth=3,
        concept_naming="lowercase",
        extraction_always_note=["methodology", "sample size"],
        extraction_ignore=["author bios"],
        custom_directives="No hedging language",
    )
    assert schema.article_max_length == 2000
    assert schema.required_sections == ["summary", "key_claims"]
    assert schema.extraction_always_note == ["methodology", "sample size"]
    assert schema.extraction_ignore == ["author bios"]
    assert schema.custom_directives == "No hedging language"
    assert schema.is_active is True


async def test_list_schemas_empty(db_session: AsyncSession):
    assert await CompilationSchemaService().list_schemas(db_session, TEST_USER_ID) == []


async def test_list_schemas(db_session: AsyncSession):
    s = CompilationSchemaService()
    await s.create_schema(db_session, TEST_USER_ID, name="a")
    await s.create_schema(db_session, TEST_USER_ID, name="b")
    schemas = await s.list_schemas(db_session, TEST_USER_ID)
    assert len(schemas) == 2
    assert schemas[0].name == "a"
    assert schemas[1].name == "b"


async def test_get_schema(db_session: AsyncSession):
    s = CompilationSchemaService()
    created = await s.create_schema(db_session, TEST_USER_ID, name="test")
    fetched = await s.get_schema(db_session, created.id, TEST_USER_ID)
    assert fetched.id == created.id
    assert fetched.name == "test"


async def test_get_schema_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await CompilationSchemaService().get_schema(db_session, "bad-id", TEST_USER_ID)


async def test_update_schema(db_session: AsyncSession):
    s = CompilationSchemaService()
    created = await s.create_schema(db_session, TEST_USER_ID, name="original")
    updated = await s.update_schema(
        db_session,
        created.id,
        TEST_USER_ID,
        name="updated",
        style="formal",
    )
    assert updated.name == "updated"
    assert updated.style == "formal"


async def test_update_schema_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await CompilationSchemaService().update_schema(db_session, "bad-id", TEST_USER_ID, name="x")


async def test_delete_schema(db_session: AsyncSession):
    s = CompilationSchemaService()
    created = await s.create_schema(db_session, TEST_USER_ID, name="del")
    await s.delete_schema(db_session, created.id, TEST_USER_ID)
    assert len(await s.list_schemas(db_session, TEST_USER_ID)) == 0


async def test_delete_schema_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await CompilationSchemaService().delete_schema(db_session, "bad-id", TEST_USER_ID)


async def test_only_one_active(db_session: AsyncSession):
    """Activating a schema deactivates all others for the same user."""
    s = CompilationSchemaService()
    a = await s.create_schema(db_session, TEST_USER_ID, name="a", is_active=True)
    b = await s.create_schema(db_session, TEST_USER_ID, name="b", is_active=True)
    # After creating b as active, a should be deactivated
    refreshed_a = await s.get_schema(db_session, a.id, TEST_USER_ID)
    assert refreshed_a.is_active is False
    assert b.is_active is True


async def test_activate_via_update(db_session: AsyncSession):
    """Updating is_active=True deactivates others."""
    s = CompilationSchemaService()
    a = await s.create_schema(db_session, TEST_USER_ID, name="a", is_active=True)
    b = await s.create_schema(db_session, TEST_USER_ID, name="b")
    await s.update_schema(db_session, b.id, TEST_USER_ID, is_active=True)
    refreshed_a = await s.get_schema(db_session, a.id, TEST_USER_ID)
    assert refreshed_a.is_active is False


async def test_get_active_schema(db_session: AsyncSession):
    s = CompilationSchemaService()
    await s.create_schema(db_session, TEST_USER_ID, name="inactive")
    await s.create_schema(db_session, TEST_USER_ID, name="active", is_active=True)
    active = await s.get_active_schema(db_session, TEST_USER_ID)
    assert active is not None
    assert active.name == "active"


async def test_get_active_schema_none(db_session: AsyncSession):
    s = CompilationSchemaService()
    await s.create_schema(db_session, TEST_USER_ID, name="inactive")
    active = await s.get_active_schema(db_session, TEST_USER_ID)
    assert active is None


async def test_user_isolation(db_session: AsyncSession):
    """Schemas from one user are not visible to another."""
    s = CompilationSchemaService()
    await s.create_schema(db_session, "user-a", name="schema-a")
    await s.create_schema(db_session, "user-b", name="schema-b")
    assert len(await s.list_schemas(db_session, "user-a")) == 1
    assert len(await s.list_schemas(db_session, "user-b")) == 1
