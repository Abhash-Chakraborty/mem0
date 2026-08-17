"""The overview: four numbers, two series, and where each of them comes from.

Every figure here is computed from the same tables the detail pages read, with
the same filters, so a card and the page it links to cannot disagree. That is
the whole design constraint - an overview whose totals do not reconcile with the
pages beneath it is worse than no overview, because it teaches people not to
trust either.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from db import get_db
from fastapi import APIRouter, Depends, Query
from feature_services import attach_categories, list_memories
from models import Category, MemoryCategory, RequestLog
from pydantic import BaseModel
from server_state import get_memory_instance
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from tenancy import Scope, require_scope, scope_results

import lifecycle_services

router = APIRouter(prefix="/analytics", tags=["analytics"])

RANGE_DAYS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}

# Which request types count as a retrieval versus a write. Named here because
# "retrieval event" is not self-evident, and the dashboard shows this same
# definition on hover.
RETRIEVAL_TYPES = ("search", "get", "get_all")
ADD_TYPES = ("add",)


class SeriesPoint(BaseModel):
    date: str
    counts: dict[str, int]
    total: int


class Overview(BaseModel):
    total_memories: int
    active_entities: int
    retrieval_events: int
    add_events: int
    categorized_memories: int
    lifecycle_counts: dict[str, int]
    requests_series: list[SeriesPoint]
    entities_series: list[SeriesPoint]
    category_distribution: list[dict[str, Any]]
    range: str
    start: Optional[str]
    end: Optional[str]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_window(
    range_key: str, start: Optional[str], end: Optional[str]
) -> tuple[Optional[datetime], Optional[datetime]]:
    explicit_start = _parse_date(start)
    explicit_end = _parse_date(end)
    if explicit_start or explicit_end:
        return explicit_start, explicit_end

    days = RANGE_DAYS.get(range_key)
    if days is None:
        return None, None
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days), now


def _scoped(scope: Scope):
    """Traces written before migration 013 have no project; the default owns them."""
    if scope.is_default_project:
        return or_(RequestLog.project_id == scope.project_id, RequestLog.project_id.is_(None))
    return RequestLog.project_id == scope.project_id


def _bucket(moment: datetime, daily: bool) -> str:
    moment = moment.astimezone(timezone.utc)
    if daily:
        return moment.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return moment.replace(minute=0, second=0, microsecond=0).isoformat()


def _series(
    db: Session,
    scope: Scope,
    start: Optional[datetime],
    end: Optional[datetime],
    daily: bool,
) -> tuple[list[SeriesPoint], int, int]:
    """Request counts per bucket, split by type, plus the two headline totals.

    One pass, so the cards and the chart are computed from the same rows and
    cannot drift apart.
    """
    query = select(RequestLog.created_at, RequestLog.request_type).where(_scoped(scope))
    if start:
        query = query.where(RequestLog.created_at >= start)
    if end:
        query = query.where(RequestLog.created_at <= end)

    grouped: dict[str, dict[str, int]] = {}
    retrievals = 0
    adds = 0

    for created_at, request_type in db.execute(query).all():
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        label = request_type or "other"
        bucket = grouped.setdefault(_bucket(created_at, daily), {})
        bucket[label] = bucket.get(label, 0) + 1
        if label in RETRIEVAL_TYPES:
            retrievals += 1
        elif label in ADD_TYPES:
            adds += 1

    points = [
        SeriesPoint(date=key, counts=counts, total=sum(counts.values()))
        for key, counts in sorted(grouped.items())
    ]
    return points, retrievals, adds


def _entity_series(
    memories: list[dict], start: Optional[datetime], end: Optional[datetime], daily: bool
) -> tuple[list[SeriesPoint], int]:
    """Distinct entities seen per bucket, and how many are active overall.

    Counted from the memories rather than from traces, because an entity exists
    because a memory mentions it - a request about someone who has no memories
    has not made them an entity.
    """
    grouped: dict[str, set[str]] = {}
    everyone: set[str] = set()

    for memory in memories:
        created = _parse_date(memory.get("created_at"))
        if created is None:
            continue
        if start and created < start:
            continue
        if end and created > end:
            continue
        key = _bucket(created, daily)
        for field, label in (("user_id", "user"), ("agent_id", "agent"), ("run_id", "session")):
            value = memory.get(field)
            if not value:
                continue
            marker = f"{label}:{value}"
            grouped.setdefault(key, set()).add(marker)
            everyone.add(marker)

    points = []
    for key, markers in sorted(grouped.items()):
        counts: dict[str, int] = {}
        for marker in markers:
            kind = marker.split(":", 1)[0]
            counts[kind] = counts.get(kind, 0) + 1
        points.append(SeriesPoint(date=key, counts=counts, total=len(markers)))

    return points, len(everyone)


@router.get("", response_model=Overview)
def get_analytics(
    range: str = Query(default="7d"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """Everything the overview page needs, for one project and one range."""
    start_dt, end_dt = _resolve_window(range, start, end)

    # Hourly buckets for a single day, daily otherwise. A day of traffic in
    # daily buckets is one bar; a month in hourly buckets is 720.
    daily = range != "1d"

    all_memories = scope_results(list_memories(get_memory_instance()), scope)
    memories = attach_categories(db, all_memories)

    in_range = [
        memory
        for memory in memories
        if _within(_parse_date(memory.get("created_at")), start_dt, end_dt)
    ]

    requests_series, retrievals, adds = _series(db, scope, start_dt, end_dt, daily)
    entities_series, active_entities = _entity_series(memories, start_dt, end_dt, daily)

    category_rows = db.execute(
        select(Category.name, Category.color, func.count(MemoryCategory.id))
        .join(MemoryCategory, MemoryCategory.category_id == Category.id, isouter=True)
        .where(Category.project_id == scope.project_id)
        .group_by(Category.id)
        .order_by(Category.name)
    ).all()

    return Overview(
        # Total memories is the whole project, not the range: "how much do I
        # have" is not a windowed question, and windowing it made the number
        # drop when someone narrowed the range, which read as data loss.
        total_memories=len(memories),
        active_entities=active_entities,
        retrieval_events=retrievals,
        add_events=adds,
        categorized_memories=len([m for m in in_range if m.get("categories")]),
        lifecycle_counts=lifecycle_services.counts_by_state(db, scope.project_id),
        requests_series=requests_series,
        entities_series=entities_series,
        category_distribution=[
            {"name": name, "color": color, "count": count} for name, color, count in category_rows
        ],
        range=range,
        start=start_dt.isoformat() if start_dt else None,
        end=end_dt.isoformat() if end_dt else None,
    )


def _within(moment: Optional[datetime], start: Optional[datetime], end: Optional[datetime]) -> bool:
    if moment is None:
        return start is None and end is None
    if start and moment < start:
        return False
    if end and moment > end:
        return False
    return True
