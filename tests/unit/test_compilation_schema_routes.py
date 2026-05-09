"""Tests for API routes: /api/compilation-schemas (issue #420)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_create_schema(client: AsyncClient):
    resp = await client.post(
        "/api/compilation-schemas",
        json={"name": "research", "style": "academic, formal"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "research"
    assert data["style"] == "academic, formal"
    assert data["is_active"] is False


async def test_list_schemas_empty(client: AsyncClient):
    resp = await client.get("/api/compilation-schemas")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_schemas(client: AsyncClient):
    await client.post("/api/compilation-schemas", json={"name": "a"})
    await client.post("/api/compilation-schemas", json={"name": "b"})
    resp = await client.get("/api/compilation-schemas")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_schema(client: AsyncClient):
    create_resp = await client.post("/api/compilation-schemas", json={"name": "fetch-me"})
    schema_id = create_resp.json()["id"]
    resp = await client.get(f"/api/compilation-schemas/{schema_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "fetch-me"


async def test_get_schema_not_found(client: AsyncClient):
    resp = await client.get("/api/compilation-schemas/nonexistent")
    assert resp.status_code == 404


async def test_update_schema(client: AsyncClient):
    create_resp = await client.post("/api/compilation-schemas", json={"name": "original"})
    schema_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/compilation-schemas/{schema_id}",
        json={"name": "updated", "style": "casual"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"
    assert resp.json()["style"] == "casual"


async def test_update_schema_not_found(client: AsyncClient):
    resp = await client.patch(
        "/api/compilation-schemas/nonexistent",
        json={"name": "x"},
    )
    assert resp.status_code == 404


async def test_delete_schema(client: AsyncClient):
    create_resp = await client.post("/api/compilation-schemas", json={"name": "del-me"})
    schema_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/compilation-schemas/{schema_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get(f"/api/compilation-schemas/{schema_id}")
    assert resp.status_code == 404


async def test_delete_schema_not_found(client: AsyncClient):
    resp = await client.delete("/api/compilation-schemas/nonexistent")
    assert resp.status_code == 404


async def test_create_with_all_fields(client: AsyncClient):
    resp = await client.post(
        "/api/compilation-schemas",
        json={
            "name": "full",
            "description": "Full schema",
            "is_active": True,
            "article_max_length": 2000,
            "required_sections": ["summary", "key_claims"],
            "style": "concise",
            "focus": "practical applications",
            "concept_max_depth": 3,
            "concept_naming": "lowercase",
            "extraction_always_note": ["methodology"],
            "extraction_ignore": ["author bios"],
            "custom_directives": "No hedging",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["article_max_length"] == 2000
    assert data["required_sections"] == ["summary", "key_claims"]
    assert data["extraction_always_note"] == ["methodology"]
    assert data["extraction_ignore"] == ["author bios"]
    assert data["is_active"] is True


async def test_only_one_active_via_api(client: AsyncClient):
    """Creating an active schema deactivates others."""
    resp_a = await client.post(
        "/api/compilation-schemas",
        json={"name": "a", "is_active": True},
    )
    resp_b = await client.post(
        "/api/compilation-schemas",
        json={"name": "b", "is_active": True},
    )
    a_id = resp_a.json()["id"]

    # Verify a is now inactive
    resp = await client.get(f"/api/compilation-schemas/{a_id}")
    assert resp.json()["is_active"] is False
    assert resp_b.json()["is_active"] is True
