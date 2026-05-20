"""Tests for admin billing endpoints."""


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
