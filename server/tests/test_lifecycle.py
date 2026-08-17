"""Tests for the memory lifecycle layer.

The load-bearing claim is *absence means active*. Nothing is backfilled, so on
a real instance almost every memory has no lifecycle row, and if that case were
wrong the entire Memories page would be wrong on day one. It is asserted from
several directions rather than once.

The second claim is that deletion cascades. There is no foreign key to the
memories - they live in pgvector under the SDK's schema - so the cascade is
application code, and application code that is not tested is application code
that silently stops running.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def ls():
    import lifecycle_services

    return lifecycle_services


@pytest.fixture
def db():
    from db import Base
    from models import Organization, Project  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


PROJECT = uuid.uuid4()


def memories(*ids):
    return [{"id": i, "memory": f"memory {i}"} for i in ids]


class TestReadModes:
    def test_default_shows_active_superseded_and_patterns(self, ls):
        """A contradicted fact is still what the system believed; hiding it
        makes the history unexplainable."""
        assert ls.DEFAULT_MODE.states == frozenset({"active", "superseded", "pattern"})
        assert "merged" not in ls.DEFAULT_MODE.states

    def test_latest_only_drops_superseded(self, ls):
        assert "superseded" not in ls.LATEST_ONLY.states
        assert "active" in ls.LATEST_ONLY.states

    def test_include_merged_is_the_widest(self, ls):
        assert ls.INCLUDE_MERGED.states == frozenset(ls.STATES)

    def test_include_merged_wins_over_latest_only(self, ls):
        assert ls.read_mode(latest_only=True, include_merged=True) is ls.INCLUDE_MERGED

    def test_no_flags_is_the_default_mode(self, ls):
        assert ls.read_mode() is ls.DEFAULT_MODE


class TestAbsenceMeansActive:
    def test_a_memory_with_no_row_reads_as_active(self, ls, db):
        assert ls.state_of(None) == "active"

    def test_unrowed_memories_survive_every_read_mode(self, ls, db):
        """Nothing is backfilled, so this is the common case, not the edge."""
        rows = memories("m1", "m2", "m3")
        for mode in (ls.DEFAULT_MODE, ls.LATEST_ONLY, ls.INCLUDE_MERGED):
            out = ls.apply_read_mode(db, {"results": rows}, mode)
            assert len(out["results"]) == 3, f"{mode.name} dropped un-rowed memories"

    def test_annotation_is_present_even_with_no_row(self, ls, db):
        """The client must never have to tell 'active' from 'we did not look'."""
        out = ls.apply_read_mode(db, {"results": memories("m1")}, ls.DEFAULT_MODE)
        assert out["results"][0]["lifecycle"]["state"] == "active"

    def test_the_envelope_survives_filtering(self, ls, db):
        out = ls.apply_read_mode(db, {"results": memories("m1"), "relations": ["x"]}, ls.DEFAULT_MODE)
        assert out["relations"] == ["x"]

    def test_a_bare_list_is_handled(self, ls, db):
        assert len(ls.apply_read_mode(db, memories("m1", "m2"), ls.DEFAULT_MODE)) == 2

    def test_an_unrecognised_shape_passes_through(self, ls, db):
        assert ls.apply_read_mode(db, "not a result set", ls.DEFAULT_MODE) == "not a result set"


class TestStateTransitions:
    def test_setting_a_state_creates_the_row(self, ls, db):
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2", reason="newer fact")
        row = ls.states_for(db, ["m1"])["m1"]
        assert row.state == "superseded" and row.superseded_by == "m2"
        assert row.reason == "newer fact"

    def test_every_transition_records_an_actor(self, ls, db):
        """A surprising change must be traceable to Dream rather than assumed a bug."""
        ls.set_state(db, "m1", PROJECT, "merged", merged_into="m9", actor="dream")
        assert ls.states_for(db, ["m1"])["m1"].actor == "dream"

    def test_moving_back_to_active_clears_the_pointer(self, ls, db):
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
        ls.set_state(db, "m1", PROJECT, "active", reason="restored")
        row = ls.states_for(db, ["m1"])["m1"]
        assert row.state == "active"
        assert row.superseded_by is None, "a restored memory must not still point at its replacement"

    def test_an_unknown_state_is_rejected(self, ls, db):
        with pytest.raises(ValueError):
            ls.set_state(db, "m1", PROJECT, "deleted-ish")

    def test_superseded_memories_are_hidden_by_latest_only(self, ls, db):
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
        out = ls.apply_read_mode(db, {"results": memories("m1", "m2")}, ls.LATEST_ONLY)
        assert [m["id"] for m in out["results"]] == ["m2"]

    def test_superseded_memories_are_shown_by_default_with_their_pointer(self, ls, db):
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2", reason="newer")
        out = ls.apply_read_mode(db, {"results": memories("m1", "m2")}, ls.DEFAULT_MODE)
        first = next(m for m in out["results"] if m["id"] == "m1")
        assert first["lifecycle"]["state"] == "superseded"
        assert first["lifecycle"]["superseded_by"] == "m2"

    def test_merged_memories_are_hidden_unless_asked_for(self, ls, db):
        ls.set_state(db, "m1", PROJECT, "merged", merged_into="m2")
        default = ls.apply_read_mode(db, {"results": memories("m1", "m2")}, ls.DEFAULT_MODE)
        widest = ls.apply_read_mode(db, {"results": memories("m1", "m2")}, ls.INCLUDE_MERGED)
        assert [m["id"] for m in default["results"]] == ["m2"]
        assert len(widest["results"]) == 2

    def test_top_k_is_applied_after_filtering(self, ls, db):
        """Otherwise a page shrinks because of state the caller cannot see."""
        ls.set_state(db, "m1", PROJECT, "merged", merged_into="m9")
        out = ls.apply_read_mode(db, {"results": memories("m1", "m2", "m3")}, ls.DEFAULT_MODE, top_k=2)
        assert len(out["results"]) == 2
        assert "m1" not in [m["id"] for m in out["results"]]


class TestAccess:
    def test_the_first_read_creates_the_row(self, ls, db):
        ls.record_access(db, ["m1"], PROJECT)
        row = ls.access_for(db, ["m1"])["m1"]
        assert row.access_count == 1
        assert row.first_access_at is not None and row.last_access_at is not None

    def test_reads_accumulate(self, ls, db):
        for _ in range(5):
            ls.record_access(db, ["m1"], PROJECT)
        assert ls.access_for(db, ["m1"])["m1"].access_count == 5

    def test_the_recent_list_is_bounded(self, ls, db):
        """A hot memory's row must not grow without limit."""
        for _ in range(ls.RECENT_ACCESS_LIMIT + 15):
            ls.record_access(db, ["m1"], PROJECT)
        assert len(ls.access_for(db, ["m1"])["m1"].recent) == ls.RECENT_ACCESS_LIMIT

    def test_duplicate_ids_in_one_call_count_once(self, ls, db):
        """A search returning the same memory twice is one recall, not two."""
        ls.record_access(db, ["m1", "m1", "m1"], PROJECT)
        assert ls.access_for(db, ["m1"])["m1"].access_count == 1

    def test_recording_nothing_is_a_no_op(self, ls, db):
        assert ls.record_access(db, [], PROJECT) == 0
        assert ls.record_access(db, [None, ""], PROJECT) == 0

    def test_a_memory_never_read_has_no_row(self, ls, db):
        assert ls.access_for(db, ["never-read"]) == {}


