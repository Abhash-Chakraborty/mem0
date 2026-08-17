"""Tests for entity alias resolution.

The invariant under test is that resolution has exactly one answer and always
takes one hop. Both are enforced on write - a chain is collapsed as it is
created, an alias may point at one canonical - so the tests push on the write
path rather than checking the read path is defensive about shapes it should
never see.

Linking is the feature people reach for when their memories have fragmented
across channels, which means it runs against data that is already messy. The
failure that matters is not a crash; it is a link that quietly resolves the
wrong way and moves someone's memories onto a stranger.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT = uuid.uuid4()


@pytest.fixture
def ident():
    import identity

    identity.invalidate()
    return identity


@pytest.fixture
def db(ident):
    from db import Base
    from models import EntityAlias  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()
    ident.invalidate()


class TestResolution:
    def test_an_unlinked_id_resolves_to_itself(self, ident, db):
        assert ident.resolve(db, PROJECT, "user", "alice") == "alice"

    def test_an_alias_resolves_to_its_canonical(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "alice"

    def test_the_canonical_resolves_to_itself(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.resolve(db, PROJECT, "user", "alice") == "alice"

    def test_expand_returns_the_whole_identity(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471", "discord-88"])
        assert set(ident.expand(db, PROJECT, "user", "alice")) == {
            "alice",
            "telegram-4471",
            "discord-88",
        }

    def test_expand_from_an_alias_gives_the_same_set(self, ident, db):
        """Reads happen under whichever id the caller has; all must agree."""
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471", "discord-88"])
        assert set(ident.expand(db, PROJECT, "user", "telegram-4471")) == set(
            ident.expand(db, PROJECT, "user", "alice")
        )

    def test_the_canonical_is_first_in_expand(self, ident, db):
        """Callers that take ids[0] must get the surviving identifier."""
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.expand(db, PROJECT, "user", "telegram-4471")[0] == "alice"

    def test_expand_of_an_unlinked_id_is_just_itself(self, ident, db):
        assert ident.expand(db, PROJECT, "user", "bob") == ["bob"]

    def test_types_do_not_bleed(self, ident, db):
        """A user called 'x' and an agent called 'x' are different entities."""
        ident.link(db, PROJECT, "user", "alice", ["x"])
        assert ident.resolve(db, PROJECT, "agent", "x") == "x"

    def test_projects_do_not_bleed(self, ident, db):
        other = uuid.uuid4()
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.resolve(db, other, "user", "telegram-4471") == "telegram-4471"


class TestChainCollapsing:
    def test_linking_to_an_alias_collapses_to_its_canonical(self, ident, db):
        """C to B where B resolves to A must store C to A, not C to B."""
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        ident.link(db, PROJECT, "user", "telegram-4471", ["discord-88"])
        assert ident.resolve(db, PROJECT, "user", "discord-88") == "alice"

    def test_resolution_is_always_one_hop(self, ident, db):
        from models import EntityAlias

        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        ident.link(db, PROJECT, "user", "telegram-4471", ["discord-88"])
        rows = db.query(EntityAlias).all()
        assert all(r.canonical_id == "alice" for r in rows), "a stored row still points at an alias"

    def test_linking_an_existing_canonical_as_an_alias_repoints_its_aliases(self, ident, db):
        """Otherwise the old canonical's aliases would keep pointing at a now-alias."""
        ident.link(db, PROJECT, "user", "bob", ["bob-web"])
        ident.link(db, PROJECT, "user", "alice", ["bob"])
        assert ident.resolve(db, PROJECT, "user", "bob-web") == "alice"
        assert ident.resolve(db, PROJECT, "user", "bob") == "alice"


