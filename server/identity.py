"""Alias resolution: which identifiers are the same entity.

Two invariants make this cheap and unambiguous, and both are enforced on write
rather than checked on read:

1. **An alias points at exactly one canonical.** The unique constraint on
   (project, type, alias) says so. Resolution therefore has one answer.

2. **Chains are collapsed.** Linking C to B when B already resolves to A stores
   C to A, not C to B. Resolution is always one hop, a cycle is unrepresentable,
   and no read has to walk a graph.

Reads go two directions and both are needed. `resolve` maps an alias to its
canonical, for writes - so new memories stop fragmenting. `expand` maps a
canonical to itself plus every alias, for reads - so memories written before the
link are still found. Only doing the first would hide history; only doing the
second would keep creating it.

The per-project cache exists because resolution sits on the read path of every
memory query. It is invalidated wholesale on any link change: links are rare and
reads are constant, so a coarse invalidation is the right trade.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import EntityAlias

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("user", "agent", "run", "app")

# Where the original identifier is preserved when a write is redirected to a
# canonical. Nothing is lost; the payload just is not what the caller sent.
SOURCE_KEY = "source_entity_id"

_cache: dict[tuple[str, str], dict[str, str]] = {}
_cache_lock = threading.Lock()


def _cache_key(project_id: Optional[uuid.UUID], entity_type: str) -> tuple[str, str]:
    return (str(project_id), entity_type)


def invalidate(project_id: Optional[uuid.UUID] = None) -> None:
    """Drop cached resolution. Called on any link change.

    Wholesale rather than surgical: links change rarely and reads happen
    constantly, so the cost of over-invalidating is a few extra queries while
    the cost of under-invalidating is a stale identity.
    """
    with _cache_lock:
        if project_id is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == str(project_id)]:
                _cache.pop(key, None)


def _alias_map(db: Session, project_id: Optional[uuid.UUID], entity_type: str) -> dict[str, str]:
    """alias -> canonical for one project and entity type, cached."""
    key = _cache_key(project_id, entity_type)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    query = select(EntityAlias).where(EntityAlias.entity_type == entity_type)
    if project_id is not None:
        query = query.where(EntityAlias.project_id == project_id)
    mapping = {row.alias_id: row.canonical_id for row in db.execute(query).scalars().all()}

    with _cache_lock:
        _cache[key] = mapping
    return mapping


def resolve(db: Session, project_id: Optional[uuid.UUID], entity_type: str, entity_id: str) -> str:
    """The canonical identifier for one id. Returns the input when unlinked."""
    if not entity_id:
        return entity_id
    return _alias_map(db, project_id, entity_type).get(entity_id, entity_id)


def expand(db: Session, project_id: Optional[uuid.UUID], entity_type: str, entity_id: str) -> list[str]:
    """Every identifier that means this entity: the canonical plus its aliases.

    Reads filter on this rather than on the single id, so memories written
    before a link are still found under it.
    """
    if not entity_id:
        return []
    mapping = _alias_map(db, project_id, entity_type)
    canonical = mapping.get(entity_id, entity_id)
    ids = [canonical] + [alias for alias, target in mapping.items() if target == canonical]
    # dict.fromkeys rather than set(): the canonical must stay first so callers
    # that take ids[0] get the surviving identifier, not an arbitrary alias.
    return list(dict.fromkeys(ids))


def aliases_of(db: Session, project_id: Optional[uuid.UUID], entity_type: str, canonical_id: str) -> list[str]:
    mapping = _alias_map(db, project_id, entity_type)
    return sorted(alias for alias, target in mapping.items() if target == canonical_id)


def is_alias(db: Session, project_id: Optional[uuid.UUID], entity_type: str, entity_id: str) -> bool:
    return entity_id in _alias_map(db, project_id, entity_type)


class LinkError(ValueError):
    """A link that would break an invariant, with a reason a person can act on."""


def link(
    db: Session,
    project_id: Optional[uuid.UUID],
    entity_type: str,
    canonical_id: str,
    alias_ids: Iterable[str],
    created_by: Optional[uuid.UUID] = None,
) -> list[EntityAlias]:
    """Make `alias_ids` resolve to `canonical_id`.

    Rejects rather than silently repairs anything that would leave resolution
    ambiguous: linking an id to itself, linking an id that already points
    elsewhere, or a link that would reverse an existing one.

    Reversible by design - deleting the row restores the previous split, and
    the memories themselves are untouched.
    """
    if entity_type not in ENTITY_TYPES:
        raise LinkError(f"Unknown entity type '{entity_type}'.")
    canonical_id = (canonical_id or "").strip()
    if not canonical_id:
        raise LinkError("A canonical identifier is required.")

    mapping = _alias_map(db, project_id, entity_type)

    # If the chosen canonical is itself an alias, collapse to its target now.
    # Storing a two-hop chain would make resolution depend on walk order.
    requested_canonical = canonical_id
    canonical_id = mapping.get(canonical_id, canonical_id)

    created: list[EntityAlias] = []
    for raw in alias_ids:
        alias_id = (raw or "").strip()
        if not alias_id:
            continue
        if alias_id == canonical_id:
            # This also catches a reverse link: asking to make A an alias of B
            # when B already resolves to A collapses to "A is an alias of A".
            # The message names the resolution, because otherwise it mentions an
            # identifier the caller never typed.
            if requested_canonical != canonical_id:
                raise LinkError(
                    f"'{requested_canonical}' already resolves to '{canonical_id}', "
                    f"so linking '{alias_id}' to it would be a cycle."
                )
            raise LinkError(f"'{alias_id}' cannot be an alias of itself.")

        existing = mapping.get(alias_id)
        if existing == canonical_id:
            continue  # Already linked; linking again is a no-op, not an error.
        if existing is not None:
            raise LinkError(
                f"'{alias_id}' already resolves to '{existing}'. "
                f"Unlink it first if it should point at '{canonical_id}' instead."
            )
        # The reverse link would make two ids each other's canonical.
        if mapping.get(canonical_id) == alias_id:
            raise LinkError(
                f"'{canonical_id}' already resolves to '{alias_id}'. Linking them the other way would be a cycle."
            )

        row = EntityAlias(
            project_id=project_id,
            entity_type=entity_type,
            canonical_id=canonical_id,
            alias_id=alias_id,
            created_by=created_by,
        )
        db.add(row)
        created.append(row)
        mapping[alias_id] = canonical_id

        # Anything that pointed at the alias now points at the new canonical,
        # so the collapsed-chain invariant survives this link too.
        for other in db.execute(
            select(EntityAlias).where(
                EntityAlias.entity_type == entity_type,
                EntityAlias.canonical_id == alias_id,
                *( [EntityAlias.project_id == project_id] if project_id is not None else [] ),
            )
        ).scalars().all():
            other.canonical_id = canonical_id
            mapping[other.alias_id] = canonical_id

    db.commit()
    invalidate(project_id)
    return created


def unlink(db: Session, project_id: Optional[uuid.UUID], alias_row_id: uuid.UUID) -> bool:
    """Remove one alias. The split it collapsed comes back, memories intact."""
    row = db.get(EntityAlias, alias_row_id)
    if row is None or (project_id is not None and row.project_id != project_id):
        return False
    db.delete(row)
    db.commit()
    invalidate(project_id)
    return True


def apply_to_write(
    db: Session,
    project_id: Optional[uuid.UUID],
    params: dict,
    metadata: dict,
) -> dict:
    """Redirect an incoming write to the canonical identifiers.

    Mutates neither argument's meaning silently: the identifier the caller sent
    is preserved under `metadata.source_entity_id`, so which channel a memory
    arrived from is still recorded even though it is filed under the person.
    """
    field_to_type = {"user_id": "user", "agent_id": "agent", "run_id": "run"}
    for field, entity_type in field_to_type.items():
        value = params.get(field)
        if not isinstance(value, str) or not value:
            continue
        canonical = resolve(db, project_id, entity_type, value)
        if canonical != value:
            params[field] = canonical
            sources = dict(metadata.get(SOURCE_KEY) or {})
            sources[field] = value
            metadata[SOURCE_KEY] = sources
    return metadata
