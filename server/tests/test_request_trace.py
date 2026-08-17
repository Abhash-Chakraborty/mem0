"""Tests for request-trace construction, redaction, and the search grammar.

Redaction is the one here that has to be right. Phase 04 starts persisting
request bodies, and a body that reaches the database has already leaked - into
backups, into replicas, into whatever query someone runs next. So the redactor
is tested by key shape rather than by a fixed list, and the guarantee under test
is that nothing recognisably credential-shaped survives a round trip.

Trace construction is tested against the response shapes the API actually
returns, because the failure mode is silent: a trace with the wrong type or a
missing entity does not error, it just makes the Requests page quietly wrong.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def trace():
    import request_trace

    return request_trace


@pytest.fixture
def red():
    import redaction

    return redaction


@pytest.fixture
def qs():
    import query_syntax

    return query_syntax


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    @pytest.mark.parametrize(
        "key",
        [
            "api_key",
            "API_KEY",
            "openai_api_key",
            "x-api-key",
            "apiKey",
            "authorization",
            "Authorization",
            "password",
            "password_hash",
            "refresh_token",
            "access_token",
            "accessToken",
            "client_secret",
            "jwt_secret",
            "cookie",
            "Set-Cookie",
            "session_id",
            "private_key",
            "aws_credentials",
        ],
    )
    def test_credential_shaped_keys_are_redacted(self, red, key):
        """Matched by substring: the set of key names carrying secrets is not closed."""
        out = red.redact({key: "s3cret-value"})
        assert out[key] == red.REDACTED
        assert "s3cret-value" not in json.dumps(out)

    def test_nested_secrets_are_redacted(self, red):
        out = red.redact({"config": {"llm": {"api_key": "sk-live-123"}}})
        assert "sk-live-123" not in json.dumps(out)

    def test_secrets_inside_lists_are_redacted(self, red):
        out = red.redact({"items": [{"token": "abc"}, {"token": "def"}]})
        assert "abc" not in json.dumps(out) and "def" not in json.dumps(out)

    def test_ordinary_content_survives(self, red):
        out = red.redact({"messages": [{"role": "user", "content": "I like hiking"}]})
        assert out["messages"][0]["content"] == "I like hiking"

    def test_the_input_is_not_mutated(self, red):
        """This runs on request bodies handlers are still using."""
        original = {"api_key": "sk-live", "nested": {"password": "hunter2"}}
        red.redact(original)
        assert original["api_key"] == "sk-live"
        assert original["nested"]["password"] == "hunter2"

    def test_long_strings_are_truncated(self, red):
        out = red.redact({"content": "x" * (red.MAX_STRING_LEN * 2)})
        assert len(out["content"]) < red.MAX_STRING_LEN * 2
        assert "truncated" in out["content"]

    def test_deep_nesting_terminates(self, red):
        deep = current = {}
        for _ in range(50):
            current["next"] = {}
            current = current["next"]
        assert "too deep" in json.dumps(red.redact(deep))

    def test_wide_objects_are_capped(self, red):
        out = red.redact({str(i): i for i in range(red.MAX_ITEMS * 2)})
        assert len(out) <= red.MAX_ITEMS + 1

    def test_an_oversized_body_is_dropped_not_half_stored(self, red):
        """A body cut off mid-structure reads as data when it is really an artefact."""
        captured = red.capture({"blob": ["y" * 1000 for _ in range(200)]})
        assert captured["_truncated"] is True

    def test_a_normal_body_is_captured_whole(self, red):
        captured = red.capture({"user_id": "alice", "messages": [{"role": "user", "content": "hi"}]})
        assert captured["user_id"] == "alice"

    def test_capture_of_none_is_none(self, red):
        assert red.capture(None) is None

    def test_headers_are_redacted(self, red):
        out = red.redact_headers({"authorization": "Bearer xyz", "content-type": "application/json"})
        assert out["authorization"] == red.REDACTED
        assert out["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassify:
    @pytest.mark.parametrize(
        "method,path,expected",
        [
            ("POST", "/memories", "add"),
            ("GET", "/memories", "get_all"),
            ("DELETE", "/memories", "delete_all"),
            ("POST", "/search", "search"),
            ("GET", "/memories/abc-123", "get"),
            ("PUT", "/memories/abc-123", "update"),
            ("DELETE", "/memories/abc-123", "delete"),
            ("GET", "/memories/abc-123/history", "get"),
            ("GET", "/entities", "other"),
            ("POST", "/auth/login", "other"),
            ("GET", "/graph", "other"),
        ],
    )
    def test_classification(self, trace, method, path, expected):
        assert trace.classify(method, path) == expected

    def test_a_single_get_is_not_mistaken_for_a_list(self, trace):
        """These differ only by a path segment; the wrong order mislabels every get."""
        assert trace.classify("GET", "/memories") == "get_all"
        assert trace.classify("GET", "/memories/x") == "get"

    def test_streaming_paths_are_excluded_from_capture(self, trace):
        assert trace.is_streaming("/system/logs/stream")
        assert trace.is_streaming("/backups/abc/download?part=vector")
        assert not trace.is_streaming("/memories")


# ---------------------------------------------------------------------------
# Trace fields
# ---------------------------------------------------------------------------


class TestEntities:
    def test_entities_come_from_the_body(self, trace):
        found = trace.extract_entities({"user_id": "alice", "agent_id": "bot"}, {})
        assert {"type": "user", "id": "alice"} in found
        assert {"type": "agent", "id": "bot"} in found

    def test_entities_come_from_the_query_string(self, trace):
        found = trace.extract_entities(None, {"user_id": "alice"})
        assert found == [{"type": "user", "id": "alice"}]

    def test_search_filters_are_read_one_level_down(self, trace):
        found = trace.extract_entities({"query": "x", "filters": {"user_id": "alice"}}, {})
        assert found == [{"type": "user", "id": "alice"}]

    def test_the_same_entity_is_not_recorded_twice(self, trace):
        found = trace.extract_entities({"user_id": "alice"}, {"user_id": "alice"})
        assert len(found) == 1

    def test_a_run_id_is_typed_as_run(self, trace):
        assert trace.extract_entities({"run_id": "sess-1"}, {}) == [{"type": "run", "id": "sess-1"}]

    def test_no_identifiers_gives_an_empty_list_not_none(self, trace):
        assert trace.extract_entities({"query": "hello"}, {}) == []


class TestMemoryIds:
    def test_ids_come_from_a_results_envelope(self, trace):
        ids = trace.extract_memory_ids({"results": [{"id": "m1"}, {"id": "m2"}]}, "/memories")
        assert ids == ["m1", "m2"]

    def test_a_single_memory_response_yields_its_id(self, trace):
        assert trace.extract_memory_ids({"id": "m1", "memory": "x"}, "/memories/m1") == ["m1"]

    def test_a_delete_recovers_its_id_from_the_path(self, trace):
        """Otherwise the operation people most want to trace has nothing to trace."""
        assert trace.extract_memory_ids({"message": "deleted"}, "/memories/m9") == ["m9"]

    def test_the_id_list_is_bounded(self, trace):
        body = {"results": [{"id": f"m{i}"} for i in range(1000)]}
        assert len(trace.extract_memory_ids(body, "/memories")) <= 200


class TestBuildTrace:
    def _build(self, trace, **kwargs):
        base = dict(
            method="POST",
            path="/memories",
            query_params={},
            headers={},
            request_body=None,
            response_body=None,
            status_code=200,
        )
        base.update(kwargs)
        return trace.build_trace(**base)

    def test_an_add_is_traced_end_to_end(self, trace):
        result = self._build(
            trace,
            request_body=json.dumps({"user_id": "alice", "messages": [{"role": "user", "content": "hi"}]}).encode(),
            response_body=json.dumps({"results": [{"id": "m1", "event": "ADD"}]}).encode(),
        )
        assert result["request_type"] == "add"
        assert result["entities"] == [{"type": "user", "id": "alice"}]
        assert result["event_count"] == 1
        assert result["memory_ids"] == ["m1"]
        assert result["error"] is None

    def test_secrets_in_the_body_never_reach_the_trace(self, trace):
        result = self._build(
            trace,
            request_body=json.dumps({"user_id": "a", "api_key": "sk-live-SECRET"}).encode(),
        )
        assert "sk-live-SECRET" not in json.dumps(result)

    def test_a_failed_request_records_the_detail_and_no_events(self, trace):
        result = self._build(
            trace,
            status_code=404,
            response_body=json.dumps({"detail": "Memory not found."}).encode(),
        )
        assert result["error"] == "Memory not found."
        assert result["event_count"] == 0
        assert result["memory_ids"] == []

    def test_a_failure_with_no_body_still_records_the_status(self, trace):
        assert self._build(trace, status_code=500)["error"] == "HTTP 500"

    def test_a_search_summary_carries_score_range(self, trace):
        result = self._build(
            trace,
            path="/search",
            response_body=json.dumps({"results": [{"id": "m1", "score": 0.9}, {"id": "m2", "score": 0.4}]}).encode(),
        )
        assert result["result_summary"]["top_score"] == 0.9
        assert result["result_summary"]["min_score"] == 0.4

    def test_an_unparseable_body_is_described_not_stored(self, trace):
        result = self._build(trace, request_body=b"\x00\x01not json")
        assert result["payload"]["_unparsed"] is True

    def test_playground_traffic_is_marked_from_the_header(self, trace):
        result = self._build(trace, headers={"x-mem0-playground": "true"})
        assert result["is_playground"] is True

    def test_ordinary_traffic_is_not_marked_as_playground(self, trace):
        assert self._build(trace, headers={})["is_playground"] is False

    def test_build_trace_never_raises(self, trace):
        """A malformed body must cost a degraded row, never a failed request."""
        result = trace.build_trace(
            method="POST",
            path="/memories",
            query_params=None,
            headers=None,
            request_body=b"{",
            response_body=b"{",
            status_code=200,
        )
        assert result["request_type"] in trace.REQUEST_TYPES


# ---------------------------------------------------------------------------
# Search grammar
# ---------------------------------------------------------------------------


class TestQuerySyntax:
    def test_an_empty_query_parses_to_nothing(self, qs):
        assert qs.parse("").is_empty
        assert qs.parse(None).is_empty
        assert qs.parse("   ").is_empty

    def test_entity_prefixes(self, qs):
        parsed = qs.parse("user:alice")
        assert parsed.entity_type == "user" and parsed.entity_id == "alice"

    def test_session_is_an_alias_for_run(self, qs):
        """The UI says Sessions where the API says run_id."""
        assert qs.parse("session:s1").entity_type == "run"
        assert qs.parse("app:a1").entity_type == "agent"

    def test_type_and_status(self, qs):
        parsed = qs.parse("type:add status:failed")
        assert parsed.types == ["add"] and parsed.status == "failed"

    def test_type_aliases_are_accepted(self, qs):
        assert qs.parse("type:getall").types == ["get_all"]
        assert qs.parse("type:list").types == ["get_all"]

    def test_multiple_types_accumulate(self, qs):
        assert sorted(qs.parse("type:add type:search").types) == ["add", "search"]

    def test_free_text_is_kept_separately(self, qs):
        parsed = qs.parse("user:alice hiking boots")
        assert parsed.entity_id == "alice"
        assert parsed.text == "hiking boots"

    def test_quoted_values_survive(self, qs):
        assert qs.parse('user:"ada lovelace"').entity_id == "ada lovelace"

    def test_an_unknown_prefix_falls_through_to_text(self, qs):
        """`usr:alice` filtering on nothing would silently return everything."""
        parsed = qs.parse("usr:alice")
        assert parsed.entity_id is None
        assert parsed.text == "usr:alice"

    def test_a_url_is_not_parsed_as_a_filter(self, qs):
        parsed = qs.parse("https://example.com/x")
        assert parsed.text == "https://example.com/x"
        assert parsed.is_empty is False and parsed.status is None

    def test_an_invalid_type_value_falls_through(self, qs):
        parsed = qs.parse("type:nonsense")
        assert parsed.types == []
        assert parsed.text == "type:nonsense"

    def test_an_unbalanced_quote_still_parses(self, qs):
        """Someone is mid-typing; refusing to search is the wrong response."""
        assert qs.parse('user:"alice').text is not None or qs.parse('user:"alice').entity_id is not None

    def test_status_synonyms(self, qs):
        assert qs.parse("status:error").status == "failed"
        assert qs.parse("status:ok").status == "succeeded"

    def test_method_filter(self, qs):
        assert qs.parse("method:post").method == "POST"
        assert qs.parse("method:teapot").method is None
