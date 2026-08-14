"""Ambient-context seams: header propagation and deadline budgets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class HeaderProvider(Protocol):
    """Supplies outgoing headers from ambient context (request-id, trace-id, ...).

    Injected once per logical call, before any logging; existing header values
    set by the caller are never overwritten.
    """

    def __call__(self) -> Mapping[str, str]: ...


@runtime_checkable
class DeadlineSource(Protocol):
    """Remaining time budget of the surrounding operation, in seconds.

    ``None`` means no ambient budget. The engine intersects this with the
    configured total timeout and any per-call override.
    """

    def remaining(self) -> float | None: ...


__all__ = ["DeadlineSource", "HeaderProvider"]
