"""Shared pytest fixtures for the self-hosted server tests.

These tests exercise the API routers in isolation. They never touch a real
PostgreSQL instance or the mem0 runtime: the SQLAlchemy engine in ``db`` is
created lazily (no connection at import time) and the memory instance is
monkeypatched per test. Required env vars are set here so importing the modules
under test never fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# The server modules use flat imports (``import auth``, ``from routers import graph``),
# so the server directory must be importable as the top-level package root.
SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Provide harmless defaults so module-level config reads never blow up.
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-sixteen-chars")
os.environ.setdefault("AUTH_DISABLED", "false")
os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")
os.environ.setdefault("MEM0_TELEMETRY", "false")


@pytest.fixture
def make_row():
    """Build a fake vector-store row (object with ``.id`` and ``.payload``)."""
    from types import SimpleNamespace

    def _make_row(entity_id: str, data: str, entity_type: str, linked_memory_ids):
        return SimpleNamespace(
            id=entity_id,
            payload={
                "data": data,
                "entity_type": entity_type,
                "linked_memory_ids": list(linked_memory_ids),
            },
        )

    return _make_row
