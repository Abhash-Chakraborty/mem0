"""Tests for this fork's authentication layer.

Upstream guards the REST API with a single ``MEM0_API_KEY``; this fork replaced
that with JWT sessions, per-user API keys, a bootstrap ``ADMIN_API_KEY`` and an
``AUTH_DISABLED`` escape hatch. Upstream's ``tests/test_server_auth.py`` therefore
cannot describe this behaviour, so the fork's own semantics are pinned here.

The dependency under test is ``auth.verify_auth`` and the two guards layered on
it. Each is exercised through a throwaway FastAPI app rather than the real one,
so these stay fast and independent of route changes in main.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def auth_module():
    import auth

    return auth


def build_app(auth, dependency_name: str):
    """Mount a single protected route using one of the auth guards."""
    app = FastAPI()
    guard = getattr(auth, dependency_name)

    @app.get("/protected")
    async def protected(user=Depends(guard)):
        return {"user": getattr(user, "name", None), "role": getattr(user, "role", None)}

    return TestClient(app, raise_server_exceptions=False)


def make_user(role: str = "member", name: str = "someone"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        email=f"{name}@example.com",
        role=role,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# verify_auth: which credential wins, and what happens with none
# ---------------------------------------------------------------------------


class TestVerifyAuth:
    def test_no_credentials_is_401_when_auth_enabled(self, auth_module):
        with patch.object(auth_module, "AUTH_DISABLED", False):
            client = build_app(auth_module, "verify_auth")
            resp = client.get("/protected")
        assert resp.status_code == 401
        # The message must tell the caller how to authenticate, not just refuse.
        assert "Bearer" in resp.json()["detail"] or "X-API-Key" in resp.json()["detail"]

    def test_no_credentials_passes_when_auth_disabled(self, auth_module):
        with patch.object(auth_module, "AUTH_DISABLED", True):
            client = build_app(auth_module, "verify_auth")
            resp = client.get("/protected")
        assert resp.status_code == 200

    def test_admin_api_key_is_accepted(self, auth_module):
        with patch.object(auth_module, "ADMIN_API_KEY", "a-long-admin-key-value"):
            client = build_app(auth_module, "verify_auth")
            resp = client.get("/protected", headers={"X-API-Key": "a-long-admin-key-value"})
        assert resp.status_code == 200

    def test_wrong_admin_api_key_falls_through_to_lookup(self, auth_module):
        """A non-matching key must be looked up as a user key, not silently accepted."""
        with patch.object(auth_module, "ADMIN_API_KEY", "a-long-admin-key-value"):
            with patch.object(auth_module, "_resolve_user_from_api_key") as resolve:
                resolve.return_value = make_user()
                client = build_app(auth_module, "verify_auth")
                resp = client.get("/protected", headers={"X-API-Key": "not-the-admin-key"})
        assert resp.status_code == 200
        resolve.assert_called_once()

    def test_admin_api_key_unset_does_not_match_empty_header(self, auth_module):
        """With no ADMIN_API_KEY configured, an empty key must not authenticate.

        AUTH_DISABLED is pinned false here so the assertion is about the key
        check itself and cannot be satisfied by an ambient env var instead.
        """
        with patch.object(auth_module, "AUTH_DISABLED", False):
            with patch.object(auth_module, "ADMIN_API_KEY", ""):
                with patch.object(auth_module, "_resolve_user_from_api_key") as resolve:
                    resolve.side_effect = auth_module.HTTPException(
                        status_code=401, detail="Invalid API key."
                    )
                    client = build_app(auth_module, "verify_auth")
                    resp = client.get("/protected", headers={"X-API-Key": ""})
        assert resp.status_code == 401

    def test_bearer_token_takes_precedence_over_api_key(self, auth_module):
        with patch.object(auth_module, "_resolve_user_from_jwt") as from_jwt:
            with patch.object(auth_module, "_resolve_user_from_api_key") as from_key:
                from_jwt.return_value = make_user(name="jwt-user")
                client = build_app(auth_module, "verify_auth")
                resp = client.get(
                    "/protected",
                    headers={"Authorization": "Bearer tok", "X-API-Key": "key"},
                )
        assert resp.status_code == 200
        assert resp.json()["user"] == "jwt-user"
        from_key.assert_not_called()


# ---------------------------------------------------------------------------
# require_admin: role enforcement and fresh-deploy bootstrap
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_member_is_rejected_with_403_not_401(self, auth_module):
        """A known non-admin is a permission failure, not an auth failure."""
        with patch.object(auth_module, "_resolve_user_from_jwt") as from_jwt:
            from_jwt.return_value = make_user(role="member")
            client = build_app(auth_module, "require_admin")
            resp = client.get("/protected", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 403

    def test_admin_user_is_allowed(self, auth_module):
        with patch.object(auth_module, "_resolve_user_from_jwt") as from_jwt:
            from_jwt.return_value = make_user(role="admin")
            client = build_app(auth_module, "require_admin")
            resp = client.get("/protected", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200

    def test_admin_key_bootstraps_when_no_users_exist(self, auth_module):
        """A fresh deploy has an empty users table; the admin key must still work."""
        with patch.object(auth_module, "ADMIN_API_KEY", "a-long-admin-key-value"):
            with patch.object(auth_module, "_get_default_user", return_value=None):
                client = build_app(auth_module, "require_admin")
                resp = client.get(
                    "/protected", headers={"X-API-Key": "a-long-admin-key-value"}
                )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_admin_key_does_not_escalate_a_non_admin_default_user(self, auth_module):
        """If a default user exists and is not an admin, the key must not promote them."""
        with patch.object(auth_module, "ADMIN_API_KEY", "a-long-admin-key-value"):
            with patch.object(
                auth_module, "_get_default_user", return_value=make_user(role="member")
            ):
                client = build_app(auth_module, "require_admin")
                resp = client.get(
                    "/protected", headers={"X-API-Key": "a-long-admin-key-value"}
                )
        assert resp.status_code == 403

    def test_unauthenticated_is_401(self, auth_module):
        with patch.object(auth_module, "AUTH_DISABLED", False):
            client = build_app(auth_module, "require_admin")
            resp = client.get("/protected")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API key hashing
# ---------------------------------------------------------------------------


class TestApiKeyHashing:
    def test_generated_key_verifies_against_its_hash(self, auth_module):
        full_key, _prefix, hashed = auth_module.generate_api_key()
        assert auth_module.verify_api_key_hash(full_key, hashed)

    def test_wrong_key_does_not_verify(self, auth_module):
        _full_key, _prefix, hashed = auth_module.generate_api_key()
        assert not auth_module.verify_api_key_hash("some-other-key", hashed)

    def test_prefix_alone_does_not_verify(self, auth_module):
        """The stored prefix is a display label, not a credential."""
        _full_key, prefix, hashed = auth_module.generate_api_key()
        assert not auth_module.verify_api_key_hash(prefix, hashed)

    def test_prefix_is_a_visible_slice_of_the_key(self, auth_module):
        full_key, prefix, _hashed = auth_module.generate_api_key()
        assert full_key.startswith(prefix)
        assert len(prefix) < len(full_key)

    def test_keys_are_unique_across_calls(self, auth_module):
        keys = {auth_module.generate_api_key()[0] for _ in range(20)}
        assert len(keys) == 20

    def test_plaintext_key_is_not_recoverable_from_hash(self, auth_module):
        full_key, _prefix, hashed = auth_module.generate_api_key()
        assert full_key not in hashed


# ---------------------------------------------------------------------------
# consume_refresh_jti: rotation, and what a second presentation of one token does
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    from db import Base
    from models import RefreshTokenJti, User  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def issue_jti(db):
    """Write a refresh-token row and hand back its jti, as create_refresh_token would."""
    from models import RefreshTokenJti, User

    user = User(name="someone", email="someone@example.com", password_hash="x", role="admin")
    db.add(user)
    db.commit()

    def _issue(used_at: datetime | None = None, expires_in: timedelta = timedelta(days=30)) -> str:
        jti = uuid.uuid4()
        db.add(
            RefreshTokenJti(
                jti=jti,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + expires_in,
                used_at=used_at,
            )
        )
        db.commit()
        return str(jti)

    return _issue


class TestConsumeRefreshJti:
    def test_an_unused_token_is_accepted_and_marked_used(self, auth_module, db, issue_jti):
        from models import RefreshTokenJti

        jti = issue_jti()
        auth_module.consume_refresh_jti(jti, db)

        row = db.get(RefreshTokenJti, uuid.UUID(jti))
        assert row.used_at is not None

    def test_a_replay_inside_the_grace_window_is_forgiven(self, auth_module, db, issue_jti):
        """Two tabs, or one page load's parallel requests, present the same cookie.

        Refusing the second would sign the user out for doing nothing wrong — the
        failure that sent a correctly-authenticated user straight back to /login.
        """
        jti = issue_jti()
        auth_module.consume_refresh_jti(jti, db)
        auth_module.consume_refresh_jti(jti, db)  # must not raise

    def test_the_grace_window_does_not_slide(self, auth_module, db, issue_jti):
        """A replay is forgiven against the first use, not against the previous replay.

        Otherwise a spent token stays alive indefinitely, one call per window.
        """
        from models import RefreshTokenJti

        jti = issue_jti()
        auth_module.consume_refresh_jti(jti, db)
        first_use = db.get(RefreshTokenJti, uuid.UUID(jti)).used_at

        auth_module.consume_refresh_jti(jti, db)
        db.expire_all()
        assert db.get(RefreshTokenJti, uuid.UUID(jti)).used_at == first_use

    def test_a_replay_past_the_grace_window_is_rejected(self, auth_module, db, issue_jti):
        stale = datetime.now(timezone.utc) - auth_module.REFRESH_REPLAY_GRACE - timedelta(seconds=1)
        jti = issue_jti(used_at=stale)

        with pytest.raises(HTTPException) as excinfo:
            auth_module.consume_refresh_jti(jti, db)
        assert excinfo.value.status_code == 401

    def test_the_grace_window_is_short(self, auth_module):
        """It exists to cover concurrent requests, not to extend a token's life."""
        assert auth_module.REFRESH_REPLAY_GRACE <= timedelta(seconds=30)

    def test_an_expired_token_is_rejected_even_if_never_used(self, auth_module, db, issue_jti):
        jti = issue_jti(expires_in=timedelta(seconds=-1))

        with pytest.raises(HTTPException) as excinfo:
            auth_module.consume_refresh_jti(jti, db)
        assert excinfo.value.status_code == 401

    def test_an_expired_token_is_not_rescued_by_the_grace_window(self, auth_module, db, issue_jti):
        """Expiry outranks grace: a just-used token that has also expired stays dead."""
        jti = issue_jti(used_at=datetime.now(timezone.utc), expires_in=timedelta(seconds=-1))

        with pytest.raises(HTTPException) as excinfo:
            auth_module.consume_refresh_jti(jti, db)
        assert excinfo.value.status_code == 401

    def test_an_unknown_jti_is_rejected(self, auth_module, db):
        with pytest.raises(HTTPException) as excinfo:
            auth_module.consume_refresh_jti(str(uuid.uuid4()), db)
        assert excinfo.value.status_code == 401

    def test_a_malformed_jti_is_rejected_rather_than_raising(self, auth_module, db):
        """A non-UUID jti comes from a forged token; it must 401, not 500."""
        with pytest.raises(HTTPException) as excinfo:
            auth_module.consume_refresh_jti("not-a-uuid", db)
        assert excinfo.value.status_code == 401
