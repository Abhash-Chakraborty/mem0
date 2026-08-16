"""Tests for the in-memory log buffer that backs the dashboard's log view.

The subtle failure this guards against is double capture: attaching the same
handler to both a child logger and its parent records one line twice, because
the record passes every handler on its way up the chain.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def stream():
    import log_stream

    # Each test starts from a clean buffer and no attached handlers, so state
    # cannot leak between them through the module-level globals.
    _detach_all(log_stream)
    with log_stream._buffer_lock:
        log_stream._buffer.clear()
    yield log_stream
    _detach_all(log_stream)


def _detach_all(log_stream):
    names = [None, *log_stream._DIRECT_LOGGERS]
    for name in names:
        logger = logging.getLogger(name) if name else logging.getLogger()
        for handler in list(logger.handlers):
            if isinstance(handler, log_stream.RingBufferHandler):
                logger.removeHandler(handler)


class TestCapture:
    def test_root_records_are_captured(self, stream):
        stream.install()
        logging.getLogger("app.thing").warning("hello")
        messages = [e["message"] for e in stream.snapshot()]
        assert "hello" in messages

    def test_record_is_captured_exactly_once(self, stream):
        """A propagating child must not be recorded once per handler in the chain."""
        stream.install()
        logging.getLogger("uvicorn.access").info("one-line")
        assert [e["message"] for e in stream.snapshot()].count("one-line") == 1

    def test_non_propagating_logger_is_still_captured(self, stream):
        """Uvicorn sets propagate=False, which would otherwise bypass root."""
        isolated = logging.getLogger("uvicorn.error")
        original = isolated.propagate
        isolated.propagate = False
        try:
            stream.install()
            isolated.error("isolated-line")
            messages = [e["message"] for e in stream.snapshot()]
            assert messages.count("isolated-line") == 1
        finally:
            isolated.propagate = original

    def test_install_twice_does_not_double_capture(self, stream):
        stream.install()
        stream.install()
        logging.getLogger("app").warning("once-only")
        assert [e["message"] for e in stream.snapshot()].count("once-only") == 1


class TestBuffer:
    def test_buffer_is_bounded(self, stream):
        stream.install()
        for i in range(stream.BUFFER_SIZE + 50):
            logging.getLogger("flood").info("line-%d", i)
        assert len(stream.snapshot(limit=stream.BUFFER_SIZE * 2)) <= stream.BUFFER_SIZE

    def test_oldest_records_are_dropped_first(self, stream):
        stream.install()
        for i in range(stream.BUFFER_SIZE + 10):
            logging.getLogger("flood").info("line-%d", i)
        messages = [e["message"] for e in stream.snapshot(limit=stream.BUFFER_SIZE * 2)]
        assert "line-0" not in messages
        assert f"line-{stream.BUFFER_SIZE + 9}" in messages

    def test_level_filter(self, stream):
        stream.install()
        logging.getLogger("app").info("an-info")
        logging.getLogger("app").error("an-error")
        errors = [e["message"] for e in stream.snapshot(level="ERROR")]
        assert errors == ["an-error"]

    def test_limit_returns_most_recent(self, stream):
        stream.install()
        for i in range(10):
            logging.getLogger("app").info("m-%d", i)
        assert [e["message"] for e in stream.snapshot(limit=2)] == ["m-8", "m-9"]


class TestSerialization:
    def test_exception_is_reduced_to_type_and_message(self, stream):
        """Full tracebacks do not belong in a browser payload."""
        stream.install()
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger("app").exception("it failed")
        entry = stream.snapshot()[-1]
        assert entry["error"] == "ValueError: boom"
        assert "Traceback" not in (entry["error"] or "")

    def test_request_id_is_carried_when_present(self, stream):
        stream.install()
        logger = logging.getLogger("app")
        logger.info("with-id", extra={"request_id": "req-123"})
        assert stream.snapshot()[-1]["request_id"] == "req-123"

    def test_handler_swallows_unserializable_records(self, stream):
        """A record this handler cannot render must not propagate an exception.

        Asserted against the handler directly: routing it through the logging
        module instead would measure whatever other handlers are attached
        (pytest installs its own), not this one.
        """
        handler = stream.RingBufferHandler()
        bad = logging.LogRecord(
            name="app",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="missing %s %s",  # more placeholders than args
            args=("only-one",),
            exc_info=None,
        )
        handler.emit(bad)  # must return rather than raise
        assert all(e["message"] != "missing %s %s" for e in stream.snapshot())
