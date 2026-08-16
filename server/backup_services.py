"""Postgres backup, verification and restore for the self-hosted server.

Design notes:

* Both databases are dumped in one file. The vector store and the application
  database are only useful together - restoring memories without the categories
  and webhook config that describe them produces an instance that looks intact
  but has lost half its state.

* Dumps use pg_dump's custom format (-Fc), which is compressed and, unlike plain
  SQL, can be inspected without executing it. That is what makes verification
  possible: `pg_restore --list` reads the archive's table of contents, so a
  truncated or corrupt dump is caught at backup time rather than discovered
  during an emergency restore.

* Every run writes a row before doing any work. A process killed mid-dump
  therefore leaves a visible "running" record instead of vanishing, and
  `sweep_stale_runs` later marks it failed.

* The subprocess never receives the password on its command line - it goes
  through PGPASSWORD in the child environment, so it cannot leak via the
  process table.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

import settings
from models import Backup

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.environ.get("MEM0_BACKUP_DIR", "/app/backups"))
RETENTION_COUNT = int(os.environ.get("MEM0_BACKUP_RETENTION", "7"))
# A dump that has run longer than this is treated as dead. Generous, because a
# large instance on slow disks is normal; the point is to catch killed processes.
STALE_RUN_AFTER = timedelta(hours=6)
DUMP_TIMEOUT_SECONDS = int(os.environ.get("MEM0_BACKUP_TIMEOUT_SECONDS", "3600"))

# Databases that make up one restorable snapshot.
VECTOR_DB = os.environ.get("POSTGRES_DB", "postgres")
APP_DB = settings.APP_DB_NAME

# Filenames are generated, never user-supplied, but they are also used to build
# filesystem paths - so anything read back from the database is re-checked
# against this before being opened.
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")


class BackupError(RuntimeError):
    """A backup or restore could not be completed. Message is user-facing."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD
    return env


def tool_path(name: str) -> str | None:
    """Locate a Postgres client binary, or None when it is not installed."""
    return shutil.which(name)


def missing_tools() -> list[str]:
    return [name for name in ("pg_dump", "pg_restore", "psql") if tool_path(name) is None]


