"""Dream: background curation that keeps memories current.

Three actions, none of them destructive:

- **Supersede** - a newer fact contradicts an older one. The older is marked
  superseded and linked to its replacement. Still returned by default, badged
  as history, because "what the system used to believe" is worth being able to
  read.
- **Merge** - two memories say the same thing. The thinner one is marked merged
  into the richer. Hidden by default, retained.
- **Synthesis** - many small memories imply something none of them states. A
  new pattern memory is written, linked back to the evidence that produced it.
  The sources are untouched.

The memory itself is never deleted or rewritten; only its lifecycle row changes.
Every decision writes an audit row carrying the model's own rationale, and every
action can be reverted. That is what makes this safe to leave switched on.

Nothing here runs on the request path. Supersede and merge are dispatched to the
same background executor the webhook and classification hooks already use, so an
add costs the caller nothing extra.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select

import lifecycle_services
import project_settings
from models import DreamAction, DreamRun, DreamState, PatternSource, Project

logger = logging.getLogger(__name__)

SUPERSEDE = "supersede"
MERGE = "merge"
SYNTHESIS = "synthesis"

DREAM_MODEL = os.environ.get("DREAM_MODEL", "gpt-4o-mini")

# Defaults. Overridable per project so a noisy corpus can be tuned without a
# deploy - see project_settings.DEFAULTS["dream"].
DEFAULTS = {
    "neighbour_k": 8,
    "similarity_floor": 0.72,
    # The duplicate bar sits higher than the contradiction bar on purpose: a
    # wrong merge hides information, a wrong supersede only re-orders it.
    "supersede_confidence": 0.70,
    "merge_confidence": 0.80,
    "synthesis_min_memories": 20,
    "synthesis_cadence_hours": 24,
    "synthesis_max_sources": 200,
    "synthesis_daily_run_cap": 20,
}


def config(settings_blob: Optional[dict]) -> dict[str, Any]:
    """Dream thresholds for a project, defaults filled in."""
    stored = project_settings.section(settings_blob, "dream")
    return {**DEFAULTS, **{k: v for k, v in stored.items() if v is not None}}


def enabled(settings_blob: Optional[dict], action: str) -> bool:
    """Whether an action may run for this project.

    Supersede and merge are always on: they are corrections, and a memory store
    that knowingly keeps contradictions is worse than one that reorders them.
    Synthesis writes *new* memories, so it is opt-in.
    """
    if action in (SUPERSEDE, MERGE):
        return True
    return bool(project_settings.section(settings_blob, "retention").get("dream_enabled"))


@dataclass
class Verdict:
    memory_id: str
    verdict: str  # contradicts | duplicates | unrelated
    confidence: float
    rationale: str


# --------------------------------------------------------------- runs


def start_run(db, project_id, kind: str, scope: Optional[dict] = None) -> DreamRun:
    run = DreamRun(
        project_id=project_id,
        kind=kind,
        status="running",
        scope=scope,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(db, run: DreamRun, status: str, *, error: Optional[str] = None) -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def record_action(
    db,
    run: DreamRun,
    kind: str,
    subject: str,
    obj: Optional[str],
    confidence: Optional[float],
    rationale: Optional[str],
) -> DreamAction:
    action = DreamAction(
        run_id=run.id,
        project_id=run.project_id,
        kind=kind,
        subject_memory_id=subject,
        object_memory_id=obj,
        confidence=confidence,
        rationale=(rationale or "")[:2000] or None,
    )
    db.add(action)
    run.acted = (run.acted or 0) + 1
    db.commit()
    return action


# --------------------------------------------------------------- adjudication


ADJUDICATE_PROMPT = """You are curating a memory store. A new memory has arrived. \
For each existing memory below, decide its relationship to the new one.

Return JSON: {"verdicts": [{"id": "<existing memory id>", "verdict": \
"contradicts|duplicates|unrelated", "confidence": 0.0-1.0, "rationale": "<one sentence>"}]}

