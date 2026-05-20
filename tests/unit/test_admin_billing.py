"""Tests for admin billing endpoints."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import AdminPlanResponse, AdminPlanUpdateRequest, Plan


class TestAdminBillingEndpoints:
    def test_admin_billing_imports(self):
        """Verify billing models can be imported for admin endpoints."""
        from wikimind.models import Plan, Subscription, WebhookEvent

        assert Subscription is not None
        assert WebhookEvent is not None
        assert Plan is not None

    def test_apply_entitlement_importable(self):
        """Verify apply_entitlement is importable."""
        from wikimind.services.billing import apply_entitlement

        assert callable(apply_entitlement)


class TestAdminPlanUpdateModels:
    """Unit tests for plan update request/response Pydantic models."""

    def test_update_request_both_fields(self):
        req = AdminPlanUpdateRequest(llm_model="gpt-4o", llm_provider="openai")
        assert req.llm_model == "gpt-4o"
        assert req.llm_provider == "openai"

    def test_update_request_model_only(self):
        req = AdminPlanUpdateRequest(llm_model="gpt-4o")
        assert req.llm_model == "gpt-4o"
        assert req.llm_provider is None

    def test_update_request_provider_only(self):
        req = AdminPlanUpdateRequest(llm_provider="anthropic")
        assert req.llm_model is None
        assert req.llm_provider == "anthropic"

    def test_update_request_empty_is_valid(self):
        """Both fields None is valid at model level; the endpoint rejects it."""
        req = AdminPlanUpdateRequest()
        assert req.llm_model is None
        assert req.llm_provider is None

    def test_plan_response_shape(self):
        from datetime import datetime

        resp = AdminPlanResponse(
            id="plan-1",
            name="free",
            display_name="Free",
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            is_active=True,
            updated_at=datetime(2026, 1, 1),
        )
        assert resp.name == "free"
        assert resp.llm_model == "gpt-4o-mini"


class TestAdminPlanUpdateEndpoint:
    """Integration tests for PATCH /api/admin/billing/plans/{plan_id}."""

    @pytest.mark.asyncio
    async def test_patch_plan_model(self, client, db_session: AsyncSession):
        """Updating llm_model on a plan returns the updated value."""
        plan = Plan(
            name="test-plan",
            display_name="Test Plan",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={"llm_model": "gpt-4o"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_model"] == "gpt-4o"
        assert data["llm_provider"] == "openai_compatible"

    @pytest.mark.asyncio
    async def test_patch_plan_provider(self, client, db_session: AsyncSession):
        """Updating llm_provider on a plan returns the updated value."""
        plan = Plan(
            name="test-plan-prov",
            display_name="Test Plan Provider",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={"llm_provider": "anthropic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_provider"] == "anthropic"
        assert data["llm_model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_patch_plan_both_fields(self, client, db_session: AsyncSession):
        """Updating both fields at once."""
        plan = Plan(
            name="test-plan-both",
            display_name="Test Both",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={"llm_model": "claude-sonnet-4-20250514", "llm_provider": "anthropic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_model"] == "claude-sonnet-4-20250514"
        assert data["llm_provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_patch_plan_not_found(self, client):
        """Returns 404 for a nonexistent plan."""
        resp = await client.patch(
            "/api/admin/billing/plans/nonexistent-id",
            json={"llm_model": "gpt-4o"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_plan_no_fields(self, client, db_session: AsyncSession):
        """Returns 400 when neither field is provided."""
        plan = Plan(
            name="test-plan-empty",
            display_name="Test Empty",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_patch_plan_invalid_provider(self, client, db_session: AsyncSession):
        """Returns 400 when llm_provider is not a valid Provider enum value."""
        plan = Plan(
            name="test-plan-bad-prov",
            display_name="Test Bad Provider",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={"llm_provider": "not_a_real_provider"},
        )
        assert resp.status_code == 400
        assert "Invalid llm_provider" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_patch_plan_empty_model(self, client, db_session: AsyncSession):
        """Returns 400 when llm_model is an empty or whitespace-only string."""
        plan = Plan(
            name="test-plan-empty-model",
            display_name="Test Empty Model",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        resp = await client.patch(
            f"/api/admin/billing/plans/{plan.id}",
            json={"llm_model": "   "},
        )
        assert resp.status_code == 400
        assert "non-empty" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_list_plans(self, client, db_session: AsyncSession):
        """GET /api/admin/billing/plans returns all plans."""
        plan = Plan(
            name="test-list-plan",
            display_name="Test List",
            price_cents=0,
            llm_provider="openai_compatible",
            llm_model="gpt-4o-mini",
            allowed_exports=["markdown"],
        )
        db_session.add(plan)
        await db_session.commit()

        resp = await client.get("/api/admin/billing/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = [p["name"] for p in data]
        assert "test-list-plan" in names
