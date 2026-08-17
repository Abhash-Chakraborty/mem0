"""Decay: recently-used memories surface higher. Expiry: old ones step aside.

Decay is a ranking bias, never a filter. The floor is 0.3x, so anything that
would have surfaced without decay can still surface with it - only the order
changes. That distinction is what makes the feature safe: a bias that could
remove a result is a filter wearing a disguise, and a search that silently
dropped the answer would be worse than one that ranked it third.

The OSS core rejects `decay=True` outright, so this runs as a re-ranking stage
over the core's results rather than as a parameter to it.

One consequence is worth stating plainly rather than discovering: because the
core applies `threshold` before this stage, a decayed result can come back
scoring just under the requested threshold. The alternative - re-filtering after
the bias - would let decay remove candidates, which is the thing it must not do.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

import lifecycle_services
import project_settings
from models import MemoryAccess, MemoryLifecycle

logger = logging.getLogger(__name__)

# A memory can be boosted to 1.5x or damped to 0.3x, never beyond. The floor is
# the important end: it is what keeps decay a bias rather than a filter.
FLOOR = 0.3
CEIL = 1.5

# Half-life of the recency term, in days. Chosen so the curve lands on the
# bands the design calls for:
#   just accessed  1.4x   |  idle 5 days   ~0.97x
#   idle 1 day     1.30x  |  idle 2 weeks  ~0.58x
#   idle 1 month   ~0.36x |  idle 3 months ~0.30x (the floor)
RECENCY_HALFLIFE_DAYS = 7.0
# The recency term alone spans [FLOOR, RECENCY_CEIL]. It stops below CEIL so
# frequency has somewhere to lift a well-used memory without every fresh one
# pinning to the ceiling.
RECENCY_CEIL = 1.4
# How much repeated use can lift a memory. Logarithmic, so each additional
# recall matters less than the one before - otherwise one hot memory would
# dominate every search forever.
FREQUENCY_WEIGHT = 0.08


def enabled(settings_blob: Optional[dict]) -> bool:
    return bool(project_settings.section(settings_blob, "retention").get("decay_enabled"))


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def factor(
    access: Optional[MemoryAccess],
    memory: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> float:
    """The multiplier for one memory, in [FLOOR, CEIL].

    A memory that has never been read is not punished for it - that would bias
    against everything written recently, which is exactly the material most
    likely to matter. Its own timestamps stand in for an access it has not had
    yet, so a new memory sits neutral rather than damped.
    """
    now = now or datetime.now(timezone.utc)

    last_touch = _as_utc(getattr(access, "last_access_at", None))
    count = int(getattr(access, "access_count", 0) or 0)

    if last_touch is None:
        # Never read. Anchor on the memory's own dates so age still counts, but
        # from a neutral starting point rather than a penalised one.
        memory = memory or {}
        last_touch = _as_utc(memory.get("updated_at")) or _as_utc(memory.get("created_at"))
        if last_touch is None:
            return 1.0

    idle_days = max(0.0, (now - last_touch).total_seconds() / 86400.0)

    # Exponential decay on recency, landing at RECENCY_CEIL when just accessed
    # and approaching FLOOR asymptotically. Exponential rather than linear so
    # "yesterday" and "last week" differ meaningfully while "six months" and
    # "a year" do not - past a point, staleness stops being informative.
    recency = FLOOR + (RECENCY_CEIL - FLOOR) * math.pow(0.5, idle_days / RECENCY_HALFLIFE_DAYS)

    # Logarithmic frequency: each additional recall lifts less than the last.
    frequency = 1.0 + FREQUENCY_WEIGHT * math.log1p(count)

    return max(FLOOR, min(CEIL, recency * frequency))


def access_map(db: Session, memory_ids: Iterable[str]) -> dict[str, MemoryAccess]:
    return lifecycle_services.access_for(db, memory_ids)


def rerank(
    db: Session,
    response: Any,
    top_k: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Any:
    """Apply the decay bias to a search response.

    The public `score` is clamped back into [0,1] afterwards, so the API
    contract is unchanged - a client that has never heard of decay still sees
    scores it can compare. The unclamped product is what the sort uses, because
    clamping first would flatten the top of the range into ties.
    """
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        return response

    results = [r for r in response["results"] if isinstance(r, dict)]
    if not results:
        return response

    accesses = access_map(db, [str(r.get("id") or "") for r in results])
    now = now or datetime.now(timezone.utc)

    ranked = []
    for row in results:
        memory_id = str(row.get("id") or "")
        multiplier = factor(accesses.get(memory_id), row, now)
        base = row.get("score")
        base_value = float(base) if isinstance(base, (int, float)) else 0.0
        biased = base_value * multiplier
        ranked.append(
            (
                biased,
                {
                    **row,
                    "score": max(0.0, min(1.0, biased)),
                    # Both kept so the Recall playground can show its work, and
                    # so "why did this rank here" is answerable.
                    "base_score": base_value,
                    "decay_factor": round(multiplier, 4),
                },
            )
        )

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    ordered = [row for _, row in ranked]
    if top_k is not None:
        ordered = ordered[:top_k]
    return {**response, "results": ordered}


# --------------------------------------------------------------- expiry


def expiry_of(memory: dict) -> Optional[datetime]:
    """A memory's expiration, whichever shape it arrives in."""
    value = memory.get("expiration_date")
    if value is None:
        metadata = memory.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("expiration_date")
    if value is None:
        return None
    parsed = _as_utc(value)
    if parsed is None:
        # A bare YYYY-MM-DD, which is what the SDK stores.
        try:
            parsed = datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
    return parsed