Definitions, applied strictly:
- "contradicts": the new memory states something that cannot be true at the same \
time as the existing one. A change over time counts (moved city, changed job). \
Two facts that merely differ do not.
- "duplicates": both memories state the same fact. One may be more detailed; that \
is still a duplicate.
- "unrelated": anything else, including related-but-compatible facts.

Be conservative. When unsure, answer "unrelated" - a wrong merge hides \
information a person put there deliberately.

NEW MEMORY:
%%NEW_MEMORY%%

EXISTING MEMORIES:
%%EXISTING%%
"""


def _llm_client():
    from openai import OpenAI

    kwargs = {"api_key": os.environ.get("OPENAI_API_KEY")}
    if os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    return OpenAI(**kwargs)


def adjudicate(new_memory: dict, candidates: list[dict]) -> list[Verdict]:
    """One LLM call for all candidates, so an add costs one call not eight."""
    if not candidates:
        return []

    existing = "\n".join(
        f'- id={c.get("id")}: {c.get("memory")}' for c in candidates if c.get("memory")
    )
    # Explicit replacement, not str.format: the prompt contains a literal JSON
    # example, and format() reads those braces as placeholders and raises.
    prompt = ADJUDICATE_PROMPT.replace("%%NEW_MEMORY%%", str(new_memory.get("memory", ""))).replace(
        "%%EXISTING%%", existing
    )

    response = _llm_client().chat.completions.create(
        model=DREAM_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Dream adjudication returned invalid JSON: %s", raw[:400])
        return []

    known = {str(c.get("id")) for c in candidates}
    out: list[Verdict] = []
    for item in parsed.get("verdicts", []):
        memory_id = str(item.get("id") or "")
        # The model can hallucinate an id; anything not in the candidate set is
        # dropped rather than acted on.
        if memory_id not in known:
            continue
        verdict = str(item.get("verdict") or "unrelated").lower()
        if verdict not in ("contradicts", "duplicates", "unrelated"):
            continue
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append(
            Verdict(memory_id, verdict, max(0.0, min(1.0, confidence)), str(item.get("rationale") or ""))
        )
    return out


def _density(memory: dict) -> int:
    """A rough measure of how much a memory says.

    Used only to choose which of two duplicates survives. Length is a crude
    proxy, but the alternative - asking the model again - costs a second call
    to decide something the model already implied by calling them duplicates.
    """
    text = str(memory.get("memory") or "")
    return len(text)


# --------------------------------------------------------------- add path


def curate_new_memory(
    session_factory: Callable,
    memory: dict,
    project_id,
    scope_filters: dict,
    search_fn: Callable,
) -> None:
    """Supersede and merge around one newly-written memory.

    Runs on a worker thread after the response has gone out. Swallows
    everything: curation failing must never turn into a failed write.
    """
    memory_id = str(memory.get("id") or "")
    if not memory_id or not memory.get("memory"):
        return

    try:
        with session_factory() as db:
            project = db.get(Project, project_id) if project_id else None
            settings_blob = project.settings if project else None
            if not enabled(settings_blob, SUPERSEDE):
                return
            cfg = config(settings_blob)

            run = start_run(
                db,
                project_id,
                SUPERSEDE,
                scope={"trigger": "add", "memory_id": memory_id, "filters": scope_filters},
            )

            try:
                neighbours = search_fn(
                    query=str(memory["memory"]),
                    filters=scope_filters,
                    top_k=int(cfg["neighbour_k"]),
                )
                rows = neighbours.get("results", []) if isinstance(neighbours, dict) else (neighbours or [])
                candidates = [
                    r
                    for r in rows
                    if isinstance(r, dict)
                    and str(r.get("id")) != memory_id
                    and float(r.get("score") or 0) >= float(cfg["similarity_floor"])
                ]
                run.considered = len(candidates)
                db.commit()

                if not candidates:
                    finish_run(db, run, "skipped")
                    return

                for verdict in adjudicate(memory, candidates):
                    other = next((c for c in candidates if str(c.get("id")) == verdict.memory_id), None)
                    if other is None:
                        continue

                    if verdict.verdict == "contradicts" and verdict.confidence >= float(
                        cfg["supersede_confidence"]
                    ):
                        lifecycle_services.set_state(
                            db,
                            verdict.memory_id,
                            project_id,
                            lifecycle_services.SUPERSEDED,
                            reason=verdict.rationale,
                            actor="dream",
                            superseded_by=memory_id,
                        )
                        record_action(
                            db, run, SUPERSEDE, verdict.memory_id, memory_id, verdict.confidence, verdict.rationale
                        )

                    elif verdict.verdict == "duplicates" and verdict.confidence >= float(
                        cfg["merge_confidence"]
                    ):
                        # The richer one survives. Merging the detailed memory
                        # into the bare one would lose exactly the detail
                        # someone bothered to record.
                        if _density(memory) >= _density(other):
                            thinner, richer = verdict.memory_id, memory_id
                        else:
                            thinner, richer = memory_id, verdict.memory_id
                        lifecycle_services.set_state(
                            db,
                            thinner,
                            project_id,
                            lifecycle_services.MERGED,
                            reason=verdict.rationale,
                            actor="dream",
                            merged_into=richer,
                        )
                        record_action(
                            db, run, MERGE, thinner, richer, verdict.confidence, verdict.rationale
                        )

                finish_run(db, run, "succeeded")
            except Exception as exc:
                finish_run(db, run, "failed", error=str(exc)[:1000])
                raise
    except Exception:
        logger.warning("Dream curation failed for memory %s", memory_id, exc_info=True)


# --------------------------------------------------------------- synthesis


SYNTHESIS_PROMPT = """You are looking for patterns across one person's memories.

