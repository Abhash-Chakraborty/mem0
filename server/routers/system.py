"""System health: one endpoint that answers "is this instance healthy?".

Every probe is individually guarded. A health page that 500s because one
subsystem is down is useless precisely when it is needed, so each section
degrades to a status of "unknown" with the reason attached rather than
failing the whole response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

import backup_services
import log_stream
import settings
from auth import require_admin, verify_auth
from db import engine, get_db
from models import Backup, RequestLog, WebhookDelivery
from server_state import get_memory_instance

router = APIRouter(prefix="/system", tags=["system"])
logger = logging.getLogger(__name__)

PROCESS_STARTED_AT = time.time()

# Disk below this is called out as a problem rather than reported neutrally.
DISK_WARN_PERCENT = 85.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _probe(name: str, fn):
    """Run one health probe, converting any failure into a reported status."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a probe must never break the page
        logger.warning("Health probe %r failed", name, exc_info=True)
        return {"status": "unknown", "error": str(exc)}


def _database() -> dict[str, Any]:
    started = time.perf_counter()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    pool = engine.pool
    # Not every pool implementation exposes every counter.
    stats = {}
    for attr in ("size", "checkedin", "checkedout", "overflow"):
        getter = getattr(pool, attr, None)
        if callable(getter):
            try:
                stats[attr] = getter()
            except Exception:  # noqa: BLE001
                pass

    in_use = stats.get("checkedout")
    capacity = stats.get("size")
    saturated = bool(in_use is not None and capacity and in_use >= capacity)

    return {
        "status": "degraded" if saturated else "ok",
        "latency_ms": latency_ms,
        "pool": stats,
        "host": settings.POSTGRES_HOST,
    }


def _disk() -> dict[str, Any]:
    target = backup_services.BACKUP_DIR if backup_services.BACKUP_DIR.exists() else "/"
    usage = shutil.disk_usage(str(target))
    used_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    return {
        "status": "degraded" if used_percent >= DISK_WARN_PERCENT else "ok",
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": used_percent,
    }


def _memory_store() -> dict[str, Any]:
    instance = get_memory_instance()
    count = None
    try:
        rows = instance.vector_store.list(limit=1)
        # Different stores return either a list or a (list, cursor) pair.
        if isinstance(rows, tuple):
            rows = rows[0]
        count = len(rows) if rows is not None else 0
    except Exception:  # noqa: BLE001 - reachability matters more than the count
        logger.debug("Vector store count probe failed", exc_info=True)
    return {
        "status": "ok",
        "collection": os.environ.get("POSTGRES_COLLECTION_NAME", "memories"),
        "reachable": True,
        "sample_rows": count,
    }


def _webhooks(db: Session) -> dict[str, Any]:
    pending = db.scalar(select(func.count(WebhookDelivery.id)).where(WebhookDelivery.status == "pending")) or 0
    failed = db.scalar(select(func.count(WebhookDelivery.id)).where(WebhookDelivery.status == "failed")) or 0
    return {
        # A queue with failures is not healthy, but it is not an outage either.
        "status": "degraded" if failed else "ok",
        "pending": pending,
        "failed": failed,
    }


def _requests(db: Session) -> dict[str, Any]:
    since = _utcnow() - timedelta(hours=24)
    total = db.scalar(select(func.count(RequestLog.id)).where(RequestLog.created_at >= since)) or 0
    errors = (
        db.scalar(
            select(func.count(RequestLog.id)).where(
                RequestLog.created_at >= since, RequestLog.status_code >= 500
            )
        )
        or 0
    )
    p95 = db.scalar(
        select(func.percentile_cont(0.95).within_group(RequestLog.latency_ms)).where(
            RequestLog.created_at >= since
        )
    )
    error_rate = round(errors / total * 100, 2) if total else 0.0
    return {
        "status": "degraded" if error_rate > 1.0 else "ok",
        "window_hours": 24,
        "total": total,
        "errors": errors,
        "error_rate_percent": error_rate,
        "latency_p95_ms": round(p95, 2) if p95 is not None else None,
    }


