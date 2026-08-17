"""Memory lifecycle: what state a memory is in, and how often it is used.

The OSS core has none of this. `decay=True` raises outright, and
supersede / merge / latest_only exist only in the hosted client. So the state
lives here, in Postgres, where it is inspectable in SQL and every transition
carries a reason and an actor.

Two rules run through the whole module:

1. **Absence means active.** A memory with no lifecycle row is active; one with
   no access row has never been read. Nothing is backfilled, so these tables
   stay proportional to what has happened rather than to how many memories
   exist, and the layer can be switched on mid-flight.

2. **Filtering happens after the SDK returns.** The state is not in the vector
   store, so it cannot be a query predicate. Reads over-fetch and trim, the
   same mechanism project scoping uses.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models import MemoryAccess, MemoryFeedback, MemoryLifecycle, PatternSource

logger = logging.getLogger(__name__)

ACTIVE = "active"
SUPERSEDED = "superseded"
MERGED = "merged"
PATTERN = "pattern"
EXPIRED = "expired"

STATES = (ACTIVE, SUPERSEDED, MERGED, PATTERN, EXPIRED)

# Who caused a transition. Recorded so a surprising change can be traced to
# Dream rather than assumed to be a bug.
ACTORS = ("dream", "user", "system")

RATINGS = ("good", "bad")
# The quick reasons the feedback control offers. Free-text notes are separate;
# these exist so the common cases are countable.
FEEDBACK_REASONS = (
    "no_strong_match",
    "could_not_save",
    "conflicting",
    "outdated",
    "wrong_entity",
)

RECENT_ACCESS_LIMIT = 20


@dataclass(frozen=True)
class ReadMode:
    """Which lifecycle states a read should return.

    Named rather than passed as three booleans because the combinations that
    make sense are few, and the ones that do not - "merged but not active" -
    should not be expressible.
    """

    name: str
    states: frozenset[str]
    # Superseded memories are shown with a badge in the default mode rather
    # than hidden: a contradicted fact is still what the system believed, and
    # silently dropping it makes the history unexplainable.
    badge_superseded: bool = False


DEFAULT_MODE = ReadMode("default", frozenset({ACTIVE, SUPERSEDED, PATTERN}), badge_superseded=True)
LATEST_ONLY = ReadMode("latest_only", frozenset({ACTIVE, PATTERN}))
INCLUDE_MERGED = ReadMode("include_merged", frozenset(STATES))


def read_mode(latest_only: bool = False, include_merged: bool = False) -> ReadMode:
    """Pick a read mode. `include_merged` wins, since it is the widest."""
    if include_merged:
        return INCLUDE_MERGED
    if latest_only:
        return LATEST_ONLY
    return DEFAULT_MODE


# --------------------------------------------------------------- reading


def states_for(db: Session, memory_ids: Iterable[str]) -> dict[str, MemoryLifecycle]:
    """Lifecycle rows for the given ids, keyed by id. Missing ids are absent."""
    ids = [m for m in memory_ids if m]
    if not ids:
        return {}
    rows = db.execute(select(MemoryLifecycle).where(MemoryLifecycle.memory_id.in_(ids))).scalars().all()
    return {row.memory_id: row for row in rows}


def state_of(row: Optional[MemoryLifecycle]) -> str:
    return row.state if row is not None else ACTIVE


def annotate(memories: list[dict[str, Any]], lifecycle: dict[str, MemoryLifecycle]) -> list[dict[str, Any]]:
    """Attach lifecycle to each memory, without hiding anything.

    Every memory gets a `lifecycle` key even when it has no row, so the client
    never has to distinguish "active" from "we did not look".
    """
    out = []
    for memory in memories:
        memory_id = str(memory.get("id") or "")
        row = lifecycle.get(memory_id)
        out.append(
            {
                **memory,
                "lifecycle": {
                    "state": state_of(row),
                    "superseded_by": row.superseded_by if row else None,
                    "merged_into": row.merged_into if row else None,
                    "reason": row.reason if row else None,
                    "actor": row.actor if row else None,
                    "changed_at": row.changed_at.isoformat() if row and row.changed_at else None,
                },
            }
        )
    return out


def apply_read_mode(
    db: Session,
    response: Any,
    mode: ReadMode,
    top_k: Optional[int] = None,
) -> Any:
    """Filter and annotate an SDK response by lifecycle state.

    Preserves the response envelope, the same way tenancy.scope_results does,
    so callers can chain the two without either needing to know the other's
    shape.
    """
    if isinstance(response, dict) and isinstance(response.get("results"), list):
        results = _filter(db, response["results"], mode, top_k)
        return {**response, "results": results}
    if isinstance(response, list):
        return _filter(db, response, mode, top_k)
    return response


def _filter(
    db: Session,
    memories: list[Any],
    mode: ReadMode,
    top_k: Optional[int],
) -> list[Any]:
    rows = [m for m in memories if isinstance(m, dict)]
    lifecycle = states_for(db, [str(m.get("id") or "") for m in rows])
    kept = [m for m in rows if state_of(lifecycle.get(str(m.get("id") or ""))) in mode.states]
    annotated = annotate(kept, lifecycle)
    return annotated[:top_k] if top_k is not None else annotated


# --------------------------------------------------------------- writing


def set_state(
    db: Session,
    memory_id: str,
    project_id: Optional[uuid.UUID],
    state: str,
    *,
    reason: Optional[str] = None,
    actor: str = "system",
    superseded_by: Optional[str] = None,
    merged_into: Optional[str] = None,
    commit: bool = True,
) -> MemoryLifecycle:
    """Move a memory to a new state, creating its row if this is the first change.

    Every transition carries a reason and an actor. A Dream decision nobody can
    explain afterwards is one nobody will trust enough to leave switched on.
    """
    if state not in STATES:
        raise ValueError(f"Unknown lifecycle state: {state!r}")

    now = datetime.now(timezone.utc)
    row = db.get(MemoryLifecycle, memory_id)
    if row is None:
        row = MemoryLifecycle(memory_id=memory_id, project_id=project_id, created_at=now)
        db.add(row)

    row.state = state
    row.actor = actor
    row.reason = reason
    row.changed_at = now
    if project_id is not None:
        row.project_id = project_id
    # Cleared when moving away, so a memory restored to active does not keep
    # pointing at whatever once replaced it.
    row.superseded_by = superseded_by if state == SUPERSEDED else None
    row.merged_into = merged_into if state == MERGED else None

    if commit:
        db.commit()
    return row


def record_access(
    db: Session,
    memory_ids: Iterable[str],
    project_id: Optional[uuid.UUID],
    commit: bool = True,
) -> int:
    """Count a read against each memory returned.

    Called after a search or a get, never inside the request path's critical
    section - a failure here must cost a missing statistic, not a failed read.
    """
    ids = [m for m in dict.fromkeys(memory_ids) if m]
    if not ids:
        return 0

    now = datetime.now(timezone.utc)
    existing = {
        row.memory_id: row
        for row in db.execute(select(MemoryAccess).where(MemoryAccess.memory_id.in_(ids))).scalars().all()
    }

    for memory_id in ids:
        row = existing.get(memory_id)
        if row is None:
            row = MemoryAccess(
                memory_id=memory_id,
                project_id=project_id,
                access_count=0,
                first_access_at=now,
                recent=[],
            )
            db.add(row)
        row.access_count = (row.access_count or 0) + 1
        row.last_access_at = now
        if row.first_access_at is None:
            row.first_access_at = now
        if project_id is not None and row.project_id is None:
            row.project_id = project_id
        recent = list(row.recent or [])
        recent.append(now.isoformat())
        # Newest kept, oldest dropped: the shape of recent use is what decay
        # reads, and an unbounded list is a row that grows forever.
        row.recent = recent[-RECENT_ACCESS_LIMIT:]

    if commit:
        db.commit()
    return len(ids)


def access_for(db: Session, memory_ids: Iterable[str]) -> dict[str, MemoryAccess]:
    ids = [m for m in memory_ids if m]
    if not ids:
        return {}
    rows = db.execute(select(MemoryAccess).where(MemoryAccess.memory_id.in_(ids))).scalars().all()
    return {row.memory_id: row for row in rows}


def add_feedback(
    db: Session,
    memory_id: str,
    project_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    rating: str,
    note: Optional[str] = None,
    reasons: Optional[list[str]] = None,
) -> MemoryFeedback:
    """Record a verdict. Append-only - changing your mind is a new row."""
    if rating not in RATINGS:
        raise ValueError(f"Rating must be one of {RATINGS}, got {rating!r}")

    clean_reasons = [r for r in (reasons or []) if r in FEEDBACK_REASONS]
    row = MemoryFeedback(
        memory_id=memory_id,
        project_id=project_id,
        user_id=user_id,
        rating=rating,
        note=(note or "").strip()[:2000] or None,
        reasons=clean_reasons or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def feedback_for(db: Session, memory_id: str) -> list[MemoryFeedback]:
    return (
        db.execute(
            select(MemoryFeedback)
            .where(MemoryFeedback.memory_id == memory_id)
            .order_by(MemoryFeedback.created_at.desc())
        )
        .scalars()
        .all()
    )


def forget(db: Session, memory_ids: Iterable[str], commit: bool = True) -> int:
    """Drop every trace of a deleted memory from these tables.

    There is no foreign key to cascade from - the memories are not in this
    database - so the cascade is here. Missing it would leave lifecycle rows
    that outlive their memory and reappear as ghosts the next time an id was
    reused.
    """
    ids = [m for m in memory_ids if m]
    if not ids:
        return 0

    db.execute(delete(MemoryLifecycle).where(MemoryLifecycle.memory_id.in_(ids)))
    db.execute(delete(MemoryAccess).where(MemoryAccess.memory_id.in_(ids)))
    db.execute(delete(MemoryFeedback).where(MemoryFeedback.memory_id.in_(ids)))
    db.execute(delete(PatternSource).where(PatternSource.pattern_memory_id.in_(ids)))
    db.execute(delete(PatternSource).where(PatternSource.source_memory_id.in_(ids)))
    # A memory that superseded another is gone; the one it replaced should not
    # keep pointing at a dead id.
    for row in (
        db.execute(select(MemoryLifecycle).where(MemoryLifecycle.superseded_by.in_(ids))).scalars().all()
    ):
        row.superseded_by = None
        row.state = ACTIVE
        row.reason = "The memory that superseded this one was deleted."
        row.actor = "system"
        row.changed_at = datetime.now(timezone.utc)

    if commit:
        db.commit()
    return len(ids)


def counts_by_state(db: Session, project_id: Optional[uuid.UUID]) -> dict[str, int]:
    """How many memories are in each non-active state.

    Active is not counted here: it is the absence of a row, so counting it
    would mean counting the vector store instead.
    """
    query = select(MemoryLifecycle.state, MemoryLifecycle.memory_id)
    if project_id is not None:
        query = query.where(MemoryLifecycle.project_id == project_id)
    out: dict[str, int] = {}
    for state, _ in db.execute(query).all():
        out[state] = out.get(state, 0) + 1
    return out
