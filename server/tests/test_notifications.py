"""Tests for notification channel formatting.

The risk these cover: a Discord or Slack endpoint that silently collects 400s
because it was sent the raw event envelope those services do not accept, and a
generic endpoint whose payload shape quietly changes under receivers that are
already parsing it.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture
def services():
    import feature_services

    return feature_services


def make_delivery(event_type: str, data: dict | None = None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        event_type=event_type,
        payload={
            "event": event_type,
            "created_at": "2026-08-16T00:00:00+00:00",
            "data": data or {},
        },
    )


def endpoint(channel: str):
    return SimpleNamespace(url="https://example.test/hook", secret="s", channel=channel)


class TestGenericChannel:
    def test_generic_payload_is_unchanged(self, services):
        delivery = make_delivery("memory.created", {"memory": {"memory": "likes tennis"}})
        body = json.loads(services.format_payload(endpoint("generic"), delivery))
        assert body == delivery.payload

    def test_missing_channel_attribute_defaults_to_generic(self, services):
        """Rows created before the channel column existed have no attribute."""
        legacy = SimpleNamespace(url="https://example.test/hook", secret="s")
        delivery = make_delivery("memory.created")
        assert json.loads(services.format_payload(legacy, delivery)) == delivery.payload

    def test_null_channel_defaults_to_generic(self, services):
        legacy = SimpleNamespace(url="https://x.test", secret="s", channel=None)
        delivery = make_delivery("memory.created")
        assert json.loads(services.format_payload(legacy, delivery)) == delivery.payload


class TestDiscordChannel:
    def test_shape_matches_discord_webhook_contract(self, services):
        delivery = make_delivery("backup.completed", {"filename": "snap.dump"})
        body = json.loads(services.format_payload(endpoint("discord"), delivery))
        assert "embeds" in body and len(body["embeds"]) == 1
        embed = body["embeds"][0]
        assert embed["title"] == "backup.completed"
        assert "snap.dump" in embed["description"]

    def test_colour_is_an_integer_not_a_hex_string(self, services):
        """Discord rejects a string here, and the failure is a silent 400."""
        delivery = make_delivery("backup.completed", {"filename": "s.dump"})
        body = json.loads(services.format_payload(endpoint("discord"), delivery))
        assert isinstance(body["embeds"][0]["color"], int)

    def test_failures_are_coloured_differently_from_successes(self, services):
        ok = json.loads(
            services.format_payload(
                endpoint("discord"), make_delivery("backup.completed", {"filename": "a"})
            )
        )
        bad = json.loads(
            services.format_payload(
                endpoint("discord"), make_delivery("backup.failed", {"error": "disk full"})
            )
        )
        assert ok["embeds"][0]["color"] != bad["embeds"][0]["color"]

    def test_failure_message_carries_the_reason(self, services):
        delivery = make_delivery("backup.failed", {"error": "disk full"})
        body = json.loads(services.format_payload(endpoint("discord"), delivery))
        assert "disk full" in body["embeds"][0]["description"]


class TestSlackChannel:
    def test_shape_has_top_level_text(self, services):
        delivery = make_delivery("system.degraded", {"sections": ["disk", "backups"]})
        body = json.loads(services.format_payload(endpoint("slack"), delivery))
        assert "text" in body
        assert "disk" in body["text"] and "backups" in body["text"]

    def test_alert_uses_danger_colour(self, services):
        delivery = make_delivery("backup.failed", {"error": "nope"})
        body = json.loads(services.format_payload(endpoint("slack"), delivery))
        assert body["attachments"][0]["color"] == "danger"


class TestSummaries:
    @pytest.mark.parametrize(
        "event,data,expected_fragment",
        [
            ("backup.completed", {"filename": "x.dump"}, "x.dump"),
            ("backup.failed", {"error": "boom"}, "boom"),
            ("system.degraded", {"sections": ["disk"]}, "disk"),
            ("search.performed", {"result_count": 3}, "3"),
            ("memory.created", {"memory": {"memory": "plays guitar"}}, "plays guitar"),
        ],
    )
    def test_summary_mentions_the_important_detail(
        self, services, event, data, expected_fragment
    ):
        summary = services._event_summary(event, {"data": data})
        assert expected_fragment in summary

    def test_unknown_event_falls_back_to_its_name(self, services):
        assert services._event_summary("some.new.event", {"data": {}}) == "some.new.event"

    def test_missing_data_does_not_raise(self, services):
        assert services._event_summary("backup.completed", {}) is not None

    def test_long_memory_text_is_truncated(self, services):
        summary = services._event_summary(
            "memory.created", {"data": {"memory": {"memory": "x" * 500}}}
        )
        assert len(summary) < 250


class TestEventRegistry:
    def test_operational_events_are_registered(self, services):
        for event in ("backup.completed", "backup.failed", "system.degraded"):
            assert event in services.WEBHOOK_EVENTS

    def test_every_event_has_a_description(self):
        """A new event without a description used to KeyError the events list."""
        from feature_services import WEBHOOK_EVENTS
        from routers.webhooks import WEBHOOK_EVENT_DESCRIPTIONS

        assert set(WEBHOOK_EVENTS) <= set(WEBHOOK_EVENT_DESCRIPTIONS)

    def test_alert_events_are_a_subset_of_all_events(self, services):
        assert services.ALERT_EVENTS <= services.WEBHOOK_EVENTS
