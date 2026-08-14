"""OpenTelemetry backend for the SDK-free tracer protocol.

The client span is attached to the ambient context for its lifetime, so
``inject_context`` propagates THIS span to the server (not merely the parent),
and any spans the server links to point at the client call. Attach and detach
happen in the same task: the engine opens the span and ends it in a finally
block without crossing task boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

try:
    from opentelemetry import context as otel_context
    from opentelemetry import propagate, trace
    from opentelemetry.trace import SpanKind, Status, StatusCode, set_span_in_context
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("OpenTelemetry tracing requires clientwright[tracing]; install it.") from exc


class OpenTelemetrySpan:
    """SpanProtocol backend over an OTel span attached to the current context."""

    __slots__ = ("_span", "_token")

    def __init__(self, span: trace.Span, token: object) -> None:
        self._span = span
        self._token = token

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        self._span.set_attribute(key, value)

    def record_failure(self, description: str) -> None:
        self._span.set_status(Status(StatusCode.ERROR, description))

    def end(self) -> None:
        try:
            otel_context.detach(self._token)  # type: ignore[arg-type]
        finally:
            self._span.end()


class OpenTelemetryTracer:
    """TracerProtocol backend over opentelemetry-api."""

    __slots__ = ("_tracer",)

    def __init__(self, tracer_provider: trace.TracerProvider | None = None) -> None:
        self._tracer = trace.get_tracer("clientwright", tracer_provider=tracer_provider)

    def start_span(self, name: str, *, attributes: Mapping[str, str | int | float | bool]) -> OpenTelemetrySpan:
        span = self._tracer.start_span(name, kind=SpanKind.CLIENT, attributes=dict(attributes))
        token = otel_context.attach(set_span_in_context(span))
        return OpenTelemetrySpan(span, token)

    def inject_context(self, headers: MutableMapping[str, str]) -> None:
        propagate.inject(headers)


__all__ = ["OpenTelemetrySpan", "OpenTelemetryTracer"]