def _backups(db: Session) -> dict[str, Any]:
    missing = backup_services.missing_tools()
    latest = db.scalars(
        select(Backup).where(Backup.status == "completed").order_by(Backup.started_at.desc()).limit(1)
    ).first()

    if missing:
        status = "unavailable"
    elif latest is None:
        # No backup at all is the most dangerous state this page can report.
        status = "critical"
    else:
        age = _utcnow() - latest.started_at
        status = "degraded" if age > timedelta(days=2) else "ok"

    return {
        "status": status,
        "missing_tools": missing,
        "latest": backup_services.serialize(latest) if latest else None,
        "retention_count": backup_services.RETENTION_COUNT,
    }


def _providers() -> dict[str, Any]:
    """Report which provider credentials are present. Never echo the values."""
    return {
        "status": "ok" if os.environ.get("OPENAI_API_KEY") else "degraded",
        "llm_model": settings.DEFAULT_LLM_MODEL,
        "embedder_model": settings.DEFAULT_EMBEDDER_MODEL,
        "category_model": settings.CATEGORY_MODEL,
        "configured": {
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "gemini": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }


# Sections whose failure means the instance is not serving correctly. A stale
# backup is serious but does not make the running API unhealthy.
CRITICAL_SECTIONS = ("database", "memory_store")


@router.get("/health")
def system_health(_admin=Depends(require_admin), db: Session = Depends(get_db)):
    sections = {
        "database": _probe("database", _database),
        "disk": _probe("disk", _disk),
        "memory_store": _probe("memory_store", _memory_store),
        "webhooks": _probe("webhooks", lambda: _webhooks(db)),
        "requests": _probe("requests", lambda: _requests(db)),
        "backups": _probe("backups", lambda: _backups(db)),
        "providers": _probe("providers", _providers),
    }

    if any(sections[name]["status"] not in {"ok"} for name in CRITICAL_SECTIONS):
        overall = "critical"
    elif any(section["status"] in {"critical"} for section in sections.values()):
        overall = "critical"
    elif any(section["status"] in {"degraded", "unavailable", "unknown"} for section in sections.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "uptime_seconds": int(time.time() - PROCESS_STARTED_AT),
        "generated_at": _utcnow().isoformat(),
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def _core_version() -> str:
    """Version of the vendored mem0 core actually loaded into this process."""
    try:
        from importlib.metadata import version

        return version("mem0ai")
    except Exception:  # noqa: BLE001 - an unknown version must not 500 the probe
        return "unknown"


@router.get("/version")
def system_version(_auth=Depends(verify_auth)):
    """Identify the running build.

    Deliberately available to any authenticated caller, not admins only: the
    dashboard footer renders this for every role, and comparing the build the
    dashboard was compiled from against the one the API reports is how a
    half-finished deploy gets noticed.
    """
    return {
        "version": settings.APP_VERSION,
        "git_sha": settings.GIT_SHA,
        "built_at": settings.BUILT_AT,
        "python": platform.python_version(),
        "mem0_core": _core_version(),
        "started_at": datetime.fromtimestamp(PROCESS_STARTED_AT, tz=timezone.utc).isoformat(),
        "uptime_seconds": int(time.time() - PROCESS_STARTED_AT),
    }


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/logs")
def recent_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    level: str | None = Query(default=None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    _admin=Depends(require_admin),
):
    """Snapshot of the in-memory log buffer, for the initial page render."""
    return {"logs": log_stream.snapshot(limit=limit, level=level), "buffer_size": log_stream.BUFFER_SIZE}


@router.get("/logs/stream")
async def stream_logs(request: Request, _admin=Depends(require_admin)):
    """Server-sent events carrying log records as they are emitted."""

    queue = log_stream.subscribe()

    async def events():
        try:
            # Comment frame: makes proxies flush headers so the client's
            # connection opens immediately rather than on the first log line.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    # Heartbeat so idle connections are not reaped mid-stream.
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(entry)}\n\n"
        finally:
            log_stream.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx buffers proxied responses by default, which would hold the
            # stream until the buffer filled.
            "X-Accel-Buffering": "no",
        },
    )
