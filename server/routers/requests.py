"""The Requests API: what happened, to whom, and what came of it.

Three endpoints, one filter set. `_apply_filters` is shared between the list and
the histogram so the chart above the table can never disagree with the table
below it - the classic bug in this shape of page, where the bars are drawn from
a different query than the rows.

Everything is scoped to the caller's project. Traces written before migration
013 have a null project_id; those are visible to the default project only, for
the same reason unstamped memories are (see tenancy.visible_to).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from models import RequestLog
from pydantic import BaseModel
from server_state import get_memory_instance
from sqlalchemy import Select, Text, func, or_, select
from sqlalchemy.orm import Session
from tenancy import Scope, require_role, require_scope, visible_to

import query_syntax

router = APIRouter(prefix="/requests", tags=["requests"])

MAX_PAGE = 200
DEFAULT_PAGE = 50
# Buckets the histogram will choose between. The range decides which: a day of
# traffic in daily buckets is one bar, a year in hourly buckets is 8,760.
BUCKET_CHOICES = (
    (timedelta(hours=6), "minute", 5),
    (timedelta(days=2), "hour", 1),
    (timedelta(days=14), "hour", 6),
    (timedelta(days=90), "day", 1),
)
FALLBACK_BUCKET = ("week", 1)


class Entity(BaseModel):
    type: str
    id: str


class RequestListItem(BaseModel):
    id: uuid.UUID
    request_id: Optional[str] = None
    method: str
    path: str
    request_type: Optional[str] = None
    status_code: int
    latency_ms: float
    auth_type: str
    entities: list[Entity] = []
    event_count: int = 0
    is_playground: bool = False
    error: Optional[str] = None
    created_at: datetime


class RequestPage(BaseModel):
    items: list[RequestListItem]
    next_cursor: Optional[str] = None
    total: int


class RequestDetail(RequestListItem):
    payload: Optional[Any] = None
    result_summary: Optional[Any] = None
    memory_ids: list[str] = []
    # Hydrated live from memory_ids rather than stored, so the panel shows what
    # a memory says now, not what it said when the request ran.
    memories: list[dict[str, Any]] = []
    project_id: Optional[uuid.UUID] = None


class HistogramBucket(BaseModel):
    bucket: datetime
    counts: dict[str, int]
    total: int


class HistogramResponse(BaseModel):
    buckets: list[HistogramBucket]
    interval: str
    total: int


def _scoped(scope: Scope) -> Any:
    """The project predicate for a trace query.

    Rows written before migration 013 carry no project. They belong to the
    default project, matching how unstamped memories are treated - anything
    else would make the whole pre-upgrade history vanish.
    """
    if scope.is_default_project:
        return or_(RequestLog.project_id == scope.project_id, RequestLog.project_id.is_(None))
    return RequestLog.project_id == scope.project_id


def _apply_filters(
    stmt: Select,
    scope: Scope,
    *,
    types: Optional[list[str]],
    status: Optional[str],
    entity_type: Optional[str],
    entity_id: Optional[str],
    has_results: Optional[bool],
    hide_playground: bool,
    method: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    q: Optional[str],
) -> Select:
    """The one place a Requests filter is expressed.

    Shared by the list and the histogram. If they filtered separately, the chart
    and the table would drift apart on the next filter anyone added.
    """
    stmt = stmt.where(_scoped(scope))

    parsed = query_syntax.parse(q) if q else query_syntax.EMPTY
    types = types or parsed.types or None
    status = status or parsed.status
    entity_type = entity_type or parsed.entity_type
    entity_id = entity_id or parsed.entity_id
    method = method or parsed.method

    if types:
        stmt = stmt.where(RequestLog.request_type.in_(types))
    if method:
        stmt = stmt.where(RequestLog.method == method.upper())
    if status == "succeeded":
        stmt = stmt.where(RequestLog.status_code < 400)
    elif status == "failed":
        stmt = stmt.where(RequestLog.status_code >= 400)
    if has_results is True:
        stmt = stmt.where(RequestLog.event_count > 0)
    elif has_results is False:
        stmt = stmt.where(RequestLog.event_count == 0)
    if hide_playground:
        stmt = stmt.where(RequestLog.is_playground.is_(False))
    if since:
        stmt = stmt.where(RequestLog.created_at >= since)
    if until:
        stmt = stmt.where(RequestLog.created_at <= until)

    if entity_id:
        # The entities column is a JSON array of {type,id}. Matching on the
        # rendered text is not elegant, but it is one predicate that works on
        # both Postgres and SQLite, and the GIN index still narrows the scan.
        needle = f'"id": "{entity_id}"'
        alt = f'"id":"{entity_id}"'
        stmt = stmt.where(
            or_(
                func.cast(RequestLog.entities, Text).contains(needle),
                func.cast(RequestLog.entities, Text).contains(alt),
            )
        )
    if entity_type:
        needle = f'"type": "{entity_type}"'
        alt = f'"type":"{entity_type}"'
        stmt = stmt.where(
            or_(
                func.cast(RequestLog.entities, Text).contains(needle),
                func.cast(RequestLog.entities, Text).contains(alt),
            )
        )

    if parsed.text:
        # Free text falls through to path and payload, which is where a request
        # someone half-remembers is actually findable.
        like = f"%{parsed.text}%"
        stmt = stmt.where(
            or_(
                RequestLog.path.ilike(like),
                func.cast(RequestLog.payload, Text).ilike(like),
            )
        )

    return stmt


def _item(row: RequestLog) -> RequestListItem:
    return RequestListItem(
        id=row.id,
        request_id=row.request_id,
        method=row.method,
        path=row.path,
        request_type=row.request_type,
        status_code=row.status_code,
        latency_ms=row.latency_ms,
        auth_type=row.auth_type,
        entities=[Entity(**e) for e in (row.entities or []) if isinstance(e, dict) and "type" in e and "id" in e],
        event_count=row.event_count or 0,
        is_playground=bool(row.is_playground),
        error=row.error,
        created_at=row.created_at,
    )


@router.get("", response_model=RequestPage)
def list_requests(
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    limit: int = Query(default=DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    cursor: Optional[str] = Query(default=None, description="created_at of the last row seen"),
    type: Optional[list[str]] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(succeeded|failed)$"),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    has_results: Optional[bool] = Query(default=None),
    hide_playground: bool = Query(default=False),
    method: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None, alias="from"),
    until: Optional[datetime] = Query(default=None, alias="to"),
    q: Optional[str] = Query(default=None),
):
    """Traces in the caller's project, newest first.

    Keyset pagination on created_at, not offset: an offset page shifts under
    you as new requests arrive, which on a live log is constant.
    """
    filters = dict(
        types=type,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        has_results=has_results,
        hide_playground=hide_playground,
        method=method,
        since=since,
        until=until,
        q=q,
    )

    stmt = _apply_filters(select(RequestLog), scope, **filters)
    if cursor:
        try:
            stmt = stmt.where(RequestLog.created_at < datetime.fromisoformat(cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor.")

    rows = db.execute(stmt.order_by(RequestLog.created_at.desc()).limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    total = db.scalar(
        _apply_filters(select(func.count(RequestLog.id)), scope, **filters)
    ) or 0

    return RequestPage(
        items=[_item(row) for row in rows],
        next_cursor=rows[-1].created_at.isoformat() if has_more and rows else None,
        total=total,
    )


def _pick_interval(since: datetime, until: datetime) -> tuple[str, int]:
    span = until - since
    for threshold, unit, size in BUCKET_CHOICES:
        if span <= threshold:
            return unit, size
    return FALLBACK_BUCKET


def _floor(moment: datetime, unit: str, size: int) -> datetime:
    """Round a timestamp down to its bucket.

    Done in Python rather than with date_trunc so the same code runs on SQLite
    in the tests, and so a 5-minute or 6-hour bucket - which date_trunc has no
    unit for - works the same way as an hourly one.
    """
    moment = moment.astimezone(timezone.utc)
    if unit == "minute":
        return moment.replace(second=0, microsecond=0, minute=(moment.minute // size) * size)
    if unit == "hour":
        return moment.replace(minute=0, second=0, microsecond=0, hour=(moment.hour // size) * size)
    if unit == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_of_day - timedelta(days=start_of_day.weekday())


@router.get("/histogram", response_model=HistogramResponse)
def request_histogram(
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    type: Optional[list[str]] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(succeeded|failed)$"),
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    has_results: Optional[bool] = Query(default=None),
    hide_playground: bool = Query(default=False),
    method: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None, alias="from"),
    until: Optional[datetime] = Query(default=None, alias="to"),
    q: Optional[str] = Query(default=None),
):
    """Counts per time bucket, split by request type.

    Uses the same `_apply_filters` as the list, so the bars always sum to the
    table's total for the same range.
    """
    now = datetime.now(timezone.utc)
    window_end = until or now
    window_start = since or (window_end - timedelta(days=7))
    unit, size = _pick_interval(window_start, window_end)

    filters = dict(
        types=type,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        has_results=has_results,
        hide_playground=hide_playground,
        method=method,
        since=window_start,
        until=window_end,
        q=q,
    )

    # Aggregate in the database, not in Python. Reading every row to count it
    # is fine at a thousand traces and 350ms at ten thousand, and "all time" on
    # a busy instance is a query someone will absolutely run.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        truncated = func.date_trunc(unit, RequestLog.created_at)
        stmt = _apply_filters(
            select(truncated.label("bucket"), RequestLog.request_type, func.count().label("n")),
            scope,
            **filters,
        ).group_by(truncated, RequestLog.request_type)
        rows = [(bucket, request_type, count) for bucket, request_type, count in db.execute(stmt).all()]
    else:
        # SQLite has no date_trunc. The test suite runs here, where the row
        # counts are small enough that reading them is free.
        stmt = _apply_filters(select(RequestLog.created_at, RequestLog.request_type), scope, **filters)
        rows = [(created_at, request_type, 1) for created_at, request_type in db.execute(stmt).all()]

    grouped: dict[datetime, dict[str, int]] = {}
    total = 0
    for created_at, request_type, count in rows:
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        # date_trunc has no 5-minute or 6-hour unit, so multi-unit buckets are
        # folded here - over the already-aggregated rows, not the raw ones.
        key = _floor(created_at, unit, size)
        bucket = grouped.setdefault(key, {})
        label = request_type or "other"
        bucket[label] = bucket.get(label, 0) + count
        total += count

    buckets = [
        HistogramBucket(bucket=key, counts=counts, total=sum(counts.values()))
        for key, counts in sorted(grouped.items())
    ]
    return HistogramResponse(
        buckets=buckets,
        interval=f"{size}{unit[0]}" if size > 1 else unit,
        total=total,
    )


@router.get("/{log_id}", response_model=RequestDetail)
def get_request(
    log_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """One trace, with its memories hydrated from the store.

    The memories are fetched live rather than read from the trace, so the panel
    shows what a memory says now. A memory that has since been edited or deleted
    is more informative than a stale copy claiming otherwise.
    """
    try:
        row = db.get(RequestLog, uuid.UUID(log_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Request not found.")
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found.")

    in_scope = row.project_id == scope.project_id or (row.project_id is None and scope.is_default_project)
    if not in_scope:
        raise HTTPException(status_code=404, detail="Request not found.")

    memories: list[dict[str, Any]] = []
    memory_ids = [m for m in (row.memory_ids or []) if isinstance(m, str)]
    if memory_ids:
        try:
            instance = get_memory_instance()
            for memory_id in memory_ids[:50]:
                try:
                    memory = instance.get(memory_id)
                except Exception:
                    memory = None
                if memory is None:
                    memories.append({"id": memory_id, "deleted": True})
                elif visible_to(memory, scope):
                    memories.append(memory)
        except Exception:
            # A store that is down must not take the trace panel with it - the
            # rest of the trace is still the useful part.
            memories = [{"id": memory_id, "unavailable": True} for memory_id in memory_ids[:50]]

    base = _item(row)
    return RequestDetail(
        **base.model_dump(),
        payload=row.payload,
        result_summary=row.result_summary,
        memory_ids=memory_ids,
        memories=memories,
        project_id=row.project_id,
    )


@router.delete("", response_model=dict)
def purge_requests(
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
    older_than_days: int = Query(default=0, ge=0, le=3650),
):
    """Delete traces in this project. Requires admin.

    `older_than_days=0` clears everything; anything else keeps the recent window.
    """
    stmt = select(RequestLog.id).where(_scoped(scope))
    if older_than_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        stmt = stmt.where(RequestLog.created_at < cutoff)

    ids = db.execute(stmt).scalars().all()
    if ids:
        db.execute(RequestLog.__table__.delete().where(RequestLog.id.in_(ids)))
        db.commit()
    return {"deleted": len(ids)}
