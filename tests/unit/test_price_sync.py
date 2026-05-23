"""Tests for Lemon Squeezy price sync — webhook handlers and reconciliation."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from wikimind.models import Plan
from wikimind.services.billing import (
    handle_product_updated,
    handle_variant_updated,
    reconcile_prices,
)


@pytest.fixture
def pro_plan() -> Plan:
    """A Pro plan with a Lemon Squeezy variant ID."""
    return Plan(
        id="plan-pro",
        name="pro",
        display_name="Pro",
        price_cents=999,
        billing_interval="month",
        allowed_exports=["markdown", "pdf"],
        lemon_squeezy_variant_id="variant-100",
        is_active=True,
        sort_order=1,
    )


@pytest.fixture
def team_plan() -> Plan:
    """A Team plan with a Lemon Squeezy variant ID."""
    return Plan(
        id="plan-team",
        name="team",
        display_name="Team",
        price_cents=2999,
        billing_interval="month",
        allowed_exports=["markdown", "pdf"],
        lemon_squeezy_variant_id="variant-200",
        is_active=True,
        sort_order=2,
    )


def _variant_payload(variant_id: str, price: int) -> dict:
    """Build a Lemon Squeezy variant_updated webhook payload."""
    return {
        "meta": {"event_name": "variant_updated", "webhook_id": "wh-123"},
        "data": {
            "id": variant_id,
            "type": "variants",
            "attributes": {"price": price, "name": "Default"},
        },
    }


def _product_payload(product_id: str) -> dict:
    """Build a Lemon Squeezy product_updated webhook payload."""
    return {
        "meta": {"event_name": "product_updated", "webhook_id": "wh-456"},
        "data": {
            "id": product_id,
            "type": "products",
            "attributes": {"name": "WikiMind Pro"},
        },
    }


# ---------------------------------------------------------------------------
# handle_variant_updated
# ---------------------------------------------------------------------------


class TestHandleVariantUpdated:
    @pytest.mark.anyio
    async def test_updates_price(self, db_session, pro_plan):
        """Price is updated when variant_updated webhook arrives."""
        db_session.add(pro_plan)
        await db_session.commit()

        payload = _variant_payload("variant-100", 1299)
        result = await handle_variant_updated(db_session, payload)

        assert result is True
        await db_session.flush()
        row = (await db_session.exec(select(Plan).where(Plan.id == "plan-pro"))).one()
        assert row.price_cents == 1299

    @pytest.mark.anyio
    async def test_no_change_when_price_same(self, db_session, pro_plan):
        """Returns False when the price hasn't changed."""
        db_session.add(pro_plan)
        await db_session.commit()

        payload = _variant_payload("variant-100", 999)
        result = await handle_variant_updated(db_session, payload)

        assert result is False
        row = (await db_session.exec(select(Plan).where(Plan.id == "plan-pro"))).one()
        assert row.price_cents == 999

    @pytest.mark.anyio
    async def test_unknown_variant_ignored(self, db_session, pro_plan):
        """Returns False for an unrecognised variant ID."""
        db_session.add(pro_plan)
        await db_session.commit()

        payload = _variant_payload("variant-unknown", 1500)
        result = await handle_variant_updated(db_session, payload)

        assert result is False

    @pytest.mark.anyio
    async def test_missing_price_ignored(self, db_session, pro_plan):
        """Returns False when the payload has no price field."""
        db_session.add(pro_plan)
        await db_session.commit()

        payload = {
            "data": {
                "id": "variant-100",
                "attributes": {},
            },
        }
        result = await handle_variant_updated(db_session, payload)

        assert result is False

    @pytest.mark.anyio
    async def test_missing_variant_id_ignored(self, db_session):
        """Returns False when the payload has no variant ID."""
        payload = {"data": {"attributes": {"price": 1000}}}
        result = await handle_variant_updated(db_session, payload)

        assert result is False


# ---------------------------------------------------------------------------
# handle_product_updated
# ---------------------------------------------------------------------------


