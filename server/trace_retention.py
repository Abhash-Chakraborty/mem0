"""Keep request_logs from becoming the largest table in the database.

Storing payloads turns a narrow log into the widest table here, so the sweep
ships alongside the capture rather than "later" - a trace table with no expiry
is a disk-space incident with a delay fuse.

Retention is per project, read from the same `projects.settings` blob every
other project setting lives in. A project with no setting gets DEFAULT_DAYS;
setting it to 0 means keep forever, which is a real choice for a low-traffic
instance and is not the default.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select

import project_settings
from models import Project, RequestLog

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30
# Deleted in chunks so a first sweep over a long-neglected instance does not
# take one enormous lock on the table the API is still writing to.
BATCH_SIZE = 5_000
MAX_BATCHES = 200


def retention_days(settings_blob: dict | None) -> int:
    """Trace retention for one project, in days. 0 means keep forever."""
    value = project_settings.section(settings_blob, "retention").get("trace_retention_days")
    if value is None:
        return DEFAULT_DAYS
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(0, days)


def sweep_project(session, project_id, days: int) -> int:
    """Delete this project's traces older than `days`. Returns how many went."""
    if days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    for _ in range(MAX_BATCHES):
        ids = (
            session.execute(
                select(RequestLog.id)
                .where(RequestLog.project_id == project_id, RequestLog.created_at < cutoff)
                .limit(BATCH_SIZE)
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        session.execute(RequestLog.__table__.delete().where(RequestLog.id.in_(ids)))
        session.commit()
        deleted += len(ids)
        if len(ids) < BATCH_SIZE:
            break
    return deleted


def sweep_orphans(session, days: int = DEFAULT_DAYS) -> int:
    """Traces with no project - written before migration 013 - age out too.

    They are readable from the default project, so leaving them forever would
    quietly defeat retention on the one instance most likely to have upgraded
    into it.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ids = (
        session.execute(
            select(RequestLog.id)
            .where(RequestLog.project_id.is_(None), RequestLog.created_at < cutoff)
            .limit(BATCH_SIZE)
        )
        .scalars()
        .all()
    )
    if not ids:
        return 0
    session.execute(RequestLog.__table__.delete().where(RequestLog.id.in_(ids)))
    session.commit()
    return len(ids)


def run_sweep(session_factory: Callable) -> int:
    """Sweep every project. Called from the scheduler; never raises."""
    total = 0
    try:
        with session_factory() as session:
            projects = session.execute(select(Project)).scalars().all()
            for project in projects:
                try:
                    total += sweep_project(session, project.id, retention_days(project.settings))
                except Exception:
                    session.rollback()
                    logger.exception("Trace sweep failed for project %s", project.id)
            try:
                total += sweep_orphans(session)
            except Exception:
                session.rollback()
                logger.exception("Trace sweep failed for unassigned traces")
    except Exception:
        logger.exception("Trace retention sweep failed")
    if total:
        logger.info("Trace retention sweep removed %d request logs", total)
    return total