class TestRejections:
    def test_an_id_cannot_be_its_own_alias(self, ident, db):
        with pytest.raises(ident.LinkError):
            ident.link(db, PROJECT, "user", "alice", ["alice"])

    def test_an_alias_cannot_point_at_two_canonicals(self, ident, db):
        """The whole design rests on resolution having one answer."""
        ident.link(db, PROJECT, "user", "alice", ["shared"])
        with pytest.raises(ident.LinkError) as exc:
            ident.link(db, PROJECT, "user", "bob", ["shared"])
        assert "already resolves to" in str(exc.value)

    def test_the_reverse_link_is_rejected(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        with pytest.raises(ident.LinkError) as exc:
            ident.link(db, PROJECT, "user", "telegram-4471", ["alice"])
        assert "cycle" in str(exc.value).lower()

    def test_relinking_the_same_pair_is_a_no_op_not_an_error(self, ident, db):
        """Retries and double-clicks must not fail."""
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        created = ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert created == []
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "alice"

    def test_an_unknown_entity_type_is_rejected(self, ident, db):
        with pytest.raises(ident.LinkError):
            ident.link(db, PROJECT, "spaceship", "alice", ["x"])

    def test_an_empty_canonical_is_rejected(self, ident, db):
        with pytest.raises(ident.LinkError):
            ident.link(db, PROJECT, "user", "   ", ["x"])

    def test_blank_aliases_are_skipped(self, ident, db):
        created = ident.link(db, PROJECT, "user", "alice", ["", "  ", "telegram-4471"])
        assert len(created) == 1


class TestUnlink:
    def test_unlinking_restores_the_split(self, ident, db):
        rows = ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.unlink(db, PROJECT, rows[0].id) is True
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "telegram-4471"

    def test_unlinking_leaves_other_aliases_alone(self, ident, db):
        rows = ident.link(db, PROJECT, "user", "alice", ["telegram-4471", "discord-88"])
        ident.unlink(db, PROJECT, rows[0].id)
        assert ident.resolve(db, PROJECT, "user", "discord-88") == "alice"

    def test_unlinking_from_the_wrong_project_fails(self, ident, db):
        rows = ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.unlink(db, uuid.uuid4(), rows[0].id) is False

    def test_unlinking_an_unknown_id_is_false_not_an_error(self, ident, db):
        assert ident.unlink(db, PROJECT, uuid.uuid4()) is False


class TestWritePath:
    def test_a_write_is_filed_under_the_canonical(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        params = {"user_id": "telegram-4471"}
        ident.apply_to_write(db, PROJECT, params, {})
        assert params["user_id"] == "alice"

    def test_the_original_identifier_is_preserved(self, ident, db):
        """Which channel a memory arrived from is worth keeping."""
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        params = {"user_id": "telegram-4471"}
        metadata = ident.apply_to_write(db, PROJECT, params, {})
        assert metadata[ident.SOURCE_KEY]["user_id"] == "telegram-4471"

    def test_an_unlinked_write_is_untouched(self, ident, db):
        params = {"user_id": "bob"}
        metadata = ident.apply_to_write(db, PROJECT, params, {})
        assert params["user_id"] == "bob"
        assert ident.SOURCE_KEY not in metadata

    def test_every_entity_field_is_redirected(self, ident, db):
        ident.link(db, PROJECT, "user", "alice", ["u2"])
        ident.link(db, PROJECT, "agent", "aurion", ["a2"])
        ident.link(db, PROJECT, "run", "sess-1", ["r2"])
        params = {"user_id": "u2", "agent_id": "a2", "run_id": "r2"}
        ident.apply_to_write(db, PROJECT, params, {})
        assert params == {"user_id": "alice", "agent_id": "aurion", "run_id": "sess-1"}


class TestCache:
    def test_a_new_link_is_visible_immediately(self, ident, db):
        """A cache that survives its own invalidation is a stale identity."""
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "telegram-4471"
        ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "alice"

    def test_an_unlink_is_visible_immediately(self, ident, db):
        rows = ident.link(db, PROJECT, "user", "alice", ["telegram-4471"])
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "alice"
        ident.unlink(db, PROJECT, rows[0].id)
        assert ident.resolve(db, PROJECT, "user", "telegram-4471") == "telegram-4471"

    def test_resolution_stays_fast_with_many_aliases(self, ident, db):
        """Resolution sits on the read path of every memory query."""
        import time

        ident.link(db, PROJECT, "user", "alice", [f"alias-{i}" for i in range(1000)])
        ident.resolve(db, PROJECT, "user", "alias-0")  # warm

        start = time.perf_counter()
        for i in range(1000):
            ident.resolve(db, PROJECT, "user", f"alias-{i}")
        per_call_ms = (time.perf_counter() - start) * 1000 / 1000
        assert per_call_ms < 5, f"{per_call_ms:.3f}ms per resolve at 1000 aliases"
