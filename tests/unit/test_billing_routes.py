"""Tests for billing API endpoints."""

import hashlib
import hmac

from wikimind.services.billing import verify_webhook_signature


class TestWebhookSignature:
    def test_valid_signature(self):
        """Valid HMAC-SHA256 signature passes verification."""
        secret = "test-secret"
        payload = b'{"test": "data"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        """Wrong signature fails verification."""
        assert verify_webhook_signature(b"data", "wrong-sig", "secret") is False

    def test_empty_signature(self):
        """Empty signature fails verification."""
        assert verify_webhook_signature(b"data", "", "secret") is False

    def test_different_payload(self):
        """Signature for different payload fails verification."""
        secret = "test-secret"
        payload_a = b'{"event": "subscription_created"}'
        payload_b = b'{"event": "subscription_expired"}'
        sig_a = hmac.new(secret.encode(), payload_a, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(payload_b, sig_a, secret) is False

    def test_different_secret(self):
        """Signature with different secret fails verification."""
        payload = b'{"test": "data"}'
        sig = hmac.new(b"real-secret", payload, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(payload, sig, "wrong-secret") is False
