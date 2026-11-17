"""Monotonic nested spans for the existing local workflow."""

import time
from contextlib import contextmanager
from contextvars import ContextVar

call_trace: ContextVar[dict | None] = ContextVar("local_ai_call_trace", default=None)


@contextmanager
def span(trace, name, parent=None):
    started = time.monotonic()
    try:
        yield
    finally:
        if trace is not None:
            origin = trace.get("_started", started)
            ended = time.monotonic()
            trace.setdefault("spans", []).append(
                {
                    "name": name,
                    "parent": parent,
                    "start_ms": round((started - origin) * 1000, 3),
                    "end_ms": round((ended - origin) * 1000, 3),
                    "duration_ms": round((ended - started) * 1000, 3),
                }
            )
