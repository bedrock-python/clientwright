"""Telemetry emitter lifecycle and the null backends."""

from __future__ import annotations

from clientwright.core.config import ObservabilityConfig
from clientwright.core.model import Attempt, ConnMetrics, FailureKind, Outcome, RequestInfo
from clientwright.core.telemetry.emitter import ClientTelemetry, outcome_label, status_label
from clientwright.core.telemetry.null import NullMetrics, NullTracer
from clientwright.core.testing import RecordingMetrics
from tests.helpers.telemetry import RecordingTracer

INFO = RequestInfo(method="GET", origin="https://a:443", url="https://a/u?token=x", route="/u")


def telemetry(metrics: RecordingMetrics | None) -> ClientTelemetry:
    return ClientTelemetry(
        service="svc",
        adapter="fake",
        seam="test",
        config=ObservabilityConfig(),
        metrics=metrics,
        tracer=None,
    )


# --- emitter ---


def test__call_lifecycle__records_call_attempts_and_balances_inflight() -> None:
    metrics = RecordingMetrics()
    emitter = telemetry(metrics)
    observation = emitter.call_start(INFO, started=0.0)
    attempt = Attempt(index=1, started=0.0, duration=0.1, outcome=Outcome(kind=None, status_code=200))
    emitter.attempt_end(observation, INFO, attempt)
    emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.2)
    assert metrics.inflight_balance == 0
    assert metrics.calls[0]["status"] == "200"
    assert metrics.calls[0]["outcome"] == "success"
    assert metrics.calls[0]["route"] == "/u"
    assert metrics.attempts[0]["outcome"] == "success"


def test__failure_without_response__status_none_and_kind_outcome() -> None:
    metrics = RecordingMetrics()
    emitter = telemetry(metrics)
    observation = emitter.call_start(INFO, started=0.0)
    emitter.call_end(observation, INFO, Outcome(kind=FailureKind.CONNECT_TIMEOUT), duration=0.2)
    assert metrics.calls[0]["status"] == "none"
    assert metrics.calls[0]["outcome"] == "connect_timeout"
    assert metrics.inflight_balance == 0


def test__metrics_disabled_in_config__nothing_recorded() -> None:
    metrics = RecordingMetrics()
    emitter = ClientTelemetry(
        service="svc",
        adapter="fake",
        seam="test",
        config=ObservabilityConfig(metrics=False),
        metrics=metrics,
        tracer=None,
    )
    observation = emitter.call_start(INFO, started=0.0)
    emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)
    assert metrics.calls == []
    assert metrics.inflight == []


def test__attempt_with_conn_metrics__annotates_the_call_span() -> None:
    tracer = RecordingTracer()
    emitter = ClientTelemetry(
        service="svc",
        adapter="fake",
        seam="test",
        config=ObservabilityConfig(),
        metrics=None,
        tracer=tracer,
    )
    observation = emitter.call_start(INFO, started=0.0)
    conn = ConnMetrics(dns=0.01, pool_wait=0.002, reused=True, http_version="2")
    emitter.attempt_end(observation, INFO, Attempt(1, 0.0, 0.1, Outcome(kind=None, status_code=200), conn=conn))
    attributes = tracer.spans[0].attributes
    assert attributes["http.connection.dns_duration"] == 0.01
    assert attributes["http.connection.pool_wait_duration"] == 0.002
    assert attributes["http.connection.reused"] is True
    assert attributes["network.protocol.version"] == "2"
    assert "http.connection.connect_duration" not in attributes  # an unseen phase is not a zero


def test__attempt_without_conn_metrics__leaves_the_span_alone() -> None:
    tracer = RecordingTracer()
    emitter = ClientTelemetry(
        service="svc",
        adapter="fake",
        seam="test",
        config=ObservabilityConfig(),
        metrics=None,
        tracer=tracer,
    )
    observation = emitter.call_start(INFO, started=0.0)
    emitter.attempt_end(observation, INFO, Attempt(1, 0.0, 0.1, Outcome(kind=None, status_code=200)))
    assert set(tracer.spans[0].attributes) == {"http.request.method", "server.origin", "url.full"}


def test__labels__helpers() -> None:
    assert outcome_label(Outcome(kind=None, status_code=200)) == "success"
    assert outcome_label(Outcome(kind=FailureKind.STATUS, status_code=503)) == "status"
    assert status_label(Outcome(kind=FailureKind.CONNECT_ERROR)) == "none"


# --- null objects ---


def test__null_backends__accept_everything() -> None:
    metrics = NullMetrics()
    metrics.record_call(
        service="s",
        adapter="a",
        seam="t",
        method="GET",
        origin="o",
        route="r",
        status="200",
        outcome="success",
        duration=0.1,
    )
    metrics.record_body_duration(service="s", adapter="a", seam="t", method="GET", origin="o", route="r", duration=0.1)
    metrics.record_attempt(
        service="s", adapter="a", seam="t", method="GET", origin="o", outcome="success", duration=0.1
    )
    metrics.inflight_delta(service="s", adapter="a", seam="t", origin="o", delta=1)
    metrics.record_circuit_state(service="s", adapter="a", key="o", state="open")
    metrics.record_redirect_hop(service="s", adapter="a", seam="t")
    metrics.record_retry_skipped(service="s", adapter="a", seam="t", reason="budget")
    metrics.record_uninstrumented_call(service="s", adapter="a", seam="t")
    tracer = NullTracer()
    span = tracer.start_span("x", attributes={})
    span.set_attribute("k", "v")
    span.record_failure("boom")
    span.end()
    tracer.inject_context({})


def test__telemetry_helpers__hit_the_null_sinks_without_branching() -> None:
    emitter = telemetry(None)  # metrics=None resolves to NullMetrics internally
    observation = emitter.call_start(INFO, started=0.0)
    emitter.redirect_hop(observation)
    emitter.retry_skipped("budget")
    emitter.circuit_state_changed("key", "open")
    emitter.uninstrumented_call()
    emitter.record_body_duration(INFO, 0.1)
    emitter.call_end(observation, INFO, Outcome(kind=None, status_code=200), duration=0.1)
