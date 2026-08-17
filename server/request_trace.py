"""Turn one HTTP exchange into a row the Requests page can render.

The dashboard wants to answer, per request: what kind of call was this, who was
it about, how many memories did it touch, what went in, and what came out.
Almost none of that is derivable from method and path alone, so it is derived
here, once, from the request body and the response body together.

Everything in this module runs *after* the response has been handed to the
client, on a worker thread. Nothing here is allowed to be on the request path,
and nothing here may raise into it - a malformed body must cost a degraded log
row, never a failed request.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import redaction

logger = logging.getLogger(__name__)

# The request types the UI groups by. "other" is a real bucket, not a failure:
# plenty of traffic is neither a memory operation nor worth its own badge.
REQUEST_TYPES = (
    "add",
    "search",
    "get_all",
    "get",
    "update",
    "delete",
    "delete_all",
    "other",
)

_MEMORY_ID_PATH = re.compile(r"^/memories/(?P<id>[^/]+)")

# Paths whose bodies must never be buffered: a stream held in memory to be
# logged is a stream that no longer streams.
STREAMING_PREFIXES = (
    "/system/logs/stream",
    "/backups/",
    "/export",
)


def classify(method: str, path: str) -> str:
    """Map an HTTP call onto a request type.

    Ordered most specific first, because `/memories/{id}` and `/memories` differ
    only by a path segment and the wrong order silently labels every single-get
    as a list.
    """
    method = method.upper()

    if path == "/search":
        return "search"

    memory_match = _MEMORY_ID_PATH.match(path)
    has_id = bool(memory_match) and memory_match.group("id") not in ("", "search")

    if path == "/memories":
        if method == "POST":
            return "add"
        if method == "GET":
            return "get_all"
        if method == "DELETE":
            return "delete_all"
    elif has_id:
        if path.endswith("/history"):
            return "get"
        if method == "GET":
            return "get"
        if method in ("PUT", "PATCH"):
            return "update"
        if method == "DELETE":
            return "delete"

    return "other"


def is_streaming(path: str) -> bool:
    return path.startswith(STREAMING_PREFIXES)


def parse_body(raw: Optional[bytes]) -> Any:
    """Best-effort JSON decode. Non-JSON bodies are described, not stored."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"_unparsed": True, "_bytes": len(raw)}


def extract_entities(body: Any, query: Any) -> list[dict[str, str]]:
    """Which user / agent / session this request was about.

    Read from the body first and the query string second, because a POST names
    its entity in the body while a GET names it in the query, and a request that
    somehow has both is describing the same thing twice.

    Returned as a list of typed pairs rather than three nullable columns so the
    Entities column renders uniformly and a GIN index can serve "everything
    about alice" without three OR'd predicates.
    """
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def take(source: Any) -> None:
        if not isinstance(source, dict):
            return
        for key, entity_type in (("user_id", "user"), ("agent_id", "agent"), ("run_id", "run")):
            value = source.get(key)
            if isinstance(value, str) and value:
                pair = (entity_type, value)
                if pair not in seen:
                    seen.add(pair)
                    found.append({"type": entity_type, "id": value})

    take(body)
    # /search nests its entity ids one level down.
    if isinstance(body, dict):
        take(body.get("filters"))
    take(query)
    return found


def _result_list(response_body: Any) -> list[Any]:
    if isinstance(response_body, dict):
        results = response_body.get("results")
        if isinstance(results, list):
            return results
    if isinstance(response_body, list):
        return response_body
    return []


def extract_memory_ids(response_body: Any, path: str) -> list[str]:
    """Ids of memories this request touched.

    Covers the two shapes the API returns: a results envelope, and a single
    memory object from a by-id route. A delete returns neither, so the id is
    recovered from the path - otherwise the one operation people most want to
    trace back is the one with nothing to trace.
    """
    ids: list[str] = []
    for item in _result_list(response_body):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])

    if not ids and isinstance(response_body, dict) and isinstance(response_body.get("id"), str):
        ids.append(response_body["id"])

    if not ids:
        match = _MEMORY_ID_PATH.match(path)
        if match:
            candidate = match.group("id")
            if candidate and candidate != "search":
                ids.append(candidate)

    # Bounded: a get_all over a large project would otherwise store thousands
    # of ids per row, in a table already holding payloads.
    return ids[:200]


