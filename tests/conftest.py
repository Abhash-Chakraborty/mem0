"""Shared fixtures for the repository test suite.

The server tests in this directory come from upstream, where the REST API is
guarded by a single ``MEM0_API_KEY``. This fork replaced that with JWT sessions
plus an admin key, so ``server.main`` refuses to import without ``JWT_SECRET``
and every request 401s unless a session exists. Upstream's assertions are about
parameter forwarding rather than authentication, so the fixture below opens the
auth gate for them; the fork's own auth semantics are covered separately in
``server/tests/test_auth.py``.
"""

from __future__ import annotations

import os

import pytest

# Values the server module reads at import time. Set before any test module is
# collected so importing server.main can never fail on a missing secret.
_SERVER_TEST_ENV = {
    "JWT_SECRET": "test-secret-at-least-sixteen-chars",
    "AUTH_DISABLED": "true",
    "POSTGRES_PASSWORD": "test-postgres-password",
    # Point at a host that refuses immediately rather than one that resolves
    # slowly; the import-time admin check opens a connection.
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_CONNECT_TIMEOUT": "1",
    "OPENAI_API_KEY": "test-placeholder",
    "MEM0_TELEMETRY": "false",
}

for _key, _value in _SERVER_TEST_ENV.items():
    os.environ.setdefault(_key, _value)


@pytest.fixture
def server_auth_disabled(monkeypatch):
    """Force the fork's auth layer open for a single test."""
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "")
