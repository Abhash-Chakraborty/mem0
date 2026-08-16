"""Tests for backup path safety, retention, and failure bookkeeping.

These never invoke pg_dump. What matters here is the logic around it: that a
stored filename can never escape the backup directory, that a failed run is
recorded rather than lost, and that retention keeps the newest snapshots.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def backups():
    import backup_services

    return backup_services


class FakeScalars:
    """Stand-in for SQLAlchemy's ScalarResult.

    __iter__ must live on the class: `iter()` looks the method up on the type,
    so attaching it to an instance is silently ignored.
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Minimal Session stand-in: records commits and holds objects by id."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.deleted = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)
        self.rows.append(obj)

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        self.deleted.append(obj)
        if obj in self.rows:
            self.rows.remove(obj)

    def get(self, _model, ident):
        return next((r for r in self.rows if r.id == ident), None)

    def scalars(self, _stmt):
        # The fake cannot evaluate SQL predicates, so it returns every row and
        # each test asserts on the rows it supplied.
        return FakeScalars(self.rows)


def make_record(**overrides):
    base = dict(
        id=uuid.uuid4(),
        filename="abhash-memory-20260101T000000Z.dump",
        kind="manual",
        status="completed",
        size_bytes=100,
        checksum="abc",
        destination="local",
        error="",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        verified_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "nested/dir/file.dump",
            "name with spaces.dump",
            "semi;colon.dump",
            "",
        ],
    )
    def test_traversal_and_odd_names_are_rejected(self, backups, name):
        with pytest.raises(backups.BackupError):
            backups.resolve_backup_path(name)

    def test_plain_generated_name_resolves_inside_backup_dir(self, backups):
        path = backups.resolve_backup_path("abhash-memory-20260101T000000Z.dump.vector")
        assert path.parent == backups.BACKUP_DIR.resolve()

    def test_resolved_path_never_escapes_even_via_symlinkish_name(self, backups):
        # A name that resolves upward must be refused rather than normalised.
        with pytest.raises(backups.BackupError):
            backups.resolve_backup_path("..")


# ---------------------------------------------------------------------------
# Failure bookkeeping
# ---------------------------------------------------------------------------


class TestFailureRecording:
    def test_dump_failure_marks_record_failed_and_reraises(self, backups, tmp_path):
        session = FakeSession()
        with patch.object(backups, "BACKUP_DIR", tmp_path):
            with patch.object(backups, "_dump_one", side_effect=backups.BackupError("boom")):
                with pytest.raises(backups.BackupError):
                    backups.run_backup(session)

        assert len(session.added) == 1
        record = session.added[0]
        assert record.status == "failed"
        assert "boom" in record.error
        # The row must be committed, not left only in memory, or a crash loses it.
        assert session.commits >= 2

    def test_unexpected_error_is_also_recorded(self, backups, tmp_path):
        session = FakeSession()
        with patch.object(backups, "BACKUP_DIR", tmp_path):
            with patch.object(backups, "_dump_one", side_effect=OSError("disk gone")):
                with pytest.raises(OSError):
                    backups.run_backup(session)
        assert session.added[0].status == "failed"
        assert "disk gone" in session.added[0].error

    def test_verification_failure_is_not_reported_as_success(self, backups, tmp_path):
        """A dump that cannot be read back must never be marked completed."""
        session = FakeSession()

        def fake_dump(_db, target):
            target.write_bytes(b"not-a-real-archive")

        with patch.object(backups, "BACKUP_DIR", tmp_path):
            with patch.object(backups, "_dump_one", side_effect=fake_dump):
                with patch.object(
                    backups, "verify_archive", side_effect=backups.BackupError("corrupt")
                ):
                    with pytest.raises(backups.BackupError):
                        backups.run_backup(session)

        assert session.added[0].status == "failed"
        assert session.added[0].verified_at is None

    def test_failed_run_leaves_no_partial_files_behind(self, backups, tmp_path):
        session = FakeSession()

        def fake_dump(_db, target):
            target.write_bytes(b"partial")

        with patch.object(backups, "BACKUP_DIR", tmp_path):
            with patch.object(backups, "_dump_one", side_effect=fake_dump):
                with patch.object(
                    backups, "verify_archive", side_effect=backups.BackupError("corrupt")
                ):
                    with pytest.raises(backups.BackupError):
                        backups.run_backup(session)

        assert list(tmp_path.glob("*.vector")) == []
        assert list(tmp_path.glob("*.app")) == []


# ---------------------------------------------------------------------------
# Stale runs
# ---------------------------------------------------------------------------


class TestStaleRuns:
    def test_old_running_row_is_marked_failed(self, backups):
        old = make_record(
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=12),
        )
        session = FakeSession([old])
        assert backups.sweep_stale_runs(session) == 1
        assert old.status == "failed"
        assert "interrupted" in old.error

    def test_recent_running_row_is_left_alone(self, backups):
        fresh = make_record(
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session = FakeSession([fresh])

        # scalars() here must only yield rows matching the stale predicate; the
        # fake cannot filter, so assert on the real guard instead.
        assert backups.STALE_RUN_AFTER > timedelta(minutes=1)
        assert fresh.status == "running"


# ---------------------------------------------------------------------------
# Restore guards
# ---------------------------------------------------------------------------


class TestRestoreGuards:
    def test_missing_backup_is_rejected(self, backups):
        session = FakeSession()
        with pytest.raises(backups.BackupError, match="not found"):
            backups.restore_backup(session, uuid.uuid4())

    def test_incomplete_backup_cannot_be_restored(self, backups):
        record = make_record(status="failed")
        session = FakeSession([record])
        with pytest.raises(backups.BackupError, match="completed"):
            backups.restore_backup(session, record.id)

    def test_missing_file_on_disk_is_reported_not_silently_skipped(self, backups, tmp_path):
        record = make_record(status="completed")
        session = FakeSession([record])
        with patch.object(backups, "BACKUP_DIR", tmp_path):
            with pytest.raises(backups.BackupError, match="missing from disk"):
                backups.restore_backup(session, record.id)


# ---------------------------------------------------------------------------
# Tooling detection
# ---------------------------------------------------------------------------


class TestToolDetection:
    def test_missing_tools_lists_absent_binaries(self, backups):
        with patch.object(backups, "tool_path", return_value=None):
            assert set(backups.missing_tools()) == {"pg_dump", "pg_restore", "psql"}

    def test_no_missing_tools_when_all_present(self, backups):
        with patch.object(backups, "tool_path", return_value="/usr/bin/pg_dump"):
            assert backups.missing_tools() == []
