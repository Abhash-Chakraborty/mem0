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


def build_client(
    monkeypatch,
    *,
    rows=None,
    error=None,
    extraction_available=True,
    auth=None,
    materialized=True,
):
    """Create a TestClient for an app exposing only the graph router.

    Since phase 09 the route resolves a project scope and reads a materialized
    graph. Both are stubbed here: an in-memory SQLite database stands in for the
    graph tables, and the scope is fixed. What stays under test is the
    derivation and the diagnostic states, which is what this file is about.

    materialized=False forces the live-derivation path, which is what the
    scope-filter tests need - a scoped read never consults the cache.
    """
    import uuid as _uuid

    from auth import verify_auth
    from db import Base, get_db
    from routers import graph as graph_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from tenancy import Scope, require_scope

    store = FakeEntityStore(rows=rows, error=error)
    fake_memory = SimpleNamespace(entity_store=store)

    monkeypatch.setattr(graph_module, "get_memory_instance", lambda: fake_memory)
    monkeypatch.setattr(graph_module, "_entity_extraction_available", lambda: extraction_available)
    if not materialized:
        # Make the cache report itself permanently fresh *and* empty, so the
        # route falls through to live derivation without rebuilding.
        monkeypatch.setattr(graph_module.graph_services, "is_stale", lambda *a, **k: False)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()

    project_id = _uuid.uuid4()
    scope = Scope(org_id=_uuid.uuid4(), project_id=project_id, role="admin", is_default_project=True)

    app = FastAPI()
    app.include_router(graph_module.router)
    app.dependency_overrides[verify_auth] = lambda: (auth if auth is not None else SimpleNamespace(role="admin"))
    app.dependency_overrides[require_scope] = lambda: scope
    def _get_db():
        # A generator, not an iterator: FastAPI unwraps yield-dependencies, and
        # a bare iterator arrives at the route as the iterator itself.
        yield session

    app.dependency_overrides[get_db] = _get_db

    client = TestClient(app)
    client.store = store  # expose for assertions
    client.session = session
    client.project_id = project_id
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
    # Since phase 09 the route depends on require_scope rather than verify_auth
    # directly, so that is the dependency an unauthenticated request fails on.
    from tenancy import require_scope

    client.app.dependency_overrides[require_scope] = _unauthorized
    assert client.get("/graph").status_code == 401


def test_graph_limit_is_rejected_above_the_ceiling(monkeypatch, make_row):
    client = build_client(monkeypatch, rows=[make_row("e1", "Hermes", "PROPER", ["m1"])])
    from routers import graph as graph_module

    assert client.get(f"/graph?limit={graph_module.SCAN_LIMIT + 1}").status_code == 422


def test_graph_limit_caps_returned_nodes(monkeypatch, make_row):
    """Since phase 09,  bounds what comes back, not what is scanned.

    The scan is bounded separately by graph_services.SCAN_LIMIT, because the
    materialized graph has to be built from the whole entity store even when
    the caller only wants the densest slice of it.
    """
    rows = [make_row(f"e{i}", f"E{i}", "PROPER", ["m1"]) for i in range(25)]
    client = build_client(monkeypatch, rows=rows)

    body = client.get("/graph?limit=10").json()
    assert len(body["nodes"]) == 10
    assert body["truncated"] is True
    assert body["total_nodes"] == 25


def test_graph_scoped_read_still_forwards_the_limit(monkeypatch, make_row):
    """An entity-scoped read bypasses the cache and derives live."""
    client = build_client(
        monkeypatch, rows=[make_row("e1", "Hermes", "PROPER", ["m1"])], materialized=False
    )
    client.get("/graph?user_id=alice&limit=10")
    assert client.store.calls[-1]["top_k"] == 10


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------
#
# The dashboard normalizes /graph responses at its fetch boundary (see
# dashboard/src/lib/graph.ts). That normalizer exists because a body without a
# `nodes` key used to reach `[...graph.nodes]` and throw during render, which -
# with no error boundary above it - produced a full-page "Application error" on
# /dashboard/graph in production.
#
# These assert the server half of that contract: `nodes` and `edges` are always
# present and always lists, in every diagnostic state. If this ever regresses,
# the client degrades to an error card rather than crashing, but the crash is
# cheaper to prevent here.


@pytest.mark.parametrize(
    "kwargs, expected_status",
    [
        ({"rows": []}, "empty"),
        ({"rows": [], "extraction_available": False}, "extractor_unavailable"),
        ({"error": RuntimeError("connection refused")}, "error"),
    ],
)
def test_graph_always_returns_node_and_edge_lists(monkeypatch, kwargs, expected_status):
    client = build_client(monkeypatch, **kwargs)

    body = client.get("/graph").json()

    assert body["status"] == expected_status
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)


def test_graph_nodes_never_carry_null_label_or_type(monkeypatch, make_row):
    """Rows missing a label are dropped, not emitted with a null.

    The client renders `n.type.toLowerCase()` and `n.label.length`; a null in
    either field is a TypeError during render.
    """
    rows = [
        make_row("e1", "Hermes", "PROPER", ["m1"]),
        SimpleNamespace(id="e2", payload={"data": None, "linked_memory_ids": ["m1"]}),
        SimpleNamespace(id="e3", payload={"data": "Redis", "linked_memory_ids": ["m1"]}),
    ]
    client = build_client(monkeypatch, rows=rows)

    body = client.get("/graph").json()

    ids = {n["id"] for n in body["nodes"]}
    assert ids == {"e1", "e3"}, "the row with a null label must be dropped"
    for node in body["nodes"]:
        assert isinstance(node["label"], str) and node["label"]
        assert isinstance(node["type"], str) and node["type"]
    # e3 has no entity_type in its payload and must still get a usable default.
    assert next(n for n in body["nodes"] if n["id"] == "e3")["type"] == "ENTITY"