Read the memories below and identify at most 3 patterns: things that are true \
about this person which no single memory states, but which several together \
imply. A pattern must be supported by at least 3 of the memories.

Return JSON: {"patterns": [{"statement": "<the pattern, one sentence, written \
as a memory about the person>", "source_ids": ["<id>", ...], "confidence": 0.0-1.0}]}

Do not restate a single memory. Do not speculate beyond what the memories \
support. If nothing rises to the level of a pattern, return an empty list - \
that is a correct answer and a common one.

MEMORIES:
%%MEMORIES%%
"""


def _pattern_hash(source_ids: list[str]) -> str:
    """Identity of a pattern, by the evidence set that produced it.

    Sorted before hashing so the same sources in a different order are the same
    pattern; this is what makes re-running produce nothing new.
    """
    return hashlib.sha256("|".join(sorted(source_ids)).encode()).hexdigest()[:32]


def synthesize_for_entity(
    db,
    project_id,
    entity_type: str,
    entity_id: str,
    memories: list[dict],
    add_fn: Callable,
    settings_blob: Optional[dict] = None,
) -> DreamRun:
    """Distil patterns from one person's memories into new pattern memories."""
    cfg = config(settings_blob)
    run = start_run(
        db, project_id, SYNTHESIS, scope={"entity_type": entity_type, "entity_id": entity_id}
    )

    try:
        eligible = memories[: int(cfg["synthesis_max_sources"])]
        run.considered = len(eligible)
        db.commit()

        if len(eligible) < int(cfg["synthesis_min_memories"]):
            finish_run(db, run, "skipped")
            return run

        listing = "\n".join(
            f'- id={m.get("id")}: {m.get("memory")}' for m in eligible if m.get("memory")
        )
        response = _llm_client().chat.completions.create(
            model=DREAM_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "user", "content": SYNTHESIS_PROMPT.replace("%%MEMORIES%%", listing)}
            ],
        )
        usage = getattr(response, "usage", None)
        run.tokens_used = int(getattr(usage, "total_tokens", 0) or 0)

        parsed = json.loads(response.choices[0].message.content or "{}")
        state = _state_for(db, project_id, entity_type, entity_id)
        seen_hashes = set(state.pattern_hashes or [])
        known_ids = {str(m.get("id")) for m in eligible}

        for item in parsed.get("patterns", []):
            statement = str(item.get("statement") or "").strip()
            source_ids = [str(s) for s in (item.get("source_ids") or []) if str(s) in known_ids]
            if not statement or len(source_ids) < 3:
                continue

            digest = _pattern_hash(source_ids)
            if digest in seen_hashes:
                continue  # Already synthesised from exactly this evidence.

            created = add_fn(statement, entity_type, entity_id, source_ids)
            if not created:
                continue

            lifecycle_services.set_state(
                db,
                created,
                project_id,
                lifecycle_services.PATTERN,
                reason=f"Synthesised from {len(source_ids)} memories.",
                actor="dream",
                commit=False,
            )
            for source_id in source_ids:
                db.add(
                    PatternSource(
                        pattern_memory_id=created,
                        source_memory_id=source_id,
                        project_id=project_id,
                    )
                )
            record_action(
                db, run, SYNTHESIS, created, None, float(item.get("confidence") or 0), statement
            )
            seen_hashes.add(digest)

        state.pattern_hashes = sorted(seen_hashes)
        state.last_synthesis_at = datetime.now(timezone.utc)
        state.memory_count_at_last_run = len(memories)
        db.commit()

        finish_run(db, run, "succeeded")
    except Exception as exc:
        finish_run(db, run, "failed", error=str(exc)[:1000])
        logger.warning("Dream synthesis failed for %s %s", entity_type, entity_id, exc_info=True)
    return run