class TestHandleProductUpdated:
    @pytest.mark.anyio
    async def test_updates_matching_variant_prices(self, db_session, pro_plan):
        """Fetches variants for the product and updates matching plan prices."""
        db_session.add(pro_plan)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.list_variants.return_value = [
            {"id": "variant-100", "attributes": {"price": 1499}},
        ]

        payload = _product_payload("product-1")
        with patch(
            "wikimind.services.billing.LemonSqueezyClient",
            return_value=mock_client,
        ):
            count = await handle_product_updated(db_session, payload)

        assert count == 1
        await db_session.flush()
        row = (await db_session.exec(select(Plan).where(Plan.id == "plan-pro"))).one()
        assert row.price_cents == 1499

    @pytest.mark.anyio
    async def test_skips_unchanged_prices(self, db_session, pro_plan):
        """No updates when remote price matches local price."""
        db_session.add(pro_plan)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.list_variants.return_value = [
            {"id": "variant-100", "attributes": {"price": 999}},
        ]

        payload = _product_payload("product-1")
        with patch(
            "wikimind.services.billing.LemonSqueezyClient",
            return_value=mock_client,
        ):
            count = await handle_product_updated(db_session, payload)

        assert count == 0

    @pytest.mark.anyio
    async def test_missing_product_id(self, db_session):
        """Returns 0 when product ID is missing from the payload."""
        payload = {"data": {"attributes": {"name": "Test"}}}
        count = await handle_product_updated(db_session, payload)

        assert count == 0

    @pytest.mark.anyio
    async def test_api_error_returns_zero(self, db_session, pro_plan):
        """Returns 0 when the Lemon Squeezy API call fails."""
        db_session.add(pro_plan)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.list_variants.side_effect = RuntimeError("API down")

        payload = _product_payload("product-1")
        with patch(
            "wikimind.services.billing.LemonSqueezyClient",
            return_value=mock_client,
        ):
            count = await handle_product_updated(db_session, payload)

        assert count == 0


# ---------------------------------------------------------------------------
# reconcile_prices
# ---------------------------------------------------------------------------


class TestReconcilePrices:
    @pytest.mark.anyio
    async def test_corrects_drifted_price(self, db_session, pro_plan):
        """Detects and corrects a price that has drifted from Lemon Squeezy."""
        db_session.add(pro_plan)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.get_variant.return_value = {
            "attributes": {"price": 1499},
        }

        with (
            patch(
                "wikimind.services.billing.LemonSqueezyClient",
                return_value=mock_client,
            ),
            patch(
                "wikimind.services.billing.get_settings",
            ) as mock_settings,
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "key"
            corrected = await reconcile_prices(db_session)

        assert corrected == 1
        row = (await db_session.exec(select(Plan).where(Plan.id == "plan-pro"))).one()
        assert row.price_cents == 1499

    @pytest.mark.anyio
    async def test_no_change_when_prices_match(self, db_session, pro_plan):
        """Returns 0 when local prices already match remote."""
        db_session.add(pro_plan)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.get_variant.return_value = {
            "attributes": {"price": 999},
        }

        with (
            patch(
                "wikimind.services.billing.LemonSqueezyClient",
                return_value=mock_client,
            ),
            patch(
                "wikimind.services.billing.get_settings",
            ) as mock_settings,
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "key"
            corrected = await reconcile_prices(db_session)

        assert corrected == 0

    @pytest.mark.anyio
    async def test_skips_when_billing_disabled(self, db_session, pro_plan):
        """Returns 0 immediately when billing is disabled."""
        db_session.add(pro_plan)
        await db_session.commit()

        with patch(
            "wikimind.services.billing.get_settings",
        ) as mock_settings:
            mock_settings.return_value.billing_enabled = False
            corrected = await reconcile_prices(db_session)

        assert corrected == 0

    @pytest.mark.anyio
    async def test_skips_plans_without_variant_id(self, db_session):
        """Plans without lemon_squeezy_variant_id are not checked."""
        free_plan = Plan(
            id="plan-free",
            name="free",
            display_name="Free",
            price_cents=0,
            allowed_exports=["markdown"],
            lemon_squeezy_variant_id=None,
            is_active=True,
            sort_order=0,
        )
        db_session.add(free_plan)
        await db_session.commit()

        with patch(
            "wikimind.services.billing.get_settings",
        ) as mock_settings:
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "key"
            corrected = await reconcile_prices(db_session)

        assert corrected == 0

    @pytest.mark.anyio
    async def test_continues_on_api_error(self, db_session, pro_plan, team_plan):
        """One variant API failure doesn't block other plans."""
        db_session.add(pro_plan)
        db_session.add(team_plan)
        await db_session.commit()

        async def get_variant_side_effect(variant_id):
            if variant_id == "variant-100":
                raise RuntimeError("timeout")
            return {"attributes": {"price": 3999}}

        mock_client = AsyncMock()
        mock_client.get_variant = AsyncMock(side_effect=get_variant_side_effect)

        with (
            patch(
                "wikimind.services.billing.LemonSqueezyClient",
                return_value=mock_client,
            ),
            patch(
                "wikimind.services.billing.get_settings",
            ) as mock_settings,
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "key"
            corrected = await reconcile_prices(db_session)

        # Only team plan was corrected; pro plan errored
        assert corrected == 1
        row_team = (await db_session.exec(select(Plan).where(Plan.id == "plan-team"))).one()
        assert row_team.price_cents == 3999
        row_pro = (await db_session.exec(select(Plan).where(Plan.id == "plan-pro"))).one()
        assert row_pro.price_cents == 999  # unchanged