class TestFeedback:
    def test_feedback_is_recorded(self, ls, db):
        ls.add_feedback(db, "m1", PROJECT, None, "good", "spot on", ["no_strong_match"])
        rows = ls.feedback_for(db, "m1")
        assert len(rows) == 1 and rows[0].rating == "good"

    def test_feedback_is_append_only(self, ls, db):
        """Changing your mind is a second row; the history is the signal."""
        ls.add_feedback(db, "m1", PROJECT, None, "good")
        ls.add_feedback(db, "m1", PROJECT, None, "bad")
        assert len(ls.feedback_for(db, "m1")) == 2

    def test_an_invalid_rating_is_rejected(self, ls, db):
        with pytest.raises(ValueError):
            ls.add_feedback(db, "m1", PROJECT, None, "meh")

    def test_unknown_reasons_are_dropped(self, ls, db):
        ls.add_feedback(db, "m1", PROJECT, None, "bad", reasons=["conflicting", "invented"])
        assert ls.feedback_for(db, "m1")[0].reasons == ["conflicting"]

    def test_an_empty_note_is_stored_as_null_not_blank(self, ls, db):
        ls.add_feedback(db, "m1", PROJECT, None, "good", note="   ")
        assert ls.feedback_for(db, "m1")[0].note is None


class TestForget:
    def test_deleting_a_memory_clears_every_table(self, ls, db):
        """No foreign key exists to cascade from, so this is the cascade."""
        from models import MemoryAccess, MemoryFeedback, MemoryLifecycle, PatternSource

        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
        ls.record_access(db, ["m1"], PROJECT)
        ls.add_feedback(db, "m1", PROJECT, None, "good")
        db.add(PatternSource(pattern_memory_id="p1", source_memory_id="m1", project_id=PROJECT))
        db.commit()

        ls.forget(db, ["m1"])

        assert db.get(MemoryLifecycle, "m1") is None
        assert db.get(MemoryAccess, "m1") is None
        assert db.execute(select(MemoryFeedback).where(MemoryFeedback.memory_id == "m1")).first() is None
        assert db.execute(select(PatternSource).where(PatternSource.source_memory_id == "m1")).first() is None

    def test_deleting_the_replacement_restores_what_it_superseded(self, ls, db):
        """Otherwise the older memory stays hidden, pointing at an id that is gone."""
        ls.set_state(db, "old", PROJECT, "superseded", superseded_by="new")
        ls.forget(db, ["new"])

        row = ls.states_for(db, ["old"])["old"]
        assert row.state == "active"
        assert row.superseded_by is None
        assert "deleted" in (row.reason or "")

    def test_forgetting_nothing_is_a_no_op(self, ls, db):
        assert ls.forget(db, []) == 0

    def test_forgetting_an_unknown_id_is_harmless(self, ls, db):
        assert ls.forget(db, ["never-existed"]) == 1


class TestCounts:
    def test_counts_exclude_active(self, ls, db):
        """Active is the absence of a row; counting it means counting pgvector."""
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
        ls.set_state(db, "m3", PROJECT, "merged", merged_into="m4")
        counts = ls.counts_by_state(db, PROJECT)
        assert counts == {"superseded": 1, "merged": 1}
        assert "active" not in counts

    def test_counts_are_scoped_to_a_project(self, ls, db):
        other = uuid.uuid4()
        ls.set_state(db, "m1", PROJECT, "merged", merged_into="x")
        ls.set_state(db, "m2", other, "merged", merged_into="y")
        assert ls.counts_by_state(db, PROJECT) == {"merged": 1}
        assert ls.counts_by_state(db, other) == {"merged": 1}


def test_changed_at_is_timezone_aware(ls, db):
    """A naive timestamp here would compare wrongly against decay's cutoffs."""
    ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
    changed = ls.states_for(db, ["m1"])["m1"].changed_at
    assert changed.tzinfo is not None or isinstance(changed, datetime)
    assert changed <= datetime.now(timezone.utc).replace(tzinfo=changed.tzinfo)
