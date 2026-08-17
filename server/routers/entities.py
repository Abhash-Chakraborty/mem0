"""Entities: who this project has memories about, and which ids are the same person.

Entities are derived, not stored. There is no entity table - an entity exists
because a memory mentions it - so this router scans payloads and buckets them.
That is honest about where the truth lives, and it means an entity cannot drift
out of sync with the memories it describes.

Aliases are the exception: they *are* stored, because "these three ids are one
person" is a judgement nobody can derive from the data. The list collapses
aliases into their canonical, so linking three identifiers makes the count drop
by two rather than showing the same person three times.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import identity
import lifecycle_services
from db import get_db
from errors import upstream_error
from fastapi import APIRouter, Depends, HTTPException, Query
from models import EntityAlias, EntityProfile, RequestLog
from pydantic import BaseModel, Field
from schemas import MessageResponse
from server_state import get_memory_instance
from sqlalchemy import Text, func, or_, select
from sqlalchemy.orm import Session
from tenancy import Scope, require_role, require_scope, visible_to

router = APIRouter(prefix="/entities", tags=["entities"])

SCAN_LIMIT = 10_000

EntityType = Literal["user", "agent", "run", "app"]
TYPE_TO_FIELD: dict[str, str] = {
    "user": "user_id",
    "agent": "agent_id",
    "run": "run_id",
    "app": "app_id",
}


class Entity(BaseModel):
    id: str
    type: EntityType
    total_memories: int
    aliases: list[str] = []
    display_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EntityDetail(Entity):
    total_requests: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    note: Optional[str] = None
    lifecycle_counts: dict[str, int] = {}


class AliasRow(BaseModel):
    id: str
    entity_type: str
    canonical_id: str
    alias_id: str
    created_at: datetime


class LinkRequest(BaseModel):
    entity_type: EntityType
    canonical_id: str
    alias_ids: list[str] = Field(..., min_length=1)


class MergeRequest(LinkRequest):
    # Merge rewrites stored payloads and cannot be undone, so the caller has to
    # say so explicitly rather than discovering it afterwards.
    confirm: bool = False


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    note: Optional[str] = None


def _payloads(scope: Scope) -> list[dict[str, Any]]:
    """Every memory payload in this project."""
    results = get_memory_instance().vector_store.list(top_k=SCAN_LIMIT)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
    return [getattr(row, "payload", None) or {} for row in rows if visible_to(row, scope)]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _profiles(db: Session, scope: Scope) -> dict[tuple[str, str], EntityProfile]:
    rows = (
        db.execute(select(EntityProfile).where(EntityProfile.project_id == scope.project_id))
        .scalars()
        .all()
    )
    return {(row.entity_type, row.entity_id): row for row in rows}


@router.get("", response_model=list[Entity])
def list_entities(
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    type: Optional[EntityType] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    """Entities in this project, with aliases collapsed into their canonical.

    Counts are summed across aliases: after linking three identifiers the list
    shows one entity holding all their memories, not three holding a third each.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"total_memories": 0, "created_at": None, "updated_at": None}
    )

    for payload in _payloads(scope):
        created = _parse_timestamp(payload.get("created_at"))
        updated = _parse_timestamp(payload.get("updated_at")) or created

        for entity_type, field in TYPE_TO_FIELD.items():
            value = payload.get(field)
            if not value:
                continue
            canonical = identity.resolve(db, scope.project_id, entity_type, str(value))
            bucket = buckets[(entity_type, canonical)]
            bucket["total_memories"] += 1
            if created and (bucket["created_at"] is None or created < bucket["created_at"]):
                bucket["created_at"] = created
            if updated and (bucket["updated_at"] is None or updated > bucket["updated_at"]):
                bucket["updated_at"] = updated

    profiles = _profiles(db, scope)
    needle = (q or "").strip().lower()

    out: list[Entity] = []
    for (entity_type, entity_id), data in sorted(buckets.items()):
        if type and entity_type != type:
            continue
        profile = profiles.get((entity_type, entity_id))
        if needle and needle not in entity_id.lower() and needle not in (profile.display_name or "").lower():
            continue
        out.append(
            Entity(
                id=entity_id,
                type=entity_type,  # type: ignore[arg-type]
                total_memories=data["total_memories"],
                aliases=identity.aliases_of(db, scope.project_id, entity_type, entity_id),
                display_name=profile.display_name if profile else None,
                created_at=data["created_at"],
                updated_at=data["updated_at"],
            )
        )
    return out


