"""Tests for the /graph entity-graph endpoint.

Covers the response shape, scope filtering (user_id/agent_id/run_id), and the
four diagnostic states the endpoint reports so the dashboard never silently
shows an unexplained empty graph:

    ok                     - entities were found
    empty                  - extractor works, but no entities yet
    extractor_unavailable  - spaCy model missing, so no graph can be built
    error                  - the entity store query failed

The mem0 runtime and DB are never touched: ``get_memory_instance`` and the
spaCy probe are monkeypatched, and auth is overridden.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


class FakeEntityStore:
    """Stand-in for mem0's entity vector store.

    Records the filters/top_k it was called with, returns canned rows, or raises
    a canned error - whichever the test configures.
    """

    def __init__(self, rows=None, error: Exception | None = None):
        self._rows = rows or []
        self._error = error
        self.calls: list[dict] = []

    def list(self, filters=None, top_k=None):
        self.calls.append({"filters": filters, "top_k": top_k})
        if self._error is not None:
            raise self._error
        return self._rows


def build_client(monkeypatch, *, rows=None, error=None, extraction_available=True, auth=None):
    """Create a TestClient for an app exposing only the graph router."""
    from auth import verify_auth
    from routers import graph as graph_module

    store = FakeEntityStore(rows=rows, error=error)
    fake_memory = SimpleNamespace(entity_store=store)

    monkeypatch.setattr(graph_module, "get_memory_instance", lambda: fake_memory)
    monkeypatch.setattr(graph_module, "_entity_extraction_available", lambda: extraction_available)

    app = FastAPI()
    app.include_router(graph_module.router)
    app.dependency_overrides[verify_auth] = lambda: (auth if auth is not None else SimpleNamespace(role="admin"))

    client = TestClient(app)
    client.store = store  # expose for assertions
    return client


def test_graph_ok_shape_and_edges(monkeypatch, make_row):
    rows = [
        make_row("e1", "Hermes", "PROPER", ["m1", "m2"]),
        make_row("e2", "Redis", "PROPER", ["m1"]),
        make_row("e3", "LangGraph", "PROPER", ["m2"]),
    ]
    client = build_client(monkeypatch, rows=rows)

    resp = client.get("/graph")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "ok"
    assert body["source"] == "mem0_entity_store"
    assert body["entity_extraction_available"] is True

    nodes = {n["id"]: n for n in body["nodes"]}
    assert set(nodes) == {"e1", "e2", "e3"}
    assert nodes["e1"]["label"] == "Hermes"
    assert nodes["e1"]["memories"] == 2

    # m1 links e1+e2; m2 links e1+e3 -> two distinct co-occurrence edges.
    edge_pairs = {tuple(sorted((e["source"], e["target"]))) for e in body["edges"]}
    assert edge_pairs == {("e1", "e2"), ("e1", "e3")}
    for edge in body["edges"]:
        assert edge["relationship"] == "co-occurs"
        assert edge["weight"] >= 1


def test_graph_edge_weight_counts_shared_memories(monkeypatch, make_row):
    # e1 and e2 co-occur in two memories -> weight 2.
    rows = [
        make_row("e1", "Hermes", "PROPER", ["m1", "m2"]),
        make_row("e2", "Redis", "PROPER", ["m1", "m2"]),
    ]
    client = build_client(monkeypatch, rows=rows)
    body = client.get("/graph").json()
    assert len(body["edges"]) == 1
    assert body["edges"][0]["weight"] == 2


@pytest.mark.parametrize(
    "query,expected",
    [
        ("?user_id=alice", {"user_id": "alice"}),
        ("?agent_id=bot", {"agent_id": "bot"}),
        ("?run_id=run-7", {"run_id": "run-7"}),
        ("?user_id=alice&agent_id=bot&run_id=run-7", {"user_id": "alice", "agent_id": "bot", "run_id": "run-7"}),
    ],
)
def test_graph_passes_scope_filters(monkeypatch, make_row, query, expected):
    client = build_client(monkeypatch, rows=[make_row("e1", "Hermes", "PROPER", ["m1"])])
    resp = client.get(f"/graph{query}")
    assert resp.status_code == 200
    assert client.store.calls[-1]["filters"] == expected


def test_graph_no_scope_passes_none_filter(monkeypatch, make_row):
    client = build_client(monkeypatch, rows=[make_row("e1", "Hermes", "PROPER", ["m1"])])
    client.get("/graph")
    # Empty scope must collapse to None, not {} (so the store lists everything).
    assert client.store.calls[-1]["filters"] is None


def test_graph_empty_when_extractor_available(monkeypatch):
    client = build_client(monkeypatch, rows=[], extraction_available=True)
    body = client.get("/graph").json()
    assert body["status"] == "empty"
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["entity_extraction_available"] is True


def test_graph_extractor_unavailable(monkeypatch):
    client = build_client(monkeypatch, rows=[], extraction_available=False)
    body = client.get("/graph").json()
    assert body["status"] == "extractor_unavailable"
    assert body["entity_extraction_available"] is False
    assert "spaCy" in (body["detail"] or "") or "extraction" in (body["detail"] or "")


def test_graph_store_error_is_reported(monkeypatch):
    client = build_client(monkeypatch, error=RuntimeError("connection refused"))
    body = client.get("/graph").json()
    assert body["status"] == "error"
    assert body["nodes"] == []
    assert "connection refused" in (body["detail"] or "")


def test_graph_missing_collection_is_empty_not_error(monkeypatch):
    # A never-created entities collection is normal before the first add; it must
    # be reported as empty, not as a hard error.
    client = build_client(
        monkeypatch,
        error=Exception('relation "memories_entities" does not exist'),
        extraction_available=True,
    )
    body = client.get("/graph").json()
    assert body["status"] == "empty"


def test_graph_requires_auth(monkeypatch):
    def _unauthorized():
        raise HTTPException(status_code=401, detail="Not authenticated")

    client = build_client(monkeypatch, rows=[])
    # Replace the override with one that simulates a failed auth dependency.
    from auth import verify_auth

    client.app.dependency_overrides[verify_auth] = _unauthorized
    assert client.get("/graph").status_code == 401


def test_graph_limit_is_bounded(monkeypatch, make_row):
    client = build_client(monkeypatch, rows=[make_row("e1", "Hermes", "PROPER", ["m1"])])
    # Above the SCAN_LIMIT ceiling -> 422 from query validation.
    from routers import graph as graph_module

    assert client.get(f"/graph?limit={graph_module.SCAN_LIMIT + 1}").status_code == 422
    # A valid limit is forwarded to the store.
    client.get("/graph?limit=10")
    assert client.store.calls[-1]["top_k"] == 10
