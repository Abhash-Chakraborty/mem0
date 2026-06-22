from datetime import datetime, timedelta, timezone
from typing import Optional

from auth import require_admin
from db import get_db
from fastapi import APIRouter, Depends, Query
from feature_services import attach_categories, dashboard_metrics, list_memories
from models import Category, MemoryCategory
from server_state import get_memory_instance
from sqlalchemy import func, select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/analytics", tags=["analytics"])

RANGE_DAYS = {"1d": 1, "7d": 7, "30d": 30}


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _resolve_window(
    range_key: str, start: Optional[str], end: Optional[str]
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return (start, end) datetimes. Custom start/end win; else a preset; else all-time."""
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if start_dt or end_dt:
        # Make the end inclusive of the selected day.
        if end_dt is not None:
            end_dt = end_dt + timedelta(days=1)
        return start_dt, end_dt
    days = RANGE_DAYS.get(range_key)
    if days:
        now = datetime.now(timezone.utc)
        return now - timedelta(days=days), None
    return None, None  # all time


@router.get("")
def get_analytics(
    range: str = Query(default="all"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    _auth=Depends(require_admin),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _resolve_window(range, start, end)
    memories = attach_categories(db, list_memories(get_memory_instance()))

    metrics = dashboard_metrics(db, memories, start_dt, end_dt)

    category_rows = (
        db.execute(
            select(Category.name, Category.color, func.count(MemoryCategory.id))
            .join(MemoryCategory, MemoryCategory.category_id == Category.id, isouter=True)
            .group_by(Category.id)
            .order_by(Category.name)
        )
        .all()
    )

    return {
        **metrics,
        "range": range,
        "start": start_dt.isoformat() if start_dt else None,
        "end": end_dt.isoformat() if end_dt else None,
        "categorized_memories": len([memory for memory in memories if memory.get("categories")]),
        "category_distribution": [
            {"name": name, "color": color, "count": count} for name, color, count in category_rows
        ],
    }