def count_events(request_type: str, response_body: Any) -> int:
    """How many memories this request produced or returned."""
    results = _result_list(response_body)
    if results:
        return len(results)
    if request_type in ("get", "update") and isinstance(response_body, dict) and response_body.get("id"):
        return 1
    if request_type == "delete":
        return 1
    return 0


def summarize_result(request_type: str, response_body: Any) -> Optional[dict[str, Any]]:
    """A small digest of the response, for the panel header.

    Not the whole body: the memories themselves are hydrated live from their ids
    when the panel opens, so storing them here would be a second, staler copy.
    """
    if response_body is None:
        return None

    results = _result_list(response_body)
    summary: dict[str, Any] = {"count": len(results)}

    if request_type == "search" and results:
        scores = [r.get("score") for r in results if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]
        if scores:
            summary["top_score"] = round(max(scores), 4)
            summary["min_score"] = round(min(scores), 4)

    if request_type == "add" and results:
        events = [r.get("event") for r in results if isinstance(r, dict) and r.get("event")]
        if events:
            summary["events"] = sorted(set(events))

    if isinstance(response_body, dict):
        if isinstance(response_body.get("detail"), str):
            summary["detail"] = response_body["detail"][:500]
        if isinstance(response_body.get("message"), str):
            summary["message"] = response_body["message"][:500]
        if isinstance(response_body.get("relations"), list):
            summary["relations"] = len(response_body["relations"])

    return summary


def is_playground(headers: Any, body: Any) -> bool:
    """Whether this came from the dashboard's Recall playground.

    Playground traffic is real traffic, so it is logged - but it is not
    application traffic, so the Requests page can hide it. The marker is a
    header the dashboard sets, with a body-metadata fallback for clients that
    cannot set headers.
    """
    try:
        if str(headers.get("x-mem0-playground", "")).lower() in ("1", "true", "yes"):
            return True
    except AttributeError:
        pass
    if isinstance(body, dict):
        metadata = body.get("metadata")
        if isinstance(metadata, dict) and metadata.get("playground") is True:
            return True
    return False


def build_trace(
    *,
    method: str,
    path: str,
    query_params: Any,
    headers: Any,
    request_body: Optional[bytes],
    response_body: Optional[bytes],
    status_code: int,
) -> dict[str, Any]:
    """Everything the trace columns need, from one exchange.

    Never raises. A trace is diagnostic data; failing to build one must not
    turn into a failed request or a lost log row, so any surprise degrades to
    a row with the basics and an `error` note.
    """
    try:
        parsed_request = parse_body(request_body)
        parsed_response = parse_body(response_body)
        request_type = classify(method, path)

        error: Optional[str] = None
        if status_code >= 400:
            if isinstance(parsed_response, dict):
                detail = parsed_response.get("detail") or parsed_response.get("error")
                error = str(detail)[:1000] if detail is not None else f"HTTP {status_code}"
            else:
                error = f"HTTP {status_code}"

        return {
            "request_type": request_type,
            "entities": extract_entities(parsed_request, dict(query_params or {})),
            "event_count": count_events(request_type, parsed_response) if status_code < 400 else 0,
            "payload": redaction.capture(parsed_request),
            "result_summary": redaction.capture(summarize_result(request_type, parsed_response)),
            "memory_ids": extract_memory_ids(parsed_response, path) if status_code < 400 else [],
            "is_playground": is_playground(headers, parsed_request),
            "error": error,
        }
    except Exception:
        logger.warning("Failed to build request trace for %s %s", method, path, exc_info=True)
        return {
            "request_type": "other",
            "entities": [],
            "event_count": 0,
            "payload": None,
            "result_summary": None,
            "memory_ids": [],
            "is_playground": False,
            "error": "trace construction failed",
        }
