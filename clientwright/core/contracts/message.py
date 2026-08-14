"""Views over native request/response objects plus the normalizer contracts.

The engine talks to these views only; it never reads ``.native``. A normalizer
is the WHOLE per-client contract: wrap, classify, freeze/rewind/discard and
stream wrapping. It comes in async and sync flavors because freeze/rewind/
discard genuinely do I/O.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any, Protocol, runtime_checkable

from ..model import ConnMetrics, FailureKind, Outcome, RequestInfo, ResolvedTimeouts


@runtime_checkable
class RequestView(Protocol):
    """Mutable view over a native in-flight request."""

    @property
    def native(self) -> Any: ...

    @property
    def info(self) -> RequestInfo: ...

    @property
    def headers(self) -> MutableMapping[str, str]: ...

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        """Per-call timeouts set by the CALLER, or None when nothing was set."""
        ...

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        """Install the engine's per-attempt timeout plan into the native request."""
        ...

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        """Point the request at a new URL before sending (owned redirects, balancing)."""
        ...


@runtime_checkable
class ResponseView(Protocol):
    """Read-only view over a native response."""

    @property
    def native(self) -> Any: ...

    @property
    def status_code(self) -> int: ...

    def header(self, name: str) -> str | None: ...

    @property
    def location(self) -> str | None: ...


class AsyncNormalizer(Protocol):
    """Async adapter contract; roughly 60-120 lines per client."""

    def wrap_request(self, native: Any) -> RequestView: ...

    def wrap_response(self, native: Any) -> ResponseView: ...

    def classify_error(self, exc: BaseException) -> FailureKind: ...

    def classify_response(self, response: ResponseView) -> Outcome:
        """Default status classification lives in the engine; override only where
        failures arrive NOT as exceptions."""
        ...

    async def freeze(self, request: RequestView) -> bool:
        """Make the body replayable. False means a repeat is forbidden."""
        ...

    async def rewind(self, request: RequestView) -> None: ...

    async def discard(self, response: ResponseView) -> None:
        """MANDATORY before a repeat - otherwise the connection never returns to the pool."""
        ...

    def wrap_stream(self, response: ResponseView, on_done: Callable[[Outcome, float], None]) -> None:
        """boundary=full: wrap the body stream so read duration and errors reach
        telemetry. No-op where there is nothing to wrap."""
        ...

    def conn_metrics(self, response: ResponseView) -> ConnMetrics | None: ...


class SyncNormalizer(Protocol):
    """Sync twin of AsyncNormalizer; freeze/rewind/discard are blocking calls."""

    def wrap_request(self, native: Any) -> RequestView: ...

    def wrap_response(self, native: Any) -> ResponseView: ...

    def classify_error(self, exc: BaseException) -> FailureKind: ...

    def classify_response(self, response: ResponseView) -> Outcome: ...

    def freeze(self, request: RequestView) -> bool: ...

    def rewind(self, request: RequestView) -> None: ...

    def discard(self, response: ResponseView) -> None: ...

    def wrap_stream(self, response: ResponseView, on_done: Callable[[Outcome, float], None]) -> None: ...

    def conn_metrics(self, response: ResponseView) -> ConnMetrics | None: ...


__all__ = [
    "AsyncNormalizer",
    "RequestView",
    "ResponseView",
    "SyncNormalizer",
]
