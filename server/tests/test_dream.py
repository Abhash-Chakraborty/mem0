"""Tests for Dream's decision logic and its audit trail.

The LLM call is stubbed throughout. What is under test is everything around it:
which verdicts clear which threshold, which of two duplicates survives, whether
a hallucinated memory id can cause an action, whether re-running produces
duplicates, and whether every decision can be undone.

That boundary is deliberate. The model's judgement is not something a unit test
can pin, but "the model said duplicates with 0.5 confidence and we merged
anyway" absolutely is - and that is the failure that would quietly destroy
someone's memory store.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT = uuid.uuid4()


@pytest.fixture
def ds():
    import dream_services

    return dream_services


@pytest.fixture
def ls():
    import lifecycle_services

    return lifecycle_services


@pytest.fixture
def db():
    from db import Base
    from models import DreamAction, DreamRun, DreamState  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def llm_returning(payload: dict):
    """Stub the OpenAI client so a fixed verdict set comes back."""
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice], usage=SimpleNamespace(total_tokens=42))
    completions = SimpleNamespace(create=lambda **kwargs: response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class TestConfig:
    def test_defaults_apply_when_a_project_has_none(self, ds):
        cfg = ds.config({})
        assert cfg["supersede_confidence"] == ds.DEFAULTS["supersede_confidence"]

    def test_the_duplicate_bar_is_higher_than_the_contradiction_bar(self, ds):
        """A wrong merge hides information; a wrong supersede only re-orders it."""
        cfg = ds.config({})
        assert cfg["merge_confidence"] > cfg["supersede_confidence"]

    def test_a_project_can_tune_thresholds(self, ds):
        cfg = ds.config({"dream": {"merge_confidence": 0.95}})
        assert cfg["merge_confidence"] == 0.95
        assert cfg["supersede_confidence"] == ds.DEFAULTS["supersede_confidence"]

    def test_supersede_and_merge_are_always_on(self, ds):
        """They are corrections; a store that knowingly keeps contradictions is worse."""
        assert ds.enabled({}, ds.SUPERSEDE) is True
        assert ds.enabled({}, ds.MERGE) is True

    def test_synthesis_is_opt_in(self, ds):
        """It writes new memories, so nobody gets them without asking."""
        assert ds.enabled({}, ds.SYNTHESIS) is False
        assert ds.enabled({"retention": {"dream_enabled": True}}, ds.SYNTHESIS) is True


class TestAdjudication:
    CANDIDATES = [
        {"id": "m1", "memory": "I live in Lisbon", "score": 0.9},
        {"id": "m2", "memory": "I have a dog named Rex", "score": 0.8},
    ]

    def test_verdicts_are_parsed(self, ds):
        payload = {
            "verdicts": [
                {"id": "m1", "verdict": "contradicts", "confidence": 0.9, "rationale": "moved"}
            ]
        }
        with patch.object(ds, "_llm_client", lambda: llm_returning(payload)):
            verdicts = ds.adjudicate({"id": "new", "memory": "I moved to Berlin"}, self.CANDIDATES)
        assert len(verdicts) == 1
        assert verdicts[0].verdict == "contradicts" and verdicts[0].confidence == 0.9

    def test_a_hallucinated_memory_id_is_dropped(self, ds):
        """Acting on an id the model invented would touch an unrelated memory."""
        payload = {"verdicts": [{"id": "does-not-exist", "verdict": "duplicates", "confidence": 1.0}]}
        with patch.object(ds, "_llm_client", lambda: llm_returning(payload)):
            assert ds.adjudicate({"id": "new", "memory": "x"}, self.CANDIDATES) == []

    def test_an_unknown_verdict_word_is_dropped(self, ds):
        payload = {"verdicts": [{"id": "m1", "verdict": "sort-of", "confidence": 1.0}]}
        with patch.object(ds, "_llm_client", lambda: llm_returning(payload)):
            assert ds.adjudicate({"id": "new", "memory": "x"}, self.CANDIDATES) == []

    def test_confidence_is_clamped(self, ds):
        payload = {"verdicts": [{"id": "m1", "verdict": "contradicts", "confidence": 5}]}
        with patch.object(ds, "_llm_client", lambda: llm_returning(payload)):
            assert ds.adjudicate({"id": "new", "memory": "x"}, self.CANDIDATES)[0].confidence == 1.0

    def test_invalid_json_yields_nothing_rather_than_raising(self, ds):
        broken = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kw: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))],
                        usage=None,
                    )
                )
            )
        )
        with patch.object(ds, "_llm_client", lambda: broken):
            assert ds.adjudicate({"id": "new", "memory": "x"}, self.CANDIDATES) == []

    def test_no_candidates_means_no_llm_call(self, ds):
        def explode():
            raise AssertionError("the model must not be called with nothing to judge")

        with patch.object(ds, "_llm_client", explode):
            assert ds.adjudicate({"id": "new", "memory": "x"}, []) == []


class TestCuration:
    def _run(self, ds, db, verdicts, new_memory, neighbours, settings=None):
        import lifecycle_services  # noqa: F401

        session_factory = lambda: _NoCloseSession(db)  # noqa: E731
        with patch.object(ds, "_llm_client", lambda: llm_returning({"verdicts": verdicts})):
            ds.curate_new_memory(
                session_factory,
                new_memory,
                None,
                {"user_id": "alice"},
                lambda **kwargs: {"results": neighbours},
            )

    def test_a_contradiction_above_the_bar_supersedes(self, ds, ls, db):
        self._run(
            ds, db,
            [{"id": "old", "verdict": "contradicts", "confidence": 0.9, "rationale": "moved city"}],
            {"id": "new", "memory": "I moved to Berlin"},
            [{"id": "old", "memory": "I live in Lisbon", "score": 0.9}],
        )
        row = ls.states_for(db, ["old"]).get("old")
        assert row is not None and row.state == "superseded"
        assert row.superseded_by == "new"
        assert row.actor == "dream"

    def test_a_contradiction_below_the_bar_does_nothing(self, ds, ls, db):
        self._run(
            ds, db,
            [{"id": "old", "verdict": "contradicts", "confidence": 0.4}],
            {"id": "new", "memory": "I moved to Berlin"},
            [{"id": "old", "memory": "I live in Lisbon", "score": 0.9}],
        )
        assert ls.states_for(db, ["old"]) == {}

    def test_a_duplicate_below_the_merge_bar_does_nothing(self, ds, ls, db):
        """0.75 clears the supersede bar but not the merge bar; it must not merge."""
        self._run(
            ds, db,
            [{"id": "old", "verdict": "duplicates", "confidence": 0.75}],
            {"id": "new", "memory": "I have a dog called Rex"},
            [{"id": "old", "memory": "I have a dog named Rex", "score": 0.95}],
        )
        assert ls.states_for(db, ["old"]) == {}

    def test_the_thinner_duplicate_is_the_one_merged_away(self, ds, ls, db):
        """Merging the detailed memory into the bare one would lose the detail."""
        self._run(
            ds, db,
            [{"id": "bare", "verdict": "duplicates", "confidence": 0.95, "rationale": "same dog"}],
            {"id": "rich", "memory": "My dog Rex is a three-year-old golden retriever"},
            [{"id": "bare", "memory": "I have a dog named Rex", "score": 0.95}],
        )
        states = ls.states_for(db, ["bare", "rich"])
        assert states["bare"].state == "merged" and states["bare"].merged_into == "rich"
        assert "rich" not in states, "the richer memory must stay active"

    def test_the_new_memory_can_be_the_one_merged_away(self, ds, ls, db):
        """Recency does not make a memory better; density does."""
        self._run(
            ds, db,
            [{"id": "rich", "verdict": "duplicates", "confidence": 0.95}],
            {"id": "bare", "memory": "I have a dog"},
            [{"id": "rich", "memory": "My dog Rex is a three-year-old golden retriever", "score": 0.95}],
        )
        states = ls.states_for(db, ["bare", "rich"])
        assert states["bare"].state == "merged" and states["bare"].merged_into == "rich"

    def test_unrelated_neighbours_are_left_alone(self, ds, ls, db):
        self._run(
            ds, db,
            [{"id": "other", "verdict": "unrelated", "confidence": 1.0}],
            {"id": "new", "memory": "I like hiking"},
            [{"id": "other", "memory": "I have a dog", "score": 0.8}],
        )
        assert ls.states_for(db, ["other"]) == {}

    def test_neighbours_below_the_similarity_floor_are_never_judged(self, ds, ls, db):
        """Cheap filter first: no LLM call for memories that are barely related."""
        def explode():
            raise AssertionError("adjudication ran on a below-floor neighbour")

        session_factory = lambda: _NoCloseSession(db)  # noqa: E731
        with patch.object(ds, "_llm_client", explode):
            ds.curate_new_memory(
                session_factory,
                {"id": "new", "memory": "x"},
                None,
                {"user_id": "alice"},
                lambda **kw: {"results": [{"id": "far", "memory": "y", "score": 0.2}]},
            )
        assert ls.states_for(db, ["far"]) == {}

    def test_a_run_is_recorded_even_when_nothing_happens(self, ds, db):
        """'Dream did nothing' and 'Dream never ran' are different problems."""
        from models import DreamRun

        session_factory = lambda: _NoCloseSession(db)  # noqa: E731
        ds.curate_new_memory(
            session_factory, {"id": "new", "memory": "x"}, None, {"user_id": "alice"},
            lambda **kw: {"results": []},
        )
        runs = db.execute(select(DreamRun)).scalars().all()
        assert len(runs) == 1 and runs[0].status == "skipped"

    def test_every_action_records_its_rationale(self, ds, db):
        from models import DreamAction

        self._run(
            ds, db,
            [{"id": "old", "verdict": "contradicts", "confidence": 0.9, "rationale": "they moved"}],
            {"id": "new", "memory": "I moved to Berlin"},
            [{"id": "old", "memory": "I live in Lisbon", "score": 0.9}],
        )
        action = db.execute(select(DreamAction)).scalars().one()
        assert action.rationale == "they moved"
        assert action.confidence == 0.9

    def test_curation_never_raises(self, ds, db):
        """A failure here must not turn into a failed write."""
        def boom(**kwargs):
            raise RuntimeError("vector store is down")

        ds.curate_new_memory(
            lambda: _NoCloseSession(db), {"id": "new", "memory": "x"}, None, {"user_id": "a"}, boom
        )


class TestPatternIdentity:
    def test_the_same_sources_give_the_same_hash(self, ds):
        assert ds._pattern_hash(["a", "b", "c"]) == ds._pattern_hash(["c", "a", "b"])

    def test_different_sources_give_different_hashes(self, ds):
        assert ds._pattern_hash(["a", "b"]) != ds._pattern_hash(["a", "b", "c"])


class TestRevert:
    def _supersede(self, ds, db):
        run = ds.start_run(db, None, ds.SUPERSEDE)
        import lifecycle_services as ls

        ls.set_state(db, "old", None, ls.SUPERSEDED, superseded_by="new", actor="dream")
        return ds.record_action(db, run, ds.SUPERSEDE, "old", "new", 0.9, "moved")

    def test_reverting_a_supersede_restores_the_memory(self, ds, ls, db):
        action = self._supersede(ds, db)
        ok, message = ds.revert(db, action.id, None)
        assert ok
        assert ls.states_for(db, ["old"])["old"].state == "active"

    def test_the_action_row_survives_the_revert(self, ds, db):
        """A reverted action is still something Dream did."""
        from models import DreamAction

        action = self._supersede(ds, db)
        ds.revert(db, action.id, None)
        row = db.get(DreamAction, action.id)
        assert row is not None and row.reverted_at is not None

    def test_reverting_twice_is_refused(self, ds, db):
        action = self._supersede(ds, db)
        ds.revert(db, action.id, None)
        ok, message = ds.revert(db, action.id, None)
        assert not ok and "already" in message.lower()

    def test_reverting_an_unknown_action_is_refused(self, ds, db):
        ok, message = ds.revert(db, uuid.uuid4(), None)
        assert not ok and "not found" in message.lower()

    def test_reverting_a_synthesis_retires_the_pattern(self, ds, ls, db):
        """The pattern was a real memory; deleting it would lose its provenance."""
        run = ds.start_run(db, None, ds.SYNTHESIS)
        action = ds.record_action(db, run, ds.SYNTHESIS, "pattern-1", None, 0.8, "a pattern")
        ok, _ = ds.revert(db, action.id, None)
        assert ok
        assert ls.states_for(db, ["pattern-1"])["pattern-1"].state == "expired"


class _NoCloseSession:
    """Wrap the test session so `with session_factory() as db` does not close it.

    dream_services opens its own session per call; the tests need the same one
    throughout so assertions can read what it wrote.
    """

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *args):
        return False

    def __getattr__(self, name):
        return getattr(self._session, name)
