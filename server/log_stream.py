"""In-process log capture for the dashboard's log view.

Rather than shipping logs to a file and tailing it - which needs a writable
volume, rotation, and a second source of truth - this attaches a handler to the
root logger and keeps the last N records in memory. Two consumers are served
from the same buffer: a snapshot for the initial page load, and a live feed for
the stream that follows it.

Bounded on purpose. The deque caps memory, and each subscriber has its own
bounded queue that drops the oldest record when a slow client stops keeping up -
a dashboard left open on a laptop lid must never grow the server's heap or block
the thread that is trying to log.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

BUFFER_SIZE = 1000
# Per-subscriber backlog. Small: a client this far behind is not reading.
SUBSCRIBER_QUEUE_SIZE = 200

_buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER_SIZE)
_buffer_lock = threading.Lock()
_subscribers: set[asyncio.Queue] = set()
_subscribers_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None

# Uvicorn configures these with propagate=False, so records logged through them
# never reach the root logger and the handler has to be attached directly.
# Without this the log view stays empty on an idle server - which reads as
# broken rather than quiet, because request lines are what you expect to see.
_DIRECT_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _serialize(record: logging.LogRecord) -> dict[str, Any]:
    return {
        "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "request_id": getattr(record, "request_id", None),
        # Only the exception's type and message; a full traceback in the browser
        # is noise and can carry internals that do not belong in a UI.
        "error": (
            f"{record.exc_info[0].__name__}: {record.exc_info[1]}"
            if record.exc_info and record.exc_info[0]
            else None
        ),
    }


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = _serialize(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            return

        with _buffer_lock:
            _buffer.append(entry)

        # Handlers run on whatever thread logged, so hand the record to the
        # event loop rather than touching asyncio primitives directly.
        loop = _loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(_fanout, entry)
        except RuntimeError:
            pass


def _fanout(entry: dict[str, Any]) -> None:
    with _subscribers_lock:
        targets = list(_subscribers)
    for queue in targets:
        if queue.full():
            # Drop this subscriber's oldest record instead of blocking.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass


def _attach(logger: logging.Logger, handler: logging.Handler, level: int) -> None:
    if any(isinstance(h, RingBufferHandler) for h in logger.handlers):
        return
    logger.addHandler(handler)
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)


def install(level: int = logging.INFO) -> None:
    """Capture log records into the ring buffer.

    Attaching to the root logger covers everything that propagates. Uvicorn's
    loggers are only attached to when they have propagation switched off, since
    otherwise their records already reach root - attaching to both a child and
    its parent would record the same line twice, once per handler the record
    passes on its way up.

    Safe to call more than once; each logger is checked before attaching.
    """
    handler = RingBufferHandler()
    handler.setLevel(level)

    _attach(logging.getLogger(), handler, level)
    for name in _DIRECT_LOGGERS:
        logger = logging.getLogger(name)
        if not logger.propagate:
            _attach(logger, handler, level)


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Record the loop that live subscribers are waiting on."""
    global _loop
    _loop = loop


def snapshot(limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
    with _buffer_lock:
        entries = list(_buffer)
    if level:
        wanted = level.upper()
        entries = [e for e in entries if e["level"] == wanted]
    return entries[-limit:]


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    with _subscribers_lock:
        _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    with _subscribers_lock:
        _subscribers.discard(queue)


def subscriber_count() -> int:
    with _subscribers_lock:
        return len(_subscribers)
