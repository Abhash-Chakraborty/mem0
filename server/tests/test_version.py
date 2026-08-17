"""Tests for GET /system/version.

The endpoint exists so a running instance can say which commit it was built
from. Two properties matter and are asserted here: the values come from the
build-time settings (not from whatever is checked out), and any authenticated
role can read it - the dashboard footer renders for readers too, and gating it
behind admin would silently blank the badge for them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def build_client(monkeypatch, *, role="reader", version="1.2.0", sha="a3f91c2", built_at="2026-08-17T10:00:00Z"):
    import settings
    from auth import verify_auth
    from routers import system as system_module

    monkeypatch.setattr(settings, "APP_VERSION", version)
    monkeypatch.setattr(settings, "GIT_SHA", sha)
    monkeypatch.setattr(settings, "BUILT_AT", built_at)

    app = FastAPI()
    app.include_router(system_module.router)
    app.dependency_overrides[verify_auth] = lambda: SimpleNamespace(role=role)
    return TestClient(app)


def test_version_reports_build_identity(monkeypatch):
    client = build_client(monkeypatch)

    resp = client.get("/system/version")
    assert resp.status_code == 200
    body = resp.json()

    assert body["version"] == "1.2.0"
    assert body["git_sha"] == "a3f91c2"
    assert body["built_at"] == "2026-08-17T10:00:00Z"


def test_version_includes_runtime_facts(monkeypatch):
    client = build_client(monkeypatch)

    body = client.get("/system/version").json()

    # Python version is read from the interpreter, so it is never "unknown".
    assert body["python"].count(".") >= 2
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0
    assert body["started_at"].endswith("+00:00")
    # mem0_core degrades to "unknown" rather than raising when metadata is absent.
    assert isinstance(body["mem0_core"], str)


@pytest.mark.parametrize("role", ["admin", "member", "reader"])
def test_version_readable_by_every_role(monkeypatch, role):
    client = build_client(monkeypatch, role=role)
    assert client.get("/system/version").status_code == 200


def test_version_defaults_are_honest_when_unset(monkeypatch):
    """An image built outside Compose must say so, not invent a version."""
    client = build_client(monkeypatch, version="dev", sha="unknown", built_at="unknown")

    body = client.get("/system/version").json()
    assert body["version"] == "dev"
    assert body["git_sha"] == "unknown"