def _state_for(db, project_id, entity_type: str, entity_id: str) -> DreamState:
    row = db.scalar(
        select(DreamState).where(
            DreamState.project_id == project_id,
            DreamState.entity_type == entity_type,
            DreamState.entity_id == entity_id,
        )
    )
    if row is None:
        row = DreamState(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            enabled_from=datetime.now(timezone.utc),
            pattern_hashes=[],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def is_due(db, project_id, entity_type: str, entity_id: str, settings_blob: Optional[dict]) -> bool:
    """Whether this entity's cadence window has elapsed."""
    cfg = config(settings_blob)
    state = _state_for(db, project_id, entity_type, entity_id)
    if state.last_synthesis_at is None:
        return True
    last = state.last_synthesis_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(hours=float(cfg["synthesis_cadence_hours"]))


def runs_today(db, project_id) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    return (
        db.query(DreamRun)
        .filter(
            DreamRun.project_id == project_id,
            DreamRun.kind == SYNTHESIS,
            DreamRun.started_at >= since,
        )
        .count()
    )


# --------------------------------------------------------------- revert


def revert(db, action_id: uuid.UUID, project_id) -> tuple[bool, str]:
    """Undo one Dream action. Returns (ok, message).

    Reverting a supersede or merge restores the memory to active. Reverting a
    synthesis marks the pattern superseded rather than deleting it - the
    pattern was a real memory, and its provenance rows are worth keeping.
    """
    action = db.get(DreamAction, action_id)
    if action is None or (project_id is not None and action.project_id != project_id):
        return False, "Action not found."
    if action.reverted_at is not None:
        return False, "That action has already been reverted."

    if action.kind in (SUPERSEDE, MERGE):
        lifecycle_services.set_state(
            db,
            action.subject_memory_id,
            action.project_id,
            lifecycle_services.ACTIVE,
            reason=f"Dream's {action.kind} was reverted.",
            actor="user",
        )
        message = "Memory restored to active."
    else:
        lifecycle_services.set_state(
            db,
            action.subject_memory_id,
            action.project_id,
            lifecycle_services.EXPIRED,
            reason="The synthesised pattern was rejected.",
            actor="user",
        )
        message = "Pattern retired."

    action.reverted_at = datetime.now(timezone.utc)
    db.commit()
    return True, message
