"""ContextVar suppression against double accounting.

When one instrumented client physically sits on top of another (requests over
urllib3) or a seam recurses into itself, the inner layer must stay silent: the
outer layer owns instrumentation.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_DEPTH: ContextVar[int] = ContextVar("clientwright_suppress_depth", default=0)


def is_suppressed() -> bool:
    return _DEPTH.get() > 0


@contextmanager
def suppressed() -> Generator[None]:
    token = _DEPTH.set(_DEPTH.get() + 1)
    try:
        yield
    finally:
        _DEPTH.reset(token)


__all__ = ["is_suppressed", "suppressed"]
