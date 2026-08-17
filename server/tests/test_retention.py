"""Tests for decay ranking and expiry.

The claim that has to hold no matter what is that **decay is a bias, not a
filter**. A search that silently dropped the right answer because it had not
been read lately would be worse than no decay at all, and the floor is the only
thing standing between those two behaviours. So the floor is asserted directly,
at extremes, and through the re-ranking path.

The second claim is that a memory nobody has read yet is not punished for it.
Otherwise decay would bias against everything written recently, which is exactly
the material most likely to matter.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
PROJECT = uuid.uuid4()


@pytest.fixture
def rs():
    import retention_services

    return retention_services


@pytest.fixture
def ls():
    import lifecycle_services

    return lifecycle_services


@pytest.fixture
def db():
    from db import Base
    from models import MemoryAccess, MemoryLifecycle  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def access(days_ago: float, count: int = 1):
    return SimpleNamespace(
        last_access_at=NOW - timedelta(days=days_ago),
        access_count=count,
    )


class TestFactorBounds:
    def test_the_floor_is_never_breached(self, rs):
        """The floor is what makes decay a bias rather than a filter."""
        assert rs.factor(access(days_ago=100_000, count=0), now=NOW) >= rs.FLOOR

    def test_the_ceiling_is_never_breached(self, rs):
        """One very hot memory must not dominate every search forever."""
        assert rs.factor(access(days_ago=0, count=1_000_000), now=NOW) <= rs.CEIL

    @pytest.mark.parametrize("days,count", [(0, 0), (1, 3), (30, 50), (365, 1), (10_000, 0)])
    def test_every_plausible_input_stays_in_range(self, rs, days, count):
        value = rs.factor(access(days, count), now=NOW)
        assert rs.FLOOR <= value <= rs.CEIL

    def test_a_just_accessed_memory_is_boosted(self, rs):
        assert rs.factor(access(days_ago=0, count=5), now=NOW) > 1.0

    def test_a_long_idle_memory_is_damped(self, rs):
        assert rs.factor(access(days_ago=180, count=1), now=NOW) < 1.0

    def test_recency_dominates_monotonically(self, rs):
        """More idle time must never mean a higher factor."""
        values = [rs.factor(access(d, count=1), now=NOW) for d in (0, 1, 7, 30, 90, 365)]
        assert values == sorted(values, reverse=True)

    def test_frequency_helps(self, rs):
        idle = 10  # far enough from the ceiling that the clamp is not in play
        assert rs.factor(access(idle, 1), now=NOW) < rs.factor(access(idle, 50), now=NOW)

    def test_each_extra_recall_matters_less_than_the_last(self, rs):
        """Compared at equal increments: one hot memory must not run away with it."""
        idle = 10
        early = rs.factor(access(idle, 2), now=NOW) - rs.factor(access(idle, 1), now=NOW)
        late = rs.factor(access(idle, 11), now=NOW) - rs.factor(access(idle, 10), now=NOW)
        assert early > late

    def test_the_bands_match_the_design(self, rs):
        """These numbers are the feature. A curve that drifts off them is a
        different feature wearing the same name."""
        assert rs.factor(access(0), now=NOW) > 1.4          # just accessed
        assert 1.2 <= rs.factor(access(1), now=NOW) <= 1.45  # touched today
        assert 0.6 <= rs.factor(access(5), now=NOW) <= 1.1   # idle days
        assert 0.4 <= rs.factor(access(14), now=NOW) <= 0.7  # idle weeks
        assert rs.factor(access(90), now=NOW) <= 0.4         # idle months


class TestNeverRead:
    def test_a_memory_never_read_is_not_punished(self, rs):
        """Otherwise decay biases against everything written recently."""
        fresh = {"created_at": (NOW - timedelta(hours=1)).isoformat()}
        assert rs.factor(None, fresh, now=NOW) >= 1.0

    def test_an_old_unread_memory_is_still_damped(self, rs):
        stale = {"created_at": (NOW - timedelta(days=365)).isoformat()}
        assert rs.factor(None, stale, now=NOW) < 1.0

    def test_a_memory_with_no_dates_at_all_is_neutral(self, rs):
        """No information is not evidence of staleness."""
        assert rs.factor(None, {}, now=NOW) == 1.0

    def test_updated_at_wins_over_created_at(self, rs):
        memory = {
            "created_at": (NOW - timedelta(days=365)).isoformat(),
            "updated_at": (NOW - timedelta(hours=1)).isoformat(),
        }
        assert rs.factor(None, memory, now=NOW) >= 1.0


class TestRerank:
    def _response(self, rows):
        return {"results": rows, "relations": ["kept"]}

    def test_nothing_is_ever_removed(self, rs, db):
        """The whole point: decay reorders, it does not filter."""
        rows = [{"id": f"m{i}", "score": 0.5} for i in range(10)]
        out = rs.rerank(db, self._response(rows), now=NOW)
        assert len(out["results"]) == 10

    def test_the_envelope_survives(self, rs, db):
        out = rs.rerank(db, self._response([{"id": "m1", "score": 0.5}]), now=NOW)
        assert out["relations"] == ["kept"]

    def test_a_recently_used_memory_outranks_an_idle_one(self, rs, ls, db):
        ls.record_access(db, ["hot"], PROJECT)
        rows = [
            {"id": "cold", "score": 0.80, "created_at": (NOW - timedelta(days=400)).isoformat()},
            {"id": "hot", "score": 0.62},
        ]
        out = rs.rerank(db, self._response(rows))
        assert out["results"][0]["id"] == "hot"

    def test_the_swing_decay_can_cause_is_bounded(self, rs, ls, db):
        """Decay can reorder, but only within CEIL/FLOOR of relevance.

        With a 0.3x floor and a 1.5x ceiling the most it can overcome is a 5x
        base-score gap. Anything wider and relevance still leads - which is what
        stops decay from becoming the ranking rather than a bias on it.
        """
        ls.record_access(db, ["hot"], PROJECT)
        rows = [
            {"id": "relevant", "score": 0.99, "created_at": (NOW - timedelta(days=400)).isoformat()},
            {"id": "hot", "score": 0.18},  # a >5x gap
        ]
        out = rs.rerank(db, self._response(rows))
        assert out["results"][0]["id"] == "relevant"
        assert rs.CEIL / rs.FLOOR == 5.0, "the bound this test relies on"

    def test_freshness_wins_within_that_bound(self, rs, ls, db):
        """And inside the bound it does reorder - otherwise decay does nothing."""
        ls.record_access(db, ["hot"], PROJECT)
        rows = [
            {"id": "stale", "score": 0.80, "created_at": (NOW - timedelta(days=400)).isoformat()},
            {"id": "hot", "score": 0.40},  # a 2x gap
        ]
        out = rs.rerank(db, self._response(rows))
        assert out["results"][0]["id"] == "hot"

    def test_the_public_score_stays_in_range(self, rs, ls, db):
        """A client that has never heard of decay must still get comparable scores."""
        ls.record_access(db, ["m1"] * 1, PROJECT)
        out = rs.rerank(db, self._response([{"id": "m1", "score": 1.0}]))
        assert 0.0 <= out["results"][0]["score"] <= 1.0

    def test_the_base_score_and_factor_are_both_exposed(self, rs, db):
        """So "why did this rank here" is answerable."""
        out = rs.rerank(db, self._response([{"id": "m1", "score": 0.7}]), now=NOW)
        row = out["results"][0]
        assert row["base_score"] == 0.7
        assert rs.FLOOR <= row["decay_factor"] <= rs.CEIL

    def test_top_k_is_applied_after_reordering(self, rs, ls, db):
        ls.record_access(db, ["hot"], PROJECT)
        rows = [
            {"id": "cold", "score": 0.8, "created_at": (NOW - timedelta(days=400)).isoformat()},
            {"id": "hot", "score": 0.62},
        ]
        out = rs.rerank(db, self._response(rows), top_k=1)
        assert [r["id"] for r in out["results"]] == ["hot"]

    def test_a_missing_score_does_not_crash(self, rs, db):
        out = rs.rerank(db, self._response([{"id": "m1"}]), now=NOW)
        assert out["results"][0]["base_score"] == 0.0

    def test_an_unrecognised_shape_passes_through(self, rs, db):
        assert rs.rerank(db, "not a result set") == "not a result set"

    def test_an_empty_result_set_passes_through(self, rs, db):
        assert rs.rerank(db, {"results": []})["results"] == []


class TestEnabled:
    def test_decay_is_off_by_default(self, rs):
        """It changes ranking; nobody should get it without asking."""
        assert rs.enabled({}) is False

    def test_decay_can_be_switched_on(self, rs):
        assert rs.enabled({"retention": {"decay_enabled": True}}) is True


class TestExpiry:
    def test_a_bare_date_is_parsed(self, rs):
        """That is the shape the SDK stores."""
        assert rs.expiry_of({"expiration_date": "2026-01-01"}) is not None

    def test_an_iso_timestamp_is_parsed(self, rs):
        assert rs.expiry_of({"expiration_date": "2026-01-01T00:00:00Z"}) is not None

    def test_it_is_read_from_nested_metadata_too(self, rs):
        assert rs.expiry_of({"metadata": {"expiration_date": "2026-01-01"}}) is not None

    def test_no_expiry_means_no_expiry(self, rs):
        assert rs.expiry_of({}) is None
        assert rs.is_expired({}) is False

    def test_garbage_is_treated_as_no_expiry_not_as_expired(self, rs):
        """Expiring something because its date was unparseable would be data loss."""
        assert rs.expiry_of({"expiration_date": "whenever"}) is None
        assert rs.is_expired({"expiration_date": "whenever"}) is False

    def test_a_past_date_is_expired(self, rs):
        assert rs.is_expired({"expiration_date": "2020-01-01"}, now=NOW) is True

    def test_a_future_date_is_not(self, rs):
        assert rs.is_expired({"expiration_date": "2099-01-01"}, now=NOW) is False


class TestSweep:
    def test_passed_dates_are_marked(self, rs, ls, db):
        marked = rs.sweep_expired(
            db, [{"id": "m1", "expiration_date": "2020-01-01"}], PROJECT, now=NOW
        )
        assert marked == 1
        assert ls.states_for(db, ["m1"])["m1"].state == "expired"

    def test_future_dates_are_left_alone(self, rs, ls, db):
        assert rs.sweep_expired(db, [{"id": "m1", "expiration_date": "2099-01-01"}], PROJECT, now=NOW) == 0
        assert ls.states_for(db, ["m1"]) == {}

    def test_a_superseded_memory_is_not_overwritten(self, rs, ls, db):
        """It has a more specific state; replacing it would lose why."""
        ls.set_state(db, "m1", PROJECT, "superseded", superseded_by="m2")
        rs.sweep_expired(db, [{"id": "m1", "expiration_date": "2020-01-01"}], PROJECT, now=NOW)
        assert ls.states_for(db, ["m1"])["m1"].state == "superseded"

    def test_sweeping_twice_marks_nothing_the_second_time(self, rs, db):
        memories = [{"id": "m1", "expiration_date": "2020-01-01"}]
        assert rs.sweep_expired(db, memories, PROJECT, now=NOW) == 1
        assert rs.sweep_expired(db, memories, PROJECT, now=NOW) == 0

    def test_the_reason_names_the_date(self, rs, ls, db):
        rs.sweep_expired(db, [{"id": "m1", "expiration_date": "2020-03-04"}], PROJECT, now=NOW)
        assert "2020-03-04" in ls.states_for(db, ["m1"])["m1"].reason

    def test_expired_memories_are_hidden_not_deleted(self, rs, ls, db):
        """Consistent with everything else here - a date passing is not a delete."""
        rs.sweep_expired(db, [{"id": "m1", "expiration_date": "2020-01-01"}], PROJECT, now=NOW)
        default = ls.apply_read_mode(db, {"results": [{"id": "m1"}]}, ls.DEFAULT_MODE)
        widest = ls.apply_read_mode(db, {"results": [{"id": "m1"}]}, ls.INCLUDE_MERGED)
        assert default["results"] == []
        assert len(widest["results"]) == 1

    def test_unexpiring_restores_the_memory(self, rs, ls, db):
        rs.sweep_expired(db, [{"id": "m1", "expiration_date": "2020-01-01"}], PROJECT, now=NOW)
        rs.unexpire(db, "m1", PROJECT)
        assert ls.states_for(db, ["m1"])["m1"].state == "active"


class TestOverfetch:
    def test_reranking_widens_the_candidate_pool(self):
        """Asking for 3 and fetching 9 gives the bias almost nothing to reorder."""
        import tenancy

        assert tenancy.overfetch(3, reranking=True) >= tenancy.OVERFETCH_FLOOR_WHEN_RERANKING
        assert tenancy.overfetch(3, reranking=False) == 9

    def test_the_ceiling_still_applies(self):
        import tenancy

        assert tenancy.overfetch(100_000, reranking=True) <= tenancy.OVERFETCH_CEILING

    def test_none_stays_none(self):
        import tenancy

        assert tenancy.overfetch(None, reranking=True) is None
