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
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


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
        """With no ADMIN_API_KEY configured, an empty key must not authenticate."""
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
