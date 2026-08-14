"""SDK-free observability seams.

The kernel records everything through these protocols; concrete backends
(Prometheus, OpenTelemetry) live in ``clientwright.adapters.observability``
behind extras and are never imported by the core.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClientMetricsProtocol(Protocol):
    """Sink for the frozen ``http_client_*`` metric families.

    Label semantics: ``outcome`` is ``"success"`` or a ``FailureKind`` value;
    ``status`` is the HTTP status as a string or ``"none"`` when the call
    produced no response; ``adapter``/``seam`` are per-adapter constants.
    """

    def record_call(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        status: str,
        outcome: str,
        duration: float,
    ) -> None: ...

    def record_body_duration(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        route: str,
        duration: float,
    ) -> None: ...

    def record_attempt(
        self,
        *,
        service: str,
        adapter: str,
        seam: str,
        method: str,
        origin: str,
        outcome: str,
        duration: float,
    ) -> None: ...

    def inflight_delta(self, *, service: str, adapter: str, seam: str, origin: str, delta: int) -> None: ...

    def record_circuit_state(self, *, service: str, adapter: str, key: str, state: str) -> None: ...

    def record_redirect_hop(self, *, service: str, adapter: str, seam: str) -> None: ...

    def record_retry_skipped(self, *, service: str, adapter: str, seam: str, reason: str) -> None: ...

    def record_uninstrumented_call(self, *, service: str, adapter: str, seam: str) -> None: ...


@runtime_checkable
class MaskerProtocol(Protocol):
    """Value-level masker applied to telemetry strings before they are emitted.

    The key-based redaction (``sensitive_query_params``) runs first; the masker
    then sees the whole string and may scrub PII that key lists cannot reach -
    an email in a path segment, a card number in a free-form value. Any
    ``(str) -> str`` callable qualifies: a regex substitution, a
    format-preserving masker, a locally hosted NER model.

    Contract: synchronous, and cheap enough to run 2-3 times per HTTP call.
    A raising masker never breaks the request - the emitter replaces the whole
    value with ``[redacted]`` (fail closed) and warns once per client.
    """

    def __call__(self, value: str) -> str: ...


@runtime_checkable
class SpanProtocol(Protocol):
    """One client span; ended exactly once, in a finally block."""

    def set_attribute(self, key: str, value: str | int | float | bool) -> None: ...

    def record_failure(self, description: str) -> None: ...

    def end(self) -> None: ...


@runtime_checkable
class TracerProtocol(Protocol):
    """Opens client spans and injects propagation headers."""

    def start_span(self, name: str, *, attributes: Mapping[str, str | int | float | bool]) -> SpanProtocol: ...

    def inject_context(self, headers: MutableMapping[str, str]) -> None: ...


__all__ = ["ClientMetricsProtocol", "MaskerProtocol", "SpanProtocol", "TracerProtocol"]
