"""Tests for graph materialization.

These tables are a cache, so the property that matters is that reading the cache
gives the same answer as deriving live. The derivation is tested as a pure
function, the round trip through the tables is tested against a real schema, and
the truncation path is tested hardest — it is where the page crashed before, and
an edge pointing at a node the client never received is exactly that bug.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT = uuid.uuid4()


@pytest.fixture
def gs():
    import graph_services

    return graph_services


@pytest.fixture
def db():
    from db import Base
    from models import GraphEdge, GraphNode  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def entity(entity_id, label, memories, entity_type="PERSON"):
    return SimpleNamespace(
        id=entity_id,
        payload={
            "data": label,
            "entity_type": entity_type,
            "linked_memory_ids": list(memories),
        },
    )


class TestDerive:
    def test_entities_become_nodes(self, gs):
        nodes, _ = gs.derive([entity("e1", "Alice", ["m1", "m2"])])
        assert nodes["e1"]["label"] == "Alice"
        assert nodes["e1"]["memory_count"] == 2

    def test_shared_memories_become_an_edge(self, gs):
        _, edges = gs.derive([entity("e1", "Alice", ["m1"]), entity("e2", "Berlin", ["m1"])])
        assert edges == {("e1", "e2"): 1}

    def test_edge_weight_counts_shared_memories(self, gs):
        _, edges = gs.derive(
            [entity("e1", "Alice", ["m1", "m2", "m3"]), entity("e2", "Berlin", ["m1", "m2"])]
        )
        assert edges[("e1", "e2")] == 2

    def test_an_edge_is_stored_once_in_a_stable_order(self, gs):
        """(a,b) and (b,a) must be one edge, or every weight is halved."""
        _, edges = gs.derive([entity("zz", "Z", ["m1"]), entity("aa", "A", ["m1"])])
        assert list(edges) == [("aa", "zz")]

    def test_entities_with_no_shared_memory_have_no_edge(self, gs):
        _, edges = gs.derive([entity("e1", "Alice", ["m1"]), entity("e2", "Berlin", ["m2"])])
        assert edges == {}

    def test_a_row_with_no_label_is_skipped(self, gs):
        nodes, _ = gs.derive([SimpleNamespace(id="e1", payload={"linked_memory_ids": ["m1"]})])
        assert nodes == {}

    def test_a_row_with_no_id_is_skipped(self, gs):
        nodes, _ = gs.derive([SimpleNamespace(id=None, payload={"data": "Alice"})])
        assert nodes == {}

    def test_a_missing_payload_does_not_crash(self, gs):
        assert gs.derive([SimpleNamespace(id="e1", payload=None)]) == ({}, {})

    def test_fan_out_is_bounded(self, gs):
        """One memory naming 100 entities would imply 4,950 edges."""
        rows = [entity(f"e{i}", f"E{i}", ["m1"]) for i in range(100)]
        _, edges = gs.derive(rows)
        cap = gs.MAX_ENTITIES_PER_MEMORY
        assert len(edges) == cap * (cap - 1) // 2

    def test_deriving_nothing_yields_nothing(self, gs):
        assert gs.derive([]) == ({}, {})


class TestRebuildAndRead:
    def _seed(self, gs, db):
        rows = [
            entity("alice", "Alice", ["m1", "m2", "m3"]),
            entity("berlin", "Berlin", ["m1", "m2"], "GPE"),
            entity("rex", "Rex", ["m3"]),
            entity("lonely", "Lonely", ["m9"]),
        ]
        return gs.rebuild_project(db, PROJECT, rows)

    def test_rebuild_reports_what_it_wrote(self, gs, db):
        counts = self._seed(gs, db)
        assert counts == {"nodes": 4, "edges": 2}

    def test_reading_returns_what_was_built(self, gs, db):
        self._seed(gs, db)
        result = gs.read(db, PROJECT)
        assert len(result["nodes"]) == 4
        assert len(result["edges"]) == 2
        assert result["materialized"] is True

    def test_degree_is_precomputed(self, gs, db):
        """The client would otherwise walk every edge to size a node."""
        self._seed(gs, db)
        by_id = {n["id"]: n for n in gs.read(db, PROJECT)["nodes"]}
        assert by_id["alice"]["degree"] == 2
        assert by_id["lonely"]["degree"] == 0

    def test_nodes_come_back_densest_first(self, gs, db):
        """A truncated graph should keep the connected core, not an alphabetical slice."""
        self._seed(gs, db)
        degrees = [n["degree"] for n in gs.read(db, PROJECT)["nodes"]]
        assert degrees == sorted(degrees, reverse=True)

    def test_min_degree_drops_isolated_nodes(self, gs, db):
        self._seed(gs, db)
        result = gs.read(db, PROJECT, min_degree=1)
        assert "lonely" not in {n["id"] for n in result["nodes"]}

    def test_a_label_query_filters(self, gs, db):
        self._seed(gs, db)
        result = gs.read(db, PROJECT, query="ber")
        assert [n["id"] for n in result["nodes"]] == ["berlin"]

    def test_rebuilding_replaces_rather_than_accumulates(self, gs, db):
        self._seed(gs, db)
        gs.rebuild_project(db, PROJECT, [entity("solo", "Solo", ["m1"])])
        result = gs.read(db, PROJECT)
        assert [n["id"] for n in result["nodes"]] == ["solo"]

    def test_projects_do_not_bleed(self, gs, db):
        other = uuid.uuid4()
        self._seed(gs, db)
        gs.rebuild_project(db, other, [entity("theirs", "Theirs", ["m1"])])
        assert {n["id"] for n in gs.read(db, PROJECT)["nodes"]} == {
            "alice", "berlin", "rex", "lonely"
        }
        assert [n["id"] for n in gs.read(db, other)["nodes"]] == ["theirs"]

    def test_an_empty_project_reads_as_unmaterialized(self, gs, db):
        result = gs.read(db, uuid.uuid4())
        assert result["nodes"] == [] and result["materialized"] is False


class TestTruncation:
    def test_edges_never_point_at_a_node_that_was_cut(self, gs, db):
        """This is the exact shape that crashed the page in phase 00."""
        rows = [entity(f"e{i:03d}", f"E{i}", ["m1"]) for i in range(30)]
        gs.rebuild_project(db, PROJECT, rows)

        result = gs.read(db, PROJECT, limit=5)
        visible = {n["id"] for n in result["nodes"]}
        assert len(visible) == 5
        for edge in result["edges"]:
            assert edge["source"] in visible, "edge points at a node the client never got"
            assert edge["target"] in visible

    def test_truncation_is_reported_with_a_total(self, gs, db):
        rows = [entity(f"e{i:03d}", f"E{i}", ["m1"]) for i in range(30)]
        gs.rebuild_project(db, PROJECT, rows)
        result = gs.read(db, PROJECT, limit=5)
        assert result["truncated"] is True
        assert result["total_nodes"] == 30

    def test_an_untruncated_read_says_so(self, gs, db):
        gs.rebuild_project(db, PROJECT, [entity("e1", "E", ["m1"])])
        result = gs.read(db, PROJECT, limit=100)
        assert result["truncated"] is False


class TestNeighbourhood:
    def _chain(self, gs, db):
        # a-b-c-d, a chain so depth actually matters
        gs.rebuild_project(
            db,
            PROJECT,
            [
                entity("a", "A", ["m1"]),
                entity("b", "B", ["m1", "m2"]),
                entity("c", "C", ["m2", "m3"]),
                entity("d", "D", ["m3"]),
            ],
        )

    def test_depth_one_returns_immediate_neighbours(self, gs, db):
        self._chain(gs, db)
        result = gs.neighbourhood(db, PROJECT, "a", depth=1)
        assert {n["id"] for n in result["nodes"]} == {"a", "b"}

    def test_depth_two_reaches_further(self, gs, db):
        self._chain(gs, db)
        result = gs.neighbourhood(db, PROJECT, "a", depth=2)
        assert {n["id"] for n in result["nodes"]} == {"a", "b", "c"}

    def test_depth_is_capped(self, gs, db):
        """Past depth 2 a hub's 'neighbourhood' is most of the graph."""
        self._chain(gs, db)
        deep = gs.neighbourhood(db, PROJECT, "a", depth=99)
        two = gs.neighbourhood(db, PROJECT, "a", depth=2)
        assert {n["id"] for n in deep["nodes"]} == {n["id"] for n in two["nodes"]}

    def test_an_unknown_node_returns_nothing(self, gs, db):
        self._chain(gs, db)
        assert gs.neighbourhood(db, PROJECT, "nope")["nodes"] == []

    def test_neighbourhood_edges_stay_within_its_nodes(self, gs, db):
        self._chain(gs, db)
        result = gs.neighbourhood(db, PROJECT, "a", depth=1)
        present = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            assert edge["source"] in present and edge["target"] in present


class TestStaleness:
    def test_an_empty_graph_is_stale(self, gs, db):
        assert gs.is_stale(db, PROJECT) is True

    def test_a_just_built_graph_is_fresh(self, gs, db):
        gs.rebuild_project(db, PROJECT, [entity("e1", "E", ["m1"])])
        assert gs.is_stale(db, PROJECT) is False

    def test_a_zero_max_age_makes_everything_stale(self, gs, db):
        gs.rebuild_project(db, PROJECT, [entity("e1", "E", ["m1"])])
        assert gs.is_stale(db, PROJECT, max_age_seconds=-1) is True