@router.get("/links", response_model=list[AliasRow])
def list_links(scope: Scope = Depends(require_scope), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(EntityAlias)
            .where(EntityAlias.project_id == scope.project_id)
            .order_by(EntityAlias.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        AliasRow(
            id=str(row.id),
            entity_type=row.entity_type,
            canonical_id=row.canonical_id,
            alias_id=row.alias_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/links", response_model=list[AliasRow], status_code=201)
def create_links(
    body: LinkRequest,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Make several identifiers resolve to one. Reversible; memories untouched.

    This is the default way to combine entities because it is undoable and it
    keeps the record of which channel each memory arrived from.
    """
    try:
        created = identity.link(
            db,
            scope.project_id,
            body.entity_type,
            body.canonical_id,
            body.alias_ids,
            created_by=scope.user_id,
        )
    except identity.LinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return [
        AliasRow(
            id=str(row.id),
            entity_type=row.entity_type,
            canonical_id=row.canonical_id,
            alias_id=row.alias_id,
            created_at=row.created_at,
        )
        for row in created
    ]


@router.delete("/links/{link_id}", response_model=MessageResponse)
def delete_link(
    link_id: str,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Unlink. The previous split returns and no memory is lost."""
    try:
        removed = identity.unlink(db, scope.project_id, uuid.UUID(link_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Link not found.")
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found.")
    return MessageResponse(message="Entities unlinked.")


@router.post("/merge", response_model=dict)
def merge_entities(
    body: MergeRequest,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Rewrite the identifier in every matching memory, then link.

    Unlike a link this is not reversible: the stored payloads change, and the
    record of which channel each memory came from is replaced by a note in
    metadata. Requires `confirm`, because a caller who did not mean it should
    get an error rather than an irreversible rewrite.

    Idempotent: running it twice finds nothing left to rewrite the second time.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Merging rewrites stored memories and cannot be undone. Set confirm=true to proceed.",
        )

    field = TYPE_TO_FIELD[body.entity_type]
    canonical = identity.resolve(db, scope.project_id, body.entity_type, body.canonical_id)
    targets = {a.strip() for a in body.alias_ids if a and a.strip() != canonical}
    if not targets:
        return {"rewritten": 0, "canonical_id": canonical, "aliases": []}

    instance = get_memory_instance()
    rewritten = 0
    try:
        results = instance.vector_store.list(top_k=SCAN_LIMIT)
        rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
        for row in rows:
            if not visible_to(row, scope):
                continue
            payload = getattr(row, "payload", None) or {}
            value = payload.get(field)
            if not value or str(value) not in targets:
                continue
            metadata = {k: v for k, v in payload.items() if k not in _RESERVED}
            sources = dict(metadata.get(identity.SOURCE_KEY) or {})
            sources[field] = str(value)
            metadata[identity.SOURCE_KEY] = sources
            metadata[field] = canonical
            metadata["project_id"] = str(scope.project_id)
            instance.update(memory_id=str(getattr(row, "id", "")), metadata=metadata)
            rewritten += 1
    except HTTPException:
        raise
    except Exception:
        raise upstream_error()

    # The alias rows still go in: a merged id should keep resolving, so a
    # client that has not caught up still lands on the right entity.
    try:
        identity.link(
            db, scope.project_id, body.entity_type, canonical, targets, created_by=scope.user_id
        )
    except identity.LinkError:
        # Already linked from a previous run. The rewrite above is the part
        # that matters, and it is idempotent.
        pass

    return {"rewritten": rewritten, "canonical_id": canonical, "aliases": sorted(targets)}


_RESERVED = {"data", "hash", "created_at", "updated_at", "expiration_date"}


@router.get("/{entity_type}/{entity_id}", response_model=EntityDetail)
def get_entity(
    entity_type: EntityType,
    entity_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    """One entity's stats, counted across every identifier that resolves here."""
    canonical = identity.resolve(db, scope.project_id, entity_type, entity_id)
    ids = set(identity.expand(db, scope.project_id, entity_type, canonical))
    field = TYPE_TO_FIELD[entity_type]

    total = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    memory_ids: list[str] = []

    for payload in _payloads(scope):
        if str(payload.get(field) or "") not in ids:
            continue
        total += 1
        if payload.get("hash"):
            memory_ids.append(str(payload["hash"]))
        created = _parse_timestamp(payload.get("created_at"))
        updated = _parse_timestamp(payload.get("updated_at")) or created
        if created and (first_seen is None or created < first_seen):
            first_seen = created
        if updated and (last_seen is None or updated > last_seen):
            last_seen = updated

    if total == 0 and not identity.aliases_of(db, scope.project_id, entity_type, canonical):
        raise HTTPException(status_code=404, detail="Entity not found.")

    # Requests are matched on the rendered entity JSON, the same predicate the
    # Requests page uses, so both agree on what "about alice" means.
    request_count = 0
    for candidate in ids:
        request_count += (
            db.scalar(
                select(func.count(RequestLog.id)).where(
                    RequestLog.project_id == scope.project_id,
                    or_(
                        func.cast(RequestLog.entities, Text).contains(f'"id": "{candidate}"'),
                        func.cast(RequestLog.entities, Text).contains(f'"id":"{candidate}"'),
                    ),
                )
            )
            or 0
        )

    profile = _profiles(db, scope).get((entity_type, canonical))

    return EntityDetail(
        id=canonical,
        type=entity_type,
        total_memories=total,
        total_requests=request_count,
        aliases=identity.aliases_of(db, scope.project_id, entity_type, canonical),
        display_name=profile.display_name if profile else None,
        note=profile.note if profile else None,
        first_seen=first_seen,
        last_seen=last_seen,
        created_at=first_seen,
        updated_at=last_seen,
        lifecycle_counts=lifecycle_services.counts_by_state(db, scope.project_id),
    )


@router.get("/{entity_type}/{entity_id}/memories", response_model=dict)
def entity_memories(
    entity_type: EntityType,
    entity_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """This entity's memories, gathered across every identifier that resolves here."""
    ids = set(identity.expand(db, scope.project_id, entity_type, entity_id))
    field = TYPE_TO_FIELD[entity_type]

    instance = get_memory_instance()
    try:
        results = instance.vector_store.list(top_k=SCAN_LIMIT)
    except Exception:
        raise upstream_error()
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []

    memories = []
    for row in rows:
        if not visible_to(row, scope):
            continue
        payload = getattr(row, "payload", None) or {}
        if str(payload.get(field) or "") not in ids:
            continue
        memories.append(
            {
                "id": str(getattr(row, "id", "")),
                "memory": payload.get("data"),
                "user_id": payload.get("user_id"),
                "agent_id": payload.get("agent_id"),
                "run_id": payload.get("run_id"),
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
                "metadata": {k: v for k, v in payload.items() if k not in _RESERVED},
            }
        )
        if len(memories) >= limit:
            break

    lifecycle = lifecycle_services.states_for(db, [m["id"] for m in memories])
    return {"results": lifecycle_services.annotate(memories, lifecycle)}


@router.get("/{entity_type}/{entity_id}/requests", response_model=dict)
def entity_requests(
    entity_type: EntityType,
    entity_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    """This entity's request traces, across every identifier that resolves here."""
    ids = identity.expand(db, scope.project_id, entity_type, entity_id)
    if not ids:
        return {"items": []}

    predicates = []
    for candidate in ids:
        predicates.append(func.cast(RequestLog.entities, Text).contains(f'"id": "{candidate}"'))
        predicates.append(func.cast(RequestLog.entities, Text).contains(f'"id":"{candidate}"'))

    rows = (
        db.execute(
            select(RequestLog)
            .where(RequestLog.project_id == scope.project_id, or_(*predicates))
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return {
        "items": [
            {
                "id": str(row.id),
                "request_type": row.request_type,
                "method": row.method,
                "path": row.path,
                "status_code": row.status_code,
                "latency_ms": row.latency_ms,
                "event_count": row.event_count,
                "entities": row.entities or [],
                "is_playground": bool(row.is_playground),
                "error": row.error,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.put("/{entity_type}/{entity_id}/profile", response_model=EntityDetail)
def update_profile(
    entity_type: EntityType,
    entity_id: str,
    body: ProfileUpdate,
    scope: Scope = Depends(require_role("member")),
    db: Session = Depends(get_db),
):
    """Give an opaque identifier a human name."""
    canonical = identity.resolve(db, scope.project_id, entity_type, entity_id)
    row = db.scalar(
        select(EntityProfile).where(
            EntityProfile.project_id == scope.project_id,
            EntityProfile.entity_type == entity_type,
            EntityProfile.entity_id == canonical,
        )
    )
    if row is None:
        row = EntityProfile(
            project_id=scope.project_id, entity_type=entity_type, entity_id=canonical
        )
        db.add(row)
    if body.display_name is not None:
        row.display_name = body.display_name.strip() or None
    if body.note is not None:
        row.note = body.note.strip() or None
    db.commit()
    return get_entity(entity_type, canonical, scope, db)


@router.delete("/{entity_type}/{entity_id}", response_model=MessageResponse)
def delete_entity(
    entity_type: EntityType,
    entity_id: str,
    scope: Scope = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Delete every memory for this entity, across all of its identifiers."""
    if entity_type == "app":
        # The SDK's delete_all only accepts user_id/agent_id/run_id; app_id is a
        # best-effort, read-only entity dimension with no bulk-delete support.
        raise HTTPException(status_code=400, detail="Deleting application entities is not supported")

    ids = identity.expand(db, scope.project_id, entity_type, entity_id)
    field = TYPE_TO_FIELD[entity_type]
    instance = get_memory_instance()
    deleted: list[str] = []

    try:
        results = instance.vector_store.list(top_k=SCAN_LIMIT)
        rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
        for row in rows:
            if not visible_to(row, scope):
                continue
            payload = getattr(row, "payload", None) or {}
            if str(payload.get(field) or "") not in ids:
                continue
            memory_id = str(getattr(row, "id", ""))
            # One at a time rather than delete_all: the SDK's bulk delete matches
            # on entity alone and would take another project's memories with it.
            instance.delete(memory_id=memory_id)
            deleted.append(memory_id)
    except Exception:
        raise upstream_error()

    if deleted:
        lifecycle_services.forget(db, deleted)

    return MessageResponse(message=f"Deleted {len(deleted)} memories for this entity")


@router.get("/{entity_type}/{entity_id}/aliases", response_model=list[str])
def entity_aliases(
    entity_type: EntityType,
    entity_id: str,
    scope: Scope = Depends(require_scope),
    db: Session = Depends(get_db),
):
    canonical = identity.resolve(db, scope.project_id, entity_type, entity_id)
    return identity.aliases_of(db, scope.project_id, entity_type, canonical)


def _now() -> datetime:
    return datetime.now(timezone.utc)
