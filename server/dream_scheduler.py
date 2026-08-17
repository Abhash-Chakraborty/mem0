"""The scheduled half of Dream: finding who is due for synthesis, and running it.

Kept out of dream_services so that module stays about *deciding* things, and out
of main.py so the route file stays about routes. This is the part that knows how
to walk the vector store, which is the part most likely to change.

Eligibility is deliberately narrow. Only memories scoped to a `user_id` alone
are considered: anything also carrying an agent, run, or app id belongs to a
narrower context, and rolling those into a pattern about the person would draw
conclusions from evidence that was never about them in general.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select

import dream_services
import identity
from models import Project

logger = logging.getLogger(__name__)

SCAN_LIMIT = 10_000


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def eligible_memories_by_user(
    memory_instance: Any,
    project_id,
    db,
    enabled_from: Optional[datetime] = None,
) -> dict[str, list[dict[str, Any]]]:
    """User-scoped memories in this project, grouped by canonical user id.

    A memory carrying an agent, run or app id is skipped: it belongs to a
    narrower context than "things true about this person".
    """
    from tenancy import PROJECT_KEY

    results = memory_instance.vector_store.list(top_k=SCAN_LIMIT)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        payload = getattr(row, "payload", None) or {}
        if str(payload.get(PROJECT_KEY) or "") != str(project_id):
            continue
        user_id = payload.get("user_id")
        if not user_id:
            continue
        if payload.get("agent_id") or payload.get("run_id") or payload.get("app_id"):
            continue

        created = _parse(payload.get("created_at"))
        if enabled_from and created and created < enabled_from:
            # Switching synthesis on must not reprocess all history.
            continue

        canonical = identity.resolve(db, project_id, "user", str(user_id))
        grouped.setdefault(canonical, []).append(
            {
                "id": str(getattr(row, "id", "")),
                "memory": payload.get("data"),
                "created_at": payload.get("created_at"),
            }
        )
    return grouped


def _writer(memory_instance, session_factory, project_id):
    """Build the callback synthesis uses to write a pattern memory.

    `infer=False`: the statement is already the memory. Sending it back through
    fact extraction would let the model rewrite a conclusion it just drew.
    """

    def add_pattern(statement: str, entity_type: str, entity_id: str, source_ids: list[str]) -> Optional[str]:
        try:
            response = memory_instance.add(
                messages=[{"role": "user", "content": statement}],
                user_id=entity_id,
                infer=False,
                metadata={
                    "project_id": str(project_id),
                    "dream_pattern": True,
                    "pattern_source_count": len(source_ids),
                },
            )
            results = response.get("results", []) if isinstance(response, dict) else []
            for item in results:
                if isinstance(item, dict) and item.get("id"):
                    return str(item["id"])
        except Exception:
            logger.warning("Failed to write pattern memory", exc_info=True)
        return None

    return add_pattern


def run_due_synthesis(session_factory: Callable, memory_instance_fn: Callable) -> int:
    """Synthesise for every entity whose cadence window has elapsed.

    Never raises: this runs on a scheduler, and a failure for one project must
    not stop the others.
    """
    total_runs = 0
    try:
        with session_factory() as db:
            projects = db.execute(select(Project)).scalars().all()
    except Exception:
        logger.exception("Dream sweep could not list projects")
        return 0

    for project in projects:
        try:
            if not dream_services.enabled(project.settings, dream_services.SYNTHESIS):
                continue

            cfg = dream_services.config(project.settings)
            with session_factory() as db:
                if dream_services.runs_today(db, project.id) >= int(cfg["synthesis_daily_run_cap"]):
                    logger.info("Dream daily run cap reached for project %s", project.id)
                    continue

                memory_instance = memory_instance_fn()
                grouped = eligible_memories_by_user(memory_instance, project.id, db)
                writer = _writer(memory_instance, session_factory, project.id)

                for entity_id, memories in grouped.items():
                    if len(memories) < int(cfg["synthesis_min_memories"]):
                        continue
                    if not dream_services.is_due(db, project.id, "user", entity_id, project.settings):
                        continue
                    if dream_services.runs_today(db, project.id) >= int(cfg["synthesis_daily_run_cap"]):
                        break

                    # Newest first: a pattern should be drawn from what is
                    # current, and the source cap cuts the tail.
                    memories.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
                    dream_services.synthesize_for_entity(
                        db,
                        project.id,
                        "user",
                        entity_id,
                        memories,
                        writer,
                        settings_blob=project.settings,
                    )
                    total_runs += 1
        except Exception:
            logger.exception("Dream sweep failed for project %s", getattr(project, "id", "?"))

    if total_runs:
        logger.info("Dream synthesis sweep completed %d run(s)", total_runs)
    return total_runs


def synthesize_now(session_factory: Callable, memory_instance_fn: Callable, project_id, entity_id: str):
    """Run synthesis for one entity immediately, ignoring the cadence window.

    Backs the Dream page's "Run now". The minimum-memories gate still applies -
    that one is about whether there is anything to find, not about timing.
    """
    with session_factory() as db:
        project = db.get(Project, project_id)
        settings_blob = project.settings if project else None
        memory_instance = memory_instance_fn()
        grouped = eligible_memories_by_user(memory_instance, project_id, db)
        memories = grouped.get(entity_id, [])
        memories.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
        return dream_services.synthesize_for_entity(
            db,
            project_id,
            "user",
            entity_id,
            memories,
            _writer(memory_instance, session_factory, project_id),
            settings_blob=settings_blob,
        )


def candidate_entities(session_factory: Callable, memory_instance_fn: Callable, project_id) -> list[dict]:
    """Entities with enough memories for synthesis, and whether they are due."""
    with session_factory() as db:
        project = db.get(Project, project_id)
        settings_blob = project.settings if project else None
        cfg = dream_services.config(settings_blob)
        grouped = eligible_memories_by_user(memory_instance_fn(), project_id, db)

        out = []
        for entity_id, memories in sorted(grouped.items()):
            out.append(
                {
                    "entity_type": "user",
                    "entity_id": entity_id,
                    "memory_count": len(memories),
                    "eligible": len(memories) >= int(cfg["synthesis_min_memories"]),
                    "due": dream_services.is_due(db, project_id, "user", entity_id, settings_blob),
                }
            )
        return out
