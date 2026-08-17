"""The shape of `projects.settings`, in one place.

The column is JSONB so that tuning extraction, categories or retention is a
write rather than a migration. The cost of that freedom is that nothing stops a
typo from becoming a silently-ignored key, so the shape is declared here, every
read goes through `resolve`, and every write goes through `merge`. Routes never
reach into the raw dict.

Defaults are returned for absent keys rather than written on project creation.
A project row created before a setting existed then behaves identically to one
created after, and adding a setting never needs a backfill.
"""

from __future__ import annotations

from typing import Any, Optional

# Anything outside this set is dropped on write. A rejected key is better than
# one that persists and does nothing, which is indistinguishable from a bug.
EXTRACTION_KEYS = {"user_instructions", "agent_instructions", "multilingual", "infer"}
RETENTION_KEYS = {"default_expiration_days", "decay_enabled", "dream_enabled", "trace_retention_days"}
CATEGORY_KEYS = {"auto_classify", "disabled_defaults"}
# Dream thresholds, tunable per project so a noisy corpus can be adjusted
# without a deploy. Defaults live in dream_services.DEFAULTS; absent keys here
# mean "use those".
DREAM_KEYS = {
    "neighbour_k",
    "similarity_floor",
    "supersede_confidence",
    "merge_confidence",
    "synthesis_min_memories",
    "synthesis_cadence_hours",
    "synthesis_max_sources",
    "synthesis_daily_run_cap",
}

DEFAULTS: dict[str, dict[str, Any]] = {
    "extraction": {
        # Empty means "use the instance-level custom_instructions, if any".
        "user_instructions": "",
        "agent_instructions": "",
        "multilingual": False,
        # False here would store raw messages verbatim instead of extracting
        # facts. Defaulted on because that is what the SDK does.
        "infer": True,
    },
    "retention": {
        # None means memories never expire, which is the SDK's behaviour.
        "default_expiration_days": None,
        "decay_enabled": False,
        "dream_enabled": False,
        # How long request traces are kept. 0 keeps them forever, which is a
        # real choice on a quiet instance but a bad default on a busy one.
        "trace_retention_days": 30,
    },
    "categories": {
        "auto_classify": True,
        # Names of built-in categories this project does not want applied.
        "disabled_defaults": [],
    },
    # Empty by default: dream_services fills in its own defaults, so an absent
    # key means "whatever the code says" rather than a value frozen here.
    "dream": {},
}

SECTION_KEYS: dict[str, set[str]] = {
    "extraction": EXTRACTION_KEYS,
    "retention": RETENTION_KEYS,
    "categories": CATEGORY_KEYS,
    "dream": DREAM_KEYS,
}


def resolve(raw: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Full settings for a project: stored values over defaults, section by section."""
    stored = raw or {}
    out: dict[str, dict[str, Any]] = {}
    for section, defaults in DEFAULTS.items():
        section_value = stored.get(section)
        merged = dict(defaults)
        if isinstance(section_value, dict):
            merged.update({k: v for k, v in section_value.items() if k in SECTION_KEYS[section]})
        out[section] = merged
    return out


def section(raw: Optional[dict[str, Any]], name: str) -> dict[str, Any]:
    return resolve(raw).get(name, {})


def merge(existing: Optional[dict[str, Any]], incoming: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Apply a partial update, one section at a time.

    Sections merge rather than replace so a client that knows about extraction
    cannot wipe retention by omitting it, and unknown keys are dropped so a
    typo fails loudly at the next read instead of persisting forever.
    """
    result = {k: dict(v) for k, v in (existing or {}).items() if isinstance(v, dict)}
    for name, value in (incoming or {}).items():
        if name not in SECTION_KEYS or not isinstance(value, dict):
            continue
        current = result.get(name, {})
        current.update({k: v for k, v in value.items() if k in SECTION_KEYS[name]})
        result[name] = current
    return result


def extraction_prompt(raw: Optional[dict[str, Any]], *, has_user: bool, has_agent: bool) -> Optional[str]:
    """The fact-extraction instructions for one add, or None to use the default.

    The SDK resolves `prompt or self.custom_instructions`, so returning None
    leaves the instance-level instructions in force rather than blanking them.

    An add carrying only an agent id uses the agent instructions; anything else
    uses the user set. When both ids are present the two are concatenated, since
    the call is about a user *and* an agent and dropping either half would
    silently ignore configuration the operator wrote.
    """
    config = section(raw, "extraction")
    user_text = (config.get("user_instructions") or "").strip()
    agent_text = (config.get("agent_instructions") or "").strip()

    if has_agent and not has_user:
        parts = [agent_text]
    elif has_agent and has_user:
        parts = [p for p in (user_text, agent_text) if p]
    else:
        parts = [user_text]

    parts = [p for p in parts if p]
    if config.get("multilingual"):
        parts.append(
            "Record each memory in the same language the user wrote it in. "
            "Do not translate to English."
        )

    return "\n\n".join(parts) if parts else None