def is_expired(memory: dict, now: Optional[datetime] = None) -> bool:
    expires = expiry_of(memory)
    if expires is None:
        return False
    return expires <= (now or datetime.now(timezone.utc))


def sweep_expired(
    db: Session,
    memories: list[dict],
    project_id,
    now: Optional[datetime] = None,
) -> int:
    """Mark passed expiration dates as expired in the lifecycle table.

    Recorded rather than recomputed per row so the Memories page can show the
    state without re-parsing every payload, and so the transition has a
    timestamp like every other one.

    Expired memories are hidden, never deleted - consistent with everything
    else here. A date passing is a statement about relevance, not a request to
    destroy something.
    """
    now = now or datetime.now(timezone.utc)
    marked = 0

    existing = lifecycle_services.states_for(db, [str(m.get("id") or "") for m in memories])
    for memory in memories:
        memory_id = str(memory.get("id") or "")
        if not memory_id or not is_expired(memory, now):
            continue
        current = existing.get(memory_id)
        # Only active memories are swept: something already superseded or
        # merged has a more specific state, and overwriting it would lose why.
        if current is not None and current.state != lifecycle_services.ACTIVE:
            continue
        lifecycle_services.set_state(
            db,
            memory_id,
            project_id,
            lifecycle_services.EXPIRED,
            reason=f"Expiration date passed ({expiry_of(memory).date().isoformat()}).",
            actor="system",
            commit=False,
        )
        marked += 1

    if marked:
        db.commit()
    return marked


def unexpire(db: Session, memory_id: str, project_id) -> None:
    """Return an expired memory to active, e.g. after its date is extended."""
    lifecycle_services.set_state(
        db,
        memory_id,
        project_id,
        lifecycle_services.ACTIVE,
        reason="Expiration date extended.",
        actor="user",
    )


def expiring_soon(db: Session, project_id, within_days: int = 7) -> list[str]:
    """Memory ids already marked expired, for the retention page's counts."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    rows = (
        db.execute(
            select(MemoryLifecycle.memory_id).where(
                MemoryLifecycle.project_id == project_id,
                MemoryLifecycle.state == lifecycle_services.EXPIRED,
                MemoryLifecycle.changed_at >= cutoff,
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --------------------------------------------------------------- sweeper

SCAN_LIMIT = 10_000


def run_expiry_sweep(session_factory, memory_instance_fn) -> int:
    """Mark every memory whose expiration date has passed.

    Runs on the scheduler alongside the backup check and trace sweep. Never
    raises: a failure for one project must not stop the others.
    """
    from models import Project
    from tenancy import PROJECT_KEY

    total = 0
    try:
        with session_factory() as db:
            projects = db.execute(select(Project)).scalars().all()
            instance = memory_instance_fn()
            results = instance.vector_store.list(top_k=SCAN_LIMIT)
            rows = (
                results[0]
                if results and isinstance(results, list) and isinstance(results[0], list)
                else results or []
            )

            by_project: dict[str, list[dict]] = {}
            for row in rows:
                payload = getattr(row, "payload", None) or {}
                project_key = str(payload.get(PROJECT_KEY) or "")
                by_project.setdefault(project_key, []).append(
                    {"id": str(getattr(row, "id", "")), "expiration_date": payload.get("expiration_date")}
                )

            for project in projects:
                candidates = by_project.get(str(project.id), [])
                if not candidates:
                    continue
                try:
                    total += sweep_expired(db, candidates, project.id)
                except Exception:
                    db.rollback()
                    logger.exception("Expiry sweep failed for project %s", project.id)
    except Exception:
        logger.exception("Expiry sweep failed")

    if total:
        logger.info("Expiry sweep marked %d memories expired", total)
    return total
