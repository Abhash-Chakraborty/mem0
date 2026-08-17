"""Tests for the organization/project tenancy layer.

Two very different things are pinned here and the split is deliberate.

The first half tests `visible_to` and the helpers around it as pure functions.
That predicate is the whole of project isolation - a memory lives in pgvector
under the SDK's schema, so nothing at the database level stops one project
reading another's rows. If this predicate is wrong, the boundary does not exist.
It is tested without a database or an app so a failure points at the rule rather
than at plumbing.

The second half runs the real routers against a real (SQLite) database, because
the invariants worth guarding there - an org always keeps an owner, an admin
cannot mint an owner, a project role can only narrow - are about how rows relate
to each other, and mocking the rows away would test nothing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# The visibility rule
# ---------------------------------------------------------------------------


@pytest.fixture
def tenancy():
    import tenancy

    return tenancy


def make_scope(tenancy, project_id=None, is_default=False, role="member"):
    return tenancy.Scope(
        org_id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        role=role,
        user_id=uuid.uuid4(),
        is_default_project=is_default,
    )


class TestVisibility:
    def test_memory_stamped_with_this_project_is_visible(self, tenancy):
        scope = make_scope(tenancy)
        assert tenancy.visible_to({"metadata": {"project_id": str(scope.project_id)}}, scope)

    def test_memory_stamped_with_another_project_is_hidden(self, tenancy):
        scope = make_scope(tenancy)
        assert not tenancy.visible_to({"metadata": {"project_id": str(uuid.uuid4())}}, scope)

    def test_stamp_is_read_from_a_flat_payload_too(self, tenancy):
        """The SDK returns a raw payload on some paths and a nested dict on others."""
        scope = make_scope(tenancy)
        assert tenancy.visible_to({"project_id": str(scope.project_id)}, scope)
        assert not tenancy.visible_to({"project_id": str(uuid.uuid4())}, scope)

    def test_stamp_is_read_off_a_vector_store_row_object(self, tenancy):
        scope = make_scope(tenancy)
        row = SimpleNamespace(id="m1", payload={"project_id": str(scope.project_id)})
        assert tenancy.visible_to(row, scope)

    @pytest.mark.parametrize("is_default", [True, False])
    def test_unstamped_memory_belongs_to_the_default_project(self, tenancy, is_default):
        """Memories written before migration 011 have no stamp.

        The default project adopts them; any other project must not see them, or
        creating a second project would silently expose the whole history.
        """
        scope = make_scope(tenancy, is_default=is_default)
        assert tenancy.visible_to({"metadata": {}}, scope) is is_default

    def test_non_default_project_never_sees_unstamped_memories(self, tenancy):
        scope = make_scope(tenancy, is_default=False)
        assert not tenancy.visible_to({}, scope)
        assert not tenancy.visible_to({"metadata": None}, scope)

    def test_stamp_comparison_survives_uuid_versus_string(self, tenancy):
        """A stamp round-trips through JSON as a string; the scope holds a UUID."""
        pid = uuid.uuid4()
        scope = make_scope(tenancy, project_id=pid)
        assert tenancy.visible_to({"project_id": pid}, scope)
        assert tenancy.visible_to({"project_id": str(pid)}, scope)


class TestScopeResults:
    def test_results_envelope_is_preserved(self, tenancy):
        scope = make_scope(tenancy)
        mine = {"id": "a", "project_id": str(scope.project_id)}
        theirs = {"id": "b", "project_id": str(uuid.uuid4())}
        out = tenancy.scope_results({"results": [mine, theirs], "relations": ["kept"]}, scope)
        assert out["results"] == [mine]
        assert out["relations"] == ["kept"], "non-results keys must survive filtering"

    def test_bare_list_response_is_filtered(self, tenancy):
        scope = make_scope(tenancy)
        mine = {"id": "a", "project_id": str(scope.project_id)}
        assert tenancy.scope_results([mine, {"id": "b", "project_id": "other"}], scope) == [mine]

    def test_top_k_is_applied_after_filtering(self, tenancy):
        scope = make_scope(tenancy)
        rows = [{"id": str(i), "project_id": str(scope.project_id)} for i in range(10)]
        out = tenancy.scope_results({"results": rows}, scope, top_k=3)
        assert len(out["results"]) == 3

    def test_unrecognised_shape_passes_through(self, tenancy):
        scope = make_scope(tenancy)
        assert tenancy.scope_results("not a result set", scope) == "not a result set"


class TestFilterSanitising:
    def test_caller_cannot_choose_its_own_project(self, tenancy):
        """A filter that set project_id would read as scoping while bypassing it."""
        filters = tenancy.entity_filters({"user_id": "alice", "project_id": str(uuid.uuid4())})
        assert filters == {"user_id": "alice"}

    def test_nulls_are_dropped(self, tenancy):
        assert tenancy.entity_filters({"user_id": "alice", "run_id": None}) == {"user_id": "alice"}

    def test_none_input_is_an_empty_filter(self, tenancy):
        assert tenancy.entity_filters(None) == {}

    def test_metadata_stamp_cannot_be_overridden_by_the_caller(self, tenancy):
        scope = make_scope(tenancy)
        smuggled = {"project_id": str(uuid.uuid4()), "source": "telegram"}
        stamped = tenancy.scoped_metadata(scope, smuggled)
        assert stamped["project_id"] == str(scope.project_id)
        assert stamped["source"] == "telegram", "unrelated metadata must be kept"

    def test_overfetch_widens_the_read_but_stays_bounded(self, tenancy):
        assert tenancy.overfetch(None) is None
        assert tenancy.overfetch(10) > 10, "post-filtering can only shrink a page"
        assert tenancy.overfetch(100_000) <= tenancy.OVERFETCH_CEILING


class TestRoleRanks:
    def test_ranks_are_strictly_ordered(self, tenancy):
        ranks = [tenancy.rank_of(r) for r in ("reader", "member", "admin", "owner")]
        assert ranks == sorted(ranks) and len(set(ranks)) == 4

    def test_unknown_role_ranks_below_every_real_role(self, tenancy):
        assert tenancy.rank_of("nonsense") < tenancy.rank_of("reader")
        assert tenancy.rank_of("") == 0


# ---------------------------------------------------------------------------
# The routers, against a real database
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_app():
    """A FastAPI app mounting the tenancy router over an in-memory database.

    Auth is stubbed rather than exercised - test_auth.py owns that - so these
    tests can vary *who* is calling without minting JWTs.
    """
    import auth as auth_module
    import db as db_module
    from db import Base
    from models import Membership, Organization, Project, User
    from routers import organizations as organizations_router

    # StaticPool, because a default-pooled ``sqlite://`` hands out a *fresh*
    # in-memory database per connection - create_all would land in one and
    # every query in another.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    app = FastAPI()
    app.include_router(organizations_router.router)

    session = Session()

    def override_get_db():
        yield session

    state = SimpleNamespace(session=session, current=None)

    def override_verify_auth():
        return state.current

    app.dependency_overrides[db_module.get_db] = override_get_db
    app.dependency_overrides[auth_module.verify_auth] = override_verify_auth
    app.dependency_overrides[auth_module.require_auth] = override_verify_auth

    def add_user(name: str, role: str = "member", org=None) -> User:
        user = User(name=name, email=f"{name}@example.com", password_hash="x", role="member")
        session.add(user)
        session.flush()
        if org is not None:
            session.add(Membership(org_id=org.id, user_id=user.id, role=role))
        session.commit()
        return user

    org = Organization(name="Default", slug="default")
    session.add(org)
    session.flush()
    project = Project(org_id=org.id, name="default-project", slug="default-project", description="", settings={})
    session.add(project)
    session.commit()

    yield SimpleNamespace(
        # Exceptions are raised rather than turned into a 500: in these tests a
        # 500 is always a bug in the router, and swallowing it hides which one.
        client=TestClient(app),
        session=session,
        org=org,
        project=project,
        add_user=add_user,
        login=lambda user: setattr(state, "current", user),
    )

    session.close()
    engine.dispose()


class TestOrgMembership:
    def test_a_non_member_cannot_see_an_org_exists(self, tenant_app):
        """404, not 403: a 403 would confirm the id is real."""
        outsider = tenant_app.add_user("outsider")
        tenant_app.login(outsider)
        resp = tenant_app.client.get(f"/orgs/{tenant_app.org.id}/members")
        assert resp.status_code == 404

    def test_members_see_only_their_own_orgs(self, tenant_app):
        from models import Organization

        other = Organization(name="Other", slug="other")
        tenant_app.session.add(other)
        tenant_app.session.commit()

        user = tenant_app.add_user("alice", role="member", org=tenant_app.org)
        tenant_app.login(user)
        resp = tenant_app.client.get("/orgs")
        assert resp.status_code == 200
        assert [o["slug"] for o in resp.json()] == ["default"]

    def test_creating_an_org_makes_you_its_owner_with_a_default_project(self, tenant_app):
        user = tenant_app.add_user("founder")
        tenant_app.login(user)
        resp = tenant_app.client.post("/orgs", json={"name": "Acme Labs"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["role"] == "owner"
        assert body["slug"] == "acme-labs"
        assert body["project_count"] == 1, "an org with no project fails scope resolution"

    def test_org_slugs_do_not_collide(self, tenant_app):
        user = tenant_app.add_user("founder")
        tenant_app.login(user)
        first = tenant_app.client.post("/orgs", json={"name": "Acme"}).json()
        second = tenant_app.client.post("/orgs", json={"name": "Acme"}).json()
        assert first["slug"] != second["slug"]


class TestRoleChanges:
    def test_an_admin_cannot_grant_a_role_above_their_own(self, tenant_app):
        """Otherwise a compromised admin account is a compromised instance."""
        admin = tenant_app.add_user("admin", role="admin", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(admin)
        resp = tenant_app.client.patch(
            f"/orgs/{tenant_app.org.id}/members/{member.id}", json={"role": "owner"}
        )
        assert resp.status_code == 403

    def test_an_admin_cannot_demote_an_owner(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        admin = tenant_app.add_user("admin", role="admin", org=tenant_app.org)
        tenant_app.login(admin)
        resp = tenant_app.client.patch(
            f"/orgs/{tenant_app.org.id}/members/{owner.id}", json={"role": "member"}
        )
        assert resp.status_code == 403

    def test_the_last_owner_cannot_demote_themselves(self, tenant_app):
        """There is no support desk to undo locking yourself out of a self-host."""
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.patch(
            f"/orgs/{tenant_app.org.id}/members/{owner.id}", json={"role": "admin"}
        )
        assert resp.status_code == 400
        assert "owner" in resp.json()["detail"].lower()

    def test_the_last_owner_cannot_leave(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.delete(f"/orgs/{tenant_app.org.id}/members/{owner.id}")
        assert resp.status_code == 400

    def test_an_owner_can_step_down_once_another_owner_exists(self, tenant_app):
        first = tenant_app.add_user("first", role="owner", org=tenant_app.org)
        tenant_app.add_user("second", role="owner", org=tenant_app.org)
        tenant_app.login(first)
        resp = tenant_app.client.patch(
            f"/orgs/{tenant_app.org.id}/members/{first.id}", json={"role": "member"}
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "member"

    def test_a_member_can_remove_themselves_without_admin(self, tenant_app):
        tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("leaver", role="member", org=tenant_app.org)
        tenant_app.login(member)
        resp = tenant_app.client.delete(f"/orgs/{tenant_app.org.id}/members/{member.id}")
        assert resp.status_code == 200

    def test_a_member_cannot_remove_someone_else(self, tenant_app):
        tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        victim = tenant_app.add_user("victim", role="member", org=tenant_app.org)
        tenant_app.login(member)
        resp = tenant_app.client.delete(f"/orgs/{tenant_app.org.id}/members/{victim.id}")
        assert resp.status_code == 403

    def test_an_unknown_role_is_rejected_by_name(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.patch(
            f"/orgs/{tenant_app.org.id}/members/{member.id}", json={"role": "superuser"}
        )
        assert resp.status_code == 400
        assert "superuser" in resp.json()["detail"]


class TestInvites:
    def test_an_invite_returns_its_token_once_and_stores_only_a_hash(self, tenant_app):
        from models import Invite

        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.post(
            f"/orgs/{tenant_app.org.id}/invites", json={"email": "new@example.com", "role": "member"}
        )
        assert resp.status_code == 201
        token = resp.json()["token"]

        stored = tenant_app.session.query(Invite).one()
        assert stored.token_hash != token, "a leaked database must not hand out working invites"
        assert token not in tenant_app.client.get(f"/orgs/{tenant_app.org.id}/invites").text

    def test_an_invite_can_only_be_redeemed_by_its_addressee(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        token = tenant_app.client.post(
            f"/orgs/{tenant_app.org.id}/invites", json={"email": "invited@example.com"}
        ).json()["token"]

        wrong = tenant_app.add_user("wrong")
        tenant_app.login(wrong)
        assert tenant_app.client.post("/invites/accept", json={"token": token}).status_code == 403

    def test_redeeming_an_invite_grants_the_invited_role(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        token = tenant_app.client.post(
            f"/orgs/{tenant_app.org.id}/invites", json={"email": "invited@example.com", "role": "reader"}
        ).json()["token"]

        invited = tenant_app.add_user("invited")
        tenant_app.login(invited)
        resp = tenant_app.client.post("/invites/accept", json={"token": token})
        assert resp.status_code == 200
        assert resp.json()["role"] == "reader"

    def test_an_invite_cannot_be_redeemed_twice(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        token = tenant_app.client.post(
            f"/orgs/{tenant_app.org.id}/invites", json={"email": "invited@example.com"}
        ).json()["token"]

        invited = tenant_app.add_user("invited")
        tenant_app.login(invited)
        assert tenant_app.client.post("/invites/accept", json={"token": token}).status_code == 200
        assert tenant_app.client.post("/invites/accept", json={"token": token}).status_code == 404

    def test_a_garbage_token_is_not_found(self, tenant_app):
        user = tenant_app.add_user("nobody")
        tenant_app.login(user)
        assert tenant_app.client.post("/invites/accept", json={"token": "m0inv_nope"}).status_code == 404

    def test_an_admin_cannot_invite_above_their_own_role(self, tenant_app):
        admin = tenant_app.add_user("admin", role="admin", org=tenant_app.org)
        tenant_app.login(admin)
        resp = tenant_app.client.post(
            f"/orgs/{tenant_app.org.id}/invites", json={"email": "x@example.com", "role": "owner"}
        )
        assert resp.status_code == 403

    def test_inviting_an_existing_member_is_a_conflict(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.post(f"/orgs/{tenant_app.org.id}/invites", json={"email": member.email})
        assert resp.status_code == 409


class TestProjects:
    def test_the_default_project_cannot_be_deleted(self, tenant_app):
        """It owns every memory written before tenancy existed."""
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.delete(f"/projects/{tenant_app.project.id}")
        assert resp.status_code == 400

    def test_a_member_cannot_create_a_project(self, tenant_app):
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(member)
        assert tenant_app.client.post("/projects", json={"name": "Staging"}).status_code == 403

    def test_project_settings_are_merged_not_replaced(self, tenant_app):
        """Each settings page owns one section; saving one must not wipe another."""
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()

        tenant_app.client.patch(
            f"/projects/{created['id']}", json={"settings": {"retention": {"default_expiration_days": 30}}}
        )
        resp = tenant_app.client.patch(
            f"/projects/{created['id']}", json={"settings": {"extraction": {"multilingual": True}}}
        )

        settings = resp.json()["settings"]
        assert settings["retention"]["default_expiration_days"] == 30, "the other section survived"
        assert settings["extraction"]["multilingual"] is True

    def test_project_settings_come_back_resolved(self, tenant_app):
        """A brand-new project reports the defaults, not an empty dict.

        Every client would otherwise need its own copy of the defaults to
        render a settings form.
        """
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()
        assert created["settings"]["extraction"]["infer"] is True
        assert created["settings"]["retention"]["default_expiration_days"] is None

    def test_unknown_settings_keys_are_rejected_not_stored(self, tenant_app):
        """A key that persists but does nothing is indistinguishable from a bug."""
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()
        resp = tenant_app.client.patch(
            f"/projects/{created['id']}", json={"settings": {"billing": {"plan": "pro"}}}
        )
        assert "billing" not in resp.json()["settings"]

    def test_a_project_from_another_org_is_not_found(self, tenant_app):
        from models import Membership, Organization, Project

        other_org = Organization(name="Other", slug="other")
        tenant_app.session.add(other_org)
        tenant_app.session.flush()
        foreign = Project(org_id=other_org.id, name="Theirs", slug="theirs", description="", settings={})
        tenant_app.session.add(foreign)
        tenant_app.session.commit()

        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.session.add(Membership(org_id=other_org.id, user_id=owner.id, role="owner"))
        tenant_app.session.commit()

        tenant_app.login(owner)
        # Scoped to the default org, so the other org's project is out of reach
        # even though the caller is an owner there too.
        assert tenant_app.client.get(f"/projects/{foreign.id}").status_code == 404

    def test_a_project_role_can_only_narrow_the_org_role(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()

        widen = tenant_app.client.put(
            f"/projects/{created['id']}/members/{member.id}", json={"role": "admin"}
        )
        assert widen.status_code == 400, "a narrowing row must never grant more than the org role"

        narrow = tenant_app.client.put(
            f"/projects/{created['id']}/members/{member.id}", json={"role": "reader"}
        )
        assert narrow.status_code == 200
        assert narrow.json()["project_role"] == "reader"
        assert narrow.json()["effective_role"] == "reader"
        assert narrow.json()["role"] == "member", "`role` always means the org role"

    def test_effective_project_role_reflects_the_narrowing(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()
        tenant_app.client.put(f"/projects/{created['id']}/members/{member.id}", json={"role": "reader"})

        listed = {m["email"]: m for m in tenant_app.client.get(f"/projects/{created['id']}/members").json()}
        assert listed[member.email]["effective_role"] == "reader"
        assert listed[member.email]["role"] == "member", "the org role is unchanged"
        assert listed[owner.email]["effective_role"] == "owner", "no row means the org role applies"
        assert listed[owner.email]["project_role"] is None

    def test_clearing_a_narrowing_restores_the_org_role(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        member = tenant_app.add_user("member", role="member", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()
        tenant_app.client.put(f"/projects/{created['id']}/members/{member.id}", json={"role": "reader"})
        assert (
            tenant_app.client.delete(f"/projects/{created['id']}/members/{member.id}").status_code == 200
        )

        listed = {m["email"]: m for m in tenant_app.client.get(f"/projects/{created['id']}/members").json()}
        assert listed[member.email]["effective_role"] == "member"
        assert listed[member.email]["project_role"] is None


class TestScopeEndpoint:
    def test_scope_reports_the_default_project(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.get("/scope")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project_slug"] == "default-project"
        assert body["is_default_project"] is True
        assert body["role"] == "owner"

    def test_the_project_header_switches_scope(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        created = tenant_app.client.post("/projects", json={"name": "Staging"}).json()

        resp = tenant_app.client.get("/scope", headers={"X-Mem0-Project": created["slug"]})
        assert resp.status_code == 200
        assert resp.json()["project_id"] == created["id"]
        assert resp.json()["is_default_project"] is False, "only the default adopts unstamped memories"

    def test_an_unknown_project_header_is_rejected(self, tenant_app):
        owner = tenant_app.add_user("owner", role="owner", org=tenant_app.org)
        tenant_app.login(owner)
        resp = tenant_app.client.get("/scope", headers={"X-Mem0-Project": "no-such-project"})
        assert resp.status_code == 404

    def test_an_org_header_the_caller_is_not_in_is_not_found(self, tenant_app):
        from models import Organization

        other = Organization(name="Other", slug="other")
        tenant_app.session.add(other)
        tenant_app.session.commit()

        user = tenant_app.add_user("alice", role="member", org=tenant_app.org)
        tenant_app.login(user)
        resp = tenant_app.client.get("/scope", headers={"X-Mem0-Org": "other"})
        # 404, not 500: membership is checked before the project is resolved, so
        # an org the caller is not in never gets far enough to report that it
        # has no project - which would confirm the org is real.
        assert resp.status_code == 404
