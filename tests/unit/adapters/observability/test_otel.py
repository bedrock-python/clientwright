"""OpenTelemetry sink units: span lifecycle, failure status, context propagation."""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry", reason="requires the [tracing] extra")
pytest.importorskip("opentelemetry.sdk", reason="requires opentelemetry-sdk (test dependency)")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from clientwright.adapters.observability._tracing.otel import OpenTelemetryTracer


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: InMemorySpanExporter) -> OpenTelemetryTracer:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OpenTelemetryTracer(tracer_provider=provider)


def test__span__client_kind_with_attributes(tracer: OpenTelemetryTracer, exporter: InMemorySpanExporter) -> None:
    span = tracer.start_span("HTTP GET", attributes={"http.request.method": "GET"})
    span.set_attribute("http.response.status_code", 200)
    span.end()
    (exported,) = exporter.get_finished_spans()
    assert exported.kind is SpanKind.CLIENT
    assert exported.attributes is not None
    assert exported.attributes["http.request.method"] == "GET"
    assert exported.attributes["http.response.status_code"] == 200
    assert exported.status.status_code is StatusCode.UNSET


def test__record_failure__sets_error_status(tracer: OpenTelemetryTracer, exporter: InMemorySpanExporter) -> None:
    span = tracer.start_span("HTTP GET", attributes={})
    span.record_failure("connect_error")
    span.end()
    (exported,) = exporter.get_finished_spans()
    assert exported.status.status_code is StatusCode.ERROR
    assert exported.status.description == "connect_error"


def test__inject_context__propagates_the_open_client_span(
    tracer: OpenTelemetryTracer, exporter: InMemorySpanExporter
) -> None:
    span = tracer.start_span("HTTP GET", attributes={})
    headers: dict[str, str] = {}
    tracer.inject_context(headers)
    span.end()
    (exported,) = exporter.get_finished_spans()
    assert "traceparent" in headers
    trace_id = f"{exported.context.trace_id:032x}"
    span_id = f"{exported.context.span_id:016x}"
    assert trace_id in headers["traceparent"]
    assert span_id in headers["traceparent"]


def test__end__detaches_context_between_spans(tracer: OpenTelemetryTracer, exporter: InMemorySpanExporter) -> None:
    first = tracer.start_span("HTTP GET", attributes={})
    first.end()
    headers: dict[str, str] = {}
    tracer.inject_context(headers)
    # After the span ended, its context is detached: nothing to propagate.
    assert "traceparent" not in headers