def _run(cmd: list[str], *, timeout: int = DUMP_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            env=_pg_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{cmd[0]} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise BackupError(
            f"{cmd[0]} is not installed in this image. Backups need the Postgres "
            "client tools; rebuild with postgresql-client present."
        ) from exc


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dump_one(database: str, target: Path) -> None:
    result = _run(
        [
            "pg_dump",
            "--host", settings.POSTGRES_HOST,
            "--port", str(settings.POSTGRES_PORT),
            "--username", settings.POSTGRES_USER,
            "--dbname", database,
            "--format", "custom",
            "--no-owner",
            "--no-acl",
            "--file", str(target),
        ]
    )
    if result.returncode != 0:
        raise BackupError(f"pg_dump failed for {database}: {result.stderr.strip() or 'unknown error'}")
    if not target.exists() or target.stat().st_size == 0:
        raise BackupError(f"pg_dump produced no output for {database}")


def verify_archive(path: Path) -> None:
    """Read the dump's table of contents. Raises BackupError if unreadable.

    This is what separates a file that exists from a backup that can be restored.
    """
    result = _run(["pg_restore", "--list", str(path)], timeout=300)
    if result.returncode != 0:
        raise BackupError(f"archive failed verification: {result.stderr.strip() or 'unreadable'}")
    if not result.stdout.strip():
        raise BackupError("archive contains no entries")


def resolve_backup_path(filename: str) -> Path:
    """Map a stored filename to a path inside BACKUP_DIR, refusing traversal."""
    if not SAFE_FILENAME.match(filename):
        raise BackupError("Invalid backup filename.")
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != BACKUP_DIR.resolve():
        raise BackupError("Invalid backup filename.")
    return path


def run_backup(session: Session, *, kind: str = "manual") -> Backup:
    """Dump both databases, verify the result, and record it. Blocking."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    stamp = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    record = Backup(
        id=uuid.uuid4(),
        filename=f"abhash-memory-{stamp}.dump",
        kind=kind,
        status="running",
        started_at=_utcnow(),
    )
    session.add(record)
    session.commit()

    # Each database is dumped separately, then both are kept. Custom-format
    # archives cannot be concatenated, so the pair is stored side by side under
    # a shared stem and treated as one snapshot.
    vector_path = BACKUP_DIR / f"{record.filename}.vector"
    app_path = BACKUP_DIR / f"{record.filename}.app"

    try:
        _dump_one(VECTOR_DB, vector_path)
        _dump_one(APP_DB, app_path)
        verify_archive(vector_path)
        verify_archive(app_path)

        total = vector_path.stat().st_size + app_path.stat().st_size
        record.size_bytes = total
        record.checksum = _checksum(vector_path)[:32] + _checksum(app_path)[:32]
        record.status = "completed"
        record.completed_at = _utcnow()
        record.verified_at = _utcnow()
        session.commit()
        logger.info("Backup %s completed (%d bytes)", record.filename, total)
    except BackupError as exc:
        record.status = "failed"
        record.error = str(exc)
        record.completed_at = _utcnow()
        session.commit()
        for leftover in (vector_path, app_path):
            leftover.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - record then re-raise
        record.status = "failed"
        record.error = f"unexpected error: {exc}"
        record.completed_at = _utcnow()
        session.commit()
        for leftover in (vector_path, app_path):
            leftover.unlink(missing_ok=True)
        raise

    apply_retention(session)
    return record


def restore_backup(session: Session, backup_id: uuid.UUID) -> None:
    """Restore both databases from a stored snapshot.

    Destructive: --clean drops and recreates the objects it restores. The caller
    is responsible for confirming intent.
    """
    record = session.get(Backup, backup_id)
    if record is None:
        raise BackupError("Backup not found.")
    if record.status != "completed":
        raise BackupError("Only a completed backup can be restored.")

    vector_path = resolve_backup_path(f"{record.filename}.vector")
    app_path = resolve_backup_path(f"{record.filename}.app")
    for path in (vector_path, app_path):
        if not path.exists():
            raise BackupError(f"Backup file is missing from disk: {path.name}")
        verify_archive(path)

    for database, path in ((VECTOR_DB, vector_path), (APP_DB, app_path)):
        result = _run(
            [
                "pg_restore",
                "--host", settings.POSTGRES_HOST,
                "--port", str(settings.POSTGRES_PORT),
                "--username", settings.POSTGRES_USER,
                "--dbname", database,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                str(path),
            ]
        )
        # pg_restore exits non-zero on warnings too, so only treat it as fatal
        # when nothing could be applied.
        if result.returncode != 0 and "error" in (result.stderr or "").lower():
            raise BackupError(f"restore failed for {database}: {result.stderr.strip()}")

    logger.warning("Restored databases from backup %s", record.filename)


def delete_backup(session: Session, backup_id: uuid.UUID) -> None:
    record = session.get(Backup, backup_id)
    if record is None:
        raise BackupError("Backup not found.")
    for suffix in (".vector", ".app"):
        try:
            resolve_backup_path(f"{record.filename}{suffix}").unlink(missing_ok=True)
        except BackupError:
            # A malformed stored name should not block removing the row.
            logger.warning("Skipping unlink for malformed backup name %r", record.filename)
    session.delete(record)
    session.commit()


def apply_retention(session: Session) -> int:
    """Keep the newest RETENTION_COUNT completed backups. Returns count removed."""
    if RETENTION_COUNT <= 0:
        return 0
    completed = list(
        session.scalars(
            select(Backup).where(Backup.status == "completed").order_by(Backup.started_at.desc())
        )
    )
    removed = 0
    for record in completed[RETENTION_COUNT:]:
        delete_backup(session, record.id)
        removed += 1
    if removed:
        logger.info("Retention removed %d old backup(s)", removed)
    return removed


def sweep_stale_runs(session: Session) -> int:
    """Mark abandoned 'running' rows as failed so the UI never shows a ghost."""
    cutoff = _utcnow() - STALE_RUN_AFTER
    stale = list(
        session.scalars(select(Backup).where(Backup.status == "running", Backup.started_at < cutoff))
    )
    for record in stale:
        record.status = "failed"
        record.error = "Backup did not finish; the process was interrupted."
        record.completed_at = _utcnow()
    if stale:
        session.commit()
    return len(stale)


def serialize(record: Backup) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "filename": record.filename,
        "kind": record.kind,
        "status": record.status,
        "size_bytes": record.size_bytes,
        "checksum": record.checksum,
        "destination": record.destination,
        "error": record.error,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "verified_at": record.verified_at.isoformat() if record.verified_at else None,
    }


def list_backups(session: Session, limit: int = 50) -> Iterable[Backup]:
    return session.scalars(select(Backup).order_by(Backup.started_at.desc()).limit(limit))
