"""The typed search syntax: `user:alice type:add status:failed some free text`.

One search box, two jobs: structured filters for what you know, and free text
for what you half-remember. Splitting them into separate inputs would be more
honest to the implementation and worse to use, so they share a box and are
separated here.

Unknown prefixes are deliberately *not* treated as filters. `http://example.com`
would otherwise parse as `http:` with a value, and a typo like `usr:alice` would
silently filter on nothing and return everything. Both fall through to free text,
where they at least behave like a search.

Mirrored in dashboard/src/lib/query-syntax.ts, which parses the same grammar to
render filter chips before the request is sent.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Optional

# The entity prefixes, mapped to the entity type they filter on. `session` is
# the UI's word for what the API calls a run; both are accepted.
ENTITY_PREFIXES: dict[str, str] = {
    "user": "user",
    "agent": "agent",
    "run": "run",
    "session": "run",
    "app": "agent",
}

TYPE_VALUES = {"add", "search", "get_all", "get", "update", "delete", "delete_all", "other"}
STATUS_VALUES = {"succeeded", "failed"}
METHOD_VALUES = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Aliases people actually type for request types.
TYPE_ALIASES = {
    "getall": "get_all",
    "get-all": "get_all",
    "list": "get_all",
    "deleteall": "delete_all",
    "delete-all": "delete_all",
    "create": "add",
    "write": "add",
    "query": "search",
}

_TOKEN = re.compile(r"^(?P<key>[a-zA-Z_-]+):(?P<value>.*)$")


@dataclass(frozen=True)
class ParsedQuery:
    types: list[str] = field(default_factory=list)
    status: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    method: Optional[str] = None
    text: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not any((self.types, self.status, self.entity_type, self.entity_id, self.method, self.text))


EMPTY = ParsedQuery()


def _tokenize(raw: str) -> list[str]:
    """Split on whitespace, honouring quotes so `user:"ada lovelace"` survives."""
    try:
        return shlex.split(raw)
    except ValueError:
        # Unbalanced quote - someone is mid-typing. Fall back to a plain split
        # rather than refusing to search.
        return raw.split()


def parse(raw: Optional[str]) -> ParsedQuery:
    if not raw or not raw.strip():
        return EMPTY

    types: list[str] = []
    status: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    method: Optional[str] = None
    free: list[str] = []

    for token in _tokenize(raw):
        match = _TOKEN.match(token)
        if not match:
            free.append(token)
            continue

        key = match.group("key").lower()
        value = match.group("value").strip()
        if not value:
            free.append(token)
            continue

        if key in ENTITY_PREFIXES:
            entity_type = ENTITY_PREFIXES[key]
            entity_id = value
        elif key == "type":
            normalized = TYPE_ALIASES.get(value.lower(), value.lower())
            if normalized in TYPE_VALUES:
                types.append(normalized)
            else:
                free.append(token)
        elif key == "status":
            lowered = value.lower()
            if lowered in STATUS_VALUES:
                status = lowered
            elif lowered in ("ok", "success", "2xx"):
                status = "succeeded"
            elif lowered in ("error", "fail", "4xx", "5xx"):
                status = "failed"
            else:
                free.append(token)
        elif key == "method":
            upper = value.upper()
            if upper in METHOD_VALUES:
                method = upper
            else:
                free.append(token)
        else:
            # Unknown prefix. Not a filter - see the module docstring.
            free.append(token)

    return ParsedQuery(
        types=types,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        method=method,
        text=" ".join(free) or None,
    )
