"""Tests for outbound webhook URL validation.

Webhook targets are fetched by the server, so an unvalidated URL turns the
delivery worker into a proxy for anything reachable from inside the network.
The cases below are the ones that matter: cloud metadata, loopback, private
ranges, non-HTTP schemes, and a hostname that resolves somewhere private.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def guard():
    import url_guard

    # Each test states its own policy; inheriting the ambient env would make
    # results depend on the shell.
    with patch.object(url_guard, "ALLOW_PRIVATE", False):
        yield url_guard


class TestBlockedTargets:
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:8000/hook",
            "http://localhost:8000/hook",  # resolves to loopback
            "http://10.0.0.5/hook",
            "http://192.168.1.10/hook",
            "http://172.16.0.1/hook",
            "http://[::1]/hook",
            "http://0.0.0.0/hook",
        ],
    )
    def test_private_and_reserved_addresses_are_refused(self, guard, url):
        with pytest.raises(guard.UnsafeWebhookURL):
            guard.validate_webhook_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.com/",
            "ftp://example.com/x",
            "redis://127.0.0.1:6379",
        ],
    )
    def test_non_http_schemes_are_refused(self, guard, url):
        with pytest.raises(guard.UnsafeWebhookURL, match="http"):
            guard.validate_webhook_url(url)

    def test_url_without_host_is_refused(self, guard):
        with pytest.raises(guard.UnsafeWebhookURL):
            guard.validate_webhook_url("http:///nohost")

    def test_hostname_resolving_to_private_address_is_refused(self, guard):
        """DNS rebinding: a public-looking name pointing somewhere internal."""
        with patch.object(guard, "resolve_addresses", return_value=["10.1.2.3"]):
            with pytest.raises(guard.UnsafeWebhookURL, match="10.1.2.3"):
                guard.validate_webhook_url("https://sneaky.example.com/hook")

    def test_one_private_address_among_several_is_enough_to_refuse(self, guard):
        with patch.object(
            guard, "resolve_addresses", return_value=["93.184.216.34", "127.0.0.1"]
        ):
            with pytest.raises(guard.UnsafeWebhookURL):
                guard.validate_webhook_url("https://mixed.example.com/hook")


class TestAllowedTargets:
    def test_public_address_is_allowed(self, guard):
        guard.validate_webhook_url("https://93.184.216.34/hook")

    def test_public_hostname_is_allowed(self, guard):
        with patch.object(guard, "resolve_addresses", return_value=["93.184.216.34"]):
            guard.validate_webhook_url("https://example.com/hook")

    def test_resolve_false_skips_the_dns_lookup(self, guard):
        """Callers that cannot afford a lookup still get the shape checks."""
        with patch.object(guard, "resolve_addresses") as resolver:
            guard.validate_webhook_url("https://example.com/hook", resolve=False)
        resolver.assert_not_called()

    def test_literal_ip_is_checked_without_dns(self, guard):
        """A resolver failure must not become a way past the guard."""
        with patch.object(guard, "resolve_addresses", side_effect=AssertionError):
            with pytest.raises(guard.UnsafeWebhookURL):
                guard.validate_webhook_url("http://127.0.0.1/hook")


class TestOptOut:
    def test_private_targets_allowed_when_explicitly_enabled(self):
        """Posting to another container on the same Docker network is normal."""
        import url_guard

        with patch.object(url_guard, "ALLOW_PRIVATE", True):
            url_guard.validate_webhook_url("http://mem0-worker:9000/hook")
            url_guard.validate_webhook_url("http://127.0.0.1:8000/hook")

    def test_scheme_check_still_applies_when_private_is_allowed(self):
        import url_guard

        with patch.object(url_guard, "ALLOW_PRIVATE", True):
            with pytest.raises(url_guard.UnsafeWebhookURL):
                url_guard.validate_webhook_url("file:///etc/passwd")


class TestDeliveryIntegration:
    def test_blocked_delivery_is_failed_without_retry(self):
        """A blocked target cannot become allowed by retrying, so stop trying."""
        import feature_services
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        delivery = SimpleNamespace(
            id="d1",
            event_type="webhook.test",
            payload={"event": "webhook.test", "data": {}},
            attempts=0,
            last_attempt_at=None,
            status="pending",
            response_status=None,
            response_body="",
            next_attempt_at=None,
        )
        endpoint = SimpleNamespace(
            url="http://169.254.169.254/", secret="s", channel="generic"
        )
        db = MagicMock()

        with patch.object(feature_services, "urllib") as net:
            feature_services._attempt_delivery(db, delivery, endpoint)
            # The point of the guard: no request is made at all.
            net.request.urlopen.assert_not_called()

        assert delivery.status == "failed"
        assert delivery.next_attempt_at is None
        assert "Blocked" in delivery.response_body
