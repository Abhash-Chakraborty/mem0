"""The Dream API: what curation has done, and undoing any of it.

Every endpoint is read-only except revert and run-now. That ratio is the point:
Dream is a thing you supervise rather than operate, so the API is mostly about
making its decisions legible.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import dream_scheduler
import dream_services
from db import SessionLocal, get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from models import DreamAction, DreamRun, Project
from pydantic import BaseModel
from server_state import get_memory_instance
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tenancy import Scope, require_role, require_scope

router = APIRouter(prefix="/dream", tags=["dream"])


class RunItem(BaseModel):
    id: str
    kind: str
    status: str
    scope: Optional[dict] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    considered: int = 0
    acted: int = 0
    tokens_used: int = 0
    duration_ms: Optional[int] = None


class ActionItem(BaseModel):
    id: str
    run_id: str
    kind: str
    subject_memory_id: str
    object_memory_id: Optional[str] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    reverted_at: Optional[datetime] = None
    created_at: datetime
    # Hydrated live so the feed shows what each memory says now, not a copy
    # frozen at decision time.
    subject_text: Optional[str] = None
    object_text: Optional[str] = None


class DreamStatus(BaseModel):
    synthesis_enabled: bool
    thresholds: dict[str, Any]
    totals: dict[str, int]
    last_run_at: Optional[datetime] = None
    candidates: list[dict] = []


class RunNowRequest(BaseModel):
    entity_id: str


def _duration_ms(run: DreamRun) -> Optional[int]:
    if run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * 1000)


def _run_item(run: DreamRun) -> RunItem:
    return RunItem(
        id=str(run.id),
        kind=run.kind,
        status=run.status,
        scope=run.scope,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        considered=run.considered or 0,
        acted=run.acted or 0,
        tokens_used=run.tokens_used or 0,
        duration_ms=_duration_ms(run),
    )


@router.get("/status", response_model=DreamStatus)
def dream_status(scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    """Whether Dream is on, how it is tuned, and what it has done."""
    project = db.get(Project, scope.project_id)
    settings_blob = project.settings if project else None

    totals: dict[str, int] = {}
    for kind, count in db.execute(
        select(DreamAction.kind, func.count(DreamAction.id))
        .where(DreamAction.project_id == scope.project_id, DreamAction.reverted_at.is_(None))
        .group_by(DreamAction.kind)
    ).all():
        totals[kind] = count
    totals["reverted"] = (
        db.scalar(
            select(func.count(DreamAction.id)).where(
                DreamAction.project_id == scope.project_id, DreamAction.reverted_at.is_not(None)
            )
        )
        or 0
    )

    last_run = db.scalar(
        select(DreamRun.started_at)
        .where(DreamRun.project_id == scope.project_id)
        .order_by(DreamRun.started_at.desc())
        .limit(1)
    )

    try:
        candidates = dream_scheduler.candidate_entities(
            SessionLocal, get_memory_instance, scope.project_id
        )
    except Exception:
        # The store being unreachable must not blank the page - the run history
        # is still readable and is the more useful half.
        candidates = []

    return DreamStatus(
        synthesis_enabled=dream_services.enabled(settings_blob, dream_services.SYNTHESIS),
        thresholds=dream_services.config(settings_blob),
        totals=totals,
        last_run_at=last_run,
        candidates=candidates,
    )


@router.get("/runs", response_model=list[RunItem])
def list_runs(
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    kind: Optional[str] = Query(default=None),
):
    query = select(DreamRun).where(DreamRun.project_id == scope.project_id)
    if kind:
        query = query.where(DreamRun.kind == kind)
    rows = (
        db.execute(query.order_by(DreamRun.started_at.desc()).limit(limit)).scalars().all()
    )
    return [_run_item(row) for row in rows]


@router.get("/actions", response_model=list[ActionItem])
def list_actions(
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    kind: Optional[str] = Query(default=None),
    include_reverted: bool = Query(default=True),
):
    """What Dream decided, newest first, with both memories' current text."""
    query = select(DreamAction).where(DreamAction.project_id == scope.project_id)
    if kind:
        query = query.where(DreamAction.kind == kind)
    if not include_reverted:
        query = query.where(DreamAction.reverted_at.is_(None))

    rows = (
        db.execute(query.order_by(DreamAction.created_at.desc()).limit(limit)).scalars().all()
    )

    instance = get_memory_instance()
    texts: dict[str, Optional[str]] = {}

    def text_of(memory_id: Optional[str]) -> Optional[str]:
        if not memory_id:
            return None
        if memory_id not in texts:
            try:
                memory = instance.get(memory_id)
                texts[memory_id] = memory.get("memory") if isinstance(memory, dict) else None
            except Exception:
                texts[memory_id] = None
        return texts[memory_id]

    return [
        ActionItem(
            id=str(row.id),
            run_id=str(row.run_id),
            kind=row.kind,
            subject_memory_id=row.subject_memory_id,
            object_memory_id=row.object_memory_id,
            confidence=row.confidence,
            rationale=row.rationale,
            reverted_at=row.reverted_at,
            created_at=row.created_at,
            subject_text=text_of(row.subject_memory_id),
            object_text=text_of(row.object_memory_id),
        )
        for row in rows
    ]


@router.post("/actions/{action_id}/revert", response_model=dict)
def revert_action(
    action_id: str,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Undo one decision. The action row stays, marked reverted."""
    try:
        parsed = uuid.UUID(action_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Action not found.")

    ok, message = dream_services.revert(db, parsed, scope.project_id)
    if not ok:
        raise HTTPException(status_code=404 if "not found" in message.lower() else 400, detail=message)
    return {"reverted": True, "message": message}


@router.post("/synthesize", response_model=RunItem)
def run_synthesis_now(
    body: RunNowRequest,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Run synthesis for one entity immediately, ignoring the cadence window.

    Synchronous, unlike the scheduled path: someone who pressed a button is
    waiting for an answer, and a fire-and-forget response saying nothing would
    be worse than the wait.
    """
    project = db.get(Project, scope.project_id)
    if not dream_services.enabled(project.settings if project else None, dream_services.SYNTHESIS):
        raise HTTPException(
            status_code=400,
            detail="Synthesis is switched off for this project. Enable it in Settings → Retention.",
        )

    run = dream_scheduler.synthesize_now(
        SessionLocal, get_memory_instance, scope.project_id, body.entity_id
    )
    return _run_item(run)
