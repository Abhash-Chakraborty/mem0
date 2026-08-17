"""Lifecycle endpoints: feedback, state, and access.

Mounted under /memories/{id}/… so the URLs read as facts about a memory rather
than as a separate subsystem, which is what they are.

Every route confirms the memory is in the caller's project before touching a
lifecycle row. The lifecycle tables key on the SDK's memory id with no foreign
key, so nothing at the database level would stop one project writing feedback
on another's memory - the check has to be here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import lifecycle_services
from db import get_db
from errors import upstream_error
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from server_state import get_memory_instance
from sqlalchemy.orm import Session
from tenancy import Scope, require_role, require_scope, visible_to

router = APIRouter(prefix="/memories", tags=["lifecycle"])


class FeedbackCreate(BaseModel):
    rating: str = Field(..., description="good or bad")
    note: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)


class FeedbackItem(BaseModel):
    id: str
    memory_id: str
    rating: str
    note: Optional[str]
    reasons: list[str]
    created_at: datetime


class StateChange(BaseModel):
    state: str
    reason: Optional[str] = None
    superseded_by: Optional[str] = None
    merged_into: Optional[str] = None


class LifecycleOut(BaseModel):
    memory_id: str
    state: str
    superseded_by: Optional[str] = None
    merged_into: Optional[str] = None
    reason: Optional[str] = None
    actor: Optional[str] = None
    changed_at: Optional[datetime] = None
    access_count: int = 0
    last_access_at: Optional[datetime] = None
    feedback: list[FeedbackItem] = []


def _require_memory(memory_id: str, scope: Scope) -> dict[str, Any]:
    """404 unless this memory exists and belongs to the caller's project."""
    try:
        memory = get_memory_instance().get(memory_id)
    except Exception:
        raise upstream_error()
    if memory is None or not visible_to(memory, scope):
        raise HTTPException(status_code=404, detail="Memory not found.")
    return memory


def _feedback_items(rows) -> list[FeedbackItem]:
    return [
        FeedbackItem(
            id=str(row.id),
            memory_id=row.memory_id,
            rating=row.rating,
            note=row.note,
            reasons=list(row.reasons or []),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{memory_id}/lifecycle", response_model=LifecycleOut)
def get_lifecycle(
    memory_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """State, access counts and feedback for one memory."""
    _require_memory(memory_id, scope)

    row = lifecycle_services.states_for(db, [memory_id]).get(memory_id)
    access = lifecycle_services.access_for(db, [memory_id]).get(memory_id)

    return LifecycleOut(
        memory_id=memory_id,
        state=lifecycle_services.state_of(row),
        superseded_by=row.superseded_by if row else None,
        merged_into=row.merged_into if row else None,
        reason=row.reason if row else None,
        actor=row.actor if row else None,
        changed_at=row.changed_at if row else None,
        access_count=access.access_count if access else 0,
        last_access_at=access.last_access_at if access else None,
        feedback=_feedback_items(lifecycle_services.feedback_for(db, memory_id)),
    )


@router.put("/{memory_id}/lifecycle", response_model=LifecycleOut)
def set_lifecycle(
    memory_id: str,
    body: StateChange,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Move a memory to a different lifecycle state by hand.

    Admin-only, and recorded with `actor="user"` so a manual override is
    distinguishable from something Dream did. Restoring a superseded memory to
    active is the main reason this exists.
    """
    _require_memory(memory_id, scope)

    if body.state not in lifecycle_services.STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown state '{body.state}'. Expected one of: {', '.join(lifecycle_services.STATES)}.",
        )
    if body.state == lifecycle_services.SUPERSEDED and not body.superseded_by:
        raise HTTPException(
            status_code=400,
            detail="superseded_by is required when marking a memory superseded - "
            "a superseded memory with nothing to point at cannot be explained.",
        )
    if body.state == lifecycle_services.MERGED and not body.merged_into:
        raise HTTPException(
            status_code=400, detail="merged_into is required when marking a memory merged."
        )

    for target in (body.superseded_by, body.merged_into):
        if target:
            _require_memory(target, scope)

    lifecycle_services.set_state(
        db,
        memory_id,
        scope.project_id,
        body.state,
        reason=body.reason,
        actor="user",
        superseded_by=body.superseded_by,
        merged_into=body.merged_into,
    )
    return get_lifecycle(memory_id, scope, db)


@router.get("/{memory_id}/feedback", response_model=list[FeedbackItem])
def list_feedback(
    memory_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    _require_memory(memory_id, scope)
    return _feedback_items(lifecycle_services.feedback_for(db, memory_id))


@router.post("/{memory_id}/feedback", response_model=FeedbackItem, status_code=201)
def add_feedback(
    memory_id: str,
    body: FeedbackCreate,
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    """Record a verdict on a memory.

    Append-only: changing your mind writes a second row. The history of what
    people thought is the signal, not just the latest opinion.
    """
    _require_memory(memory_id, scope)

    unknown = [r for r in body.reasons if r not in lifecycle_services.FEEDBACK_REASONS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reason(s): {', '.join(unknown)}. "
            f"Expected: {', '.join(lifecycle_services.FEEDBACK_REASONS)}.",
        )

    try:
        row = lifecycle_services.add_feedback(
            db,
            memory_id,
            scope.project_id,
            scope.user_id,
            body.rating,
            body.note,
            body.reasons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _feedback_items([row])[0]
