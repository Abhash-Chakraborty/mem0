"""What may be written to the request-trace tables, and what may not.

Applied at write time, never at read time. A secret that reaches the database
has already leaked - into backups, into replicas, into whatever query someone
runs later - and redacting on the way out would only hide it from the dashboard.
So the database never holds it in the first place.

Matching is by key substring rather than exact name because the keys that carry
secrets are not a closed set: `openai_api_key`, `x-api-key`, `refreshToken` and
`client_secret` all have to be caught without enumerating every framework's
naming convention. The cost is over-redaction on an innocent key containing
"token", which is the right direction to err.

Separators are stripped before matching, so one entry covers every spelling a
key might arrive in - `api_key`, `x-api-key`, `apiKey`, `API KEY`. Listing the
variants instead is how `x-api-key`, the form this API's own header uses, gets
missed.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[redacted]"

# Substrings, matched against the key with separators stripped and lowercased -
# so each entry is written in its bare form and covers every spelling.
REDACT_KEY_PARTS: frozenset[str] = frozenset(
    {
        "apikey",
        "authorization",
        "authtoken",
        "accesstoken",
        "clientsecret",
        "cookie",
        "credential",
        "jwt",
        "passwd",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "sessionid",
        "token",
    }
)

_SEPARATORS = re.compile(r"[^a-z0-9]+")

# Total serialized size of a captured body. Beyond this the payload is replaced
# by a marker: a log table that grows faster than the data it describes is a
# worse outage than a missing payload.
MAX_CAPTURED_BYTES = 32 * 1024
# Per-string cap, applied before the total. One enormous message must not use
# the whole budget and push every other field out of the capture.
MAX_STRING_LEN = 4 * 1024
# Depth and breadth caps, so a pathological body cannot cost unbounded CPU.
MAX_DEPTH = 8
MAX_ITEMS = 200


def is_sensitive(key: str) -> bool:
    normalized = _SEPARATORS.sub("", key.lower())
    return any(part in normalized for part in REDACT_KEY_PARTS)


def redact(value: Any, _depth: int = 0) -> Any:
    """Return a copy with sensitive values replaced and oversized ones truncated.

    Never mutates the input: this runs on request bodies that handlers are
    still using.
    """
    if _depth >= MAX_DEPTH:
        return "[truncated: too deep]"

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                out["[truncated]"] = f"{len(value) - MAX_ITEMS} more keys"
                break
            out[str(key)] = REDACTED if is_sensitive(str(key)) else redact(item, _depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        items = [redact(item, _depth + 1) for item in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"[truncated: {len(value) - MAX_ITEMS} more items]")
        return items

    if isinstance(value, str) and len(value) > MAX_STRING_LEN:
        return value[:MAX_STRING_LEN] + f"… [truncated: {len(value) - MAX_STRING_LEN} more chars]"

    return value


def redact_headers(headers: Any) -> dict[str, str]:
    """Headers with credentials removed. Accepts anything dict-like."""
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(k): (REDACTED if is_sensitive(str(k)) else str(v)) for k, v in items}


def fits(value: Any) -> bool:
    """Whether a redacted value is small enough to store."""
    import json

    try:
        return len(json.dumps(value, default=str).encode("utf-8")) <= MAX_CAPTURED_BYTES
    except (TypeError, ValueError):
        return False


def capture(value: Any) -> Any:
    """Redact, then drop the payload entirely if it is still too large.

    Returning a marker rather than a partial body is deliberate: a body cut off
    mid-structure reads as data when it is really an artefact of the cap.
    """
    if value is None:
        return None
    redacted = redact(value)
    if fits(redacted):
        return redacted
    return {"_truncated": True, "_reason": f"body exceeded {MAX_CAPTURED_BYTES} bytes after redaction"}
