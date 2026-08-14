"""aiohttp TraceConfig: the bypass sentinel and connection-level timings.

The callbacks are driven BY HAND with fake params objects - no sockets. The
contract under test is what lands in ``current_conn_metrics()`` for the task
that made the request, and when the ``uninstrumented_calls_total`` sentinel
fires.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="requires the [aiohttp] extra")

from clientwright.adapters.aiohttp.capabilities import CAPABILITIES  # noqa: E402
from clientwright.adapters.aiohttp.normalize import AsyncAiohttpNormalizer  # noqa: E402
from clientwright.adapters.aiohttp.trace import ENGINE_ACTIVE, build_trace_config, current_conn_metrics  # noqa: E402
from clientwright.core.config import ObservabilityConfig  # noqa: E402
from clientwright.core.telemetry.emitter import ClientTelemetry  # noqa: E402


class _RecordingMetrics:
    """ClientMetricsProtocol fake counting only what these tests drive."""

    def __init__(self) -> None:
        self.uninstrumented = 0

    def record_call(self, **kwargs: Any) -> None:
        return None

    def record_body_duration(self, **kwargs: Any) -> None:
        return None

    def record_attempt(self, **kwargs: Any) -> None:
        return None

    def inflight_delta(self, **kwargs: Any) -> None:
        return None

    def record_circuit_state(self, **kwargs: Any) -> None:
        return None

    def record_redirect_hop(self, **kwargs: Any) -> None:
        return None

    def record_retry_skipped(self, **kwargs: Any) -> None:
        return None

    def record_uninstrumented_call(self, **kwargs: Any) -> None:
        self.uninstrumented += 1


class _Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


class _Callbacks:
    """Named access to the coroutines build_trace_config registered."""

    def __init__(self, trace_config: aiohttp.TraceConfig) -> None:
        self.start = trace_config.on_request_start[0]
        self.dns_start = trace_config.on_dns_resolvehost_start[0]
        self.dns_end = trace_config.on_dns_resolvehost_end[0]
        self.connect_start = trace_config.on_connection_create_start[0]
        self.connect_end = trace_config.on_connection_create_end[0]
        self.reuseconn = trace_config.on_connection_reuseconn[0]
        self.queued_start = trace_config.on_connection_queued_start[0]
        self.queued_end = trace_config.on_connection_queued_end[0]


def _telemetry(metrics: _RecordingMetrics) -> ClientTelemetry:
    return ClientTelemetry(
        service="svc",
        adapter="aiohttp",
        seam=CAPABILITIES.seam,
        config=ObservabilityConfig(),
        metrics=metrics,
        tracer=None,
    )


def _build(metrics: _RecordingMetrics | None = None) -> tuple[_Callbacks, _Clock]:
    clock = _Clock()
    trace_config = build_trace_config(_telemetry(metrics or _RecordingMetrics()), clock)
    return _Callbacks(trace_config), clock


async def test__request_outside_the_engine__fires_the_uninstrumented_sentinel() -> None:
    metrics = _RecordingMetrics()
    callbacks, _ = _build(metrics)
    await callbacks.start(None, SimpleNamespace(), SimpleNamespace())
    assert metrics.uninstrumented == 1


async def test__request_inside_the_engine__not_counted_as_a_bypass() -> None:
    metrics = _RecordingMetrics()
    callbacks, _ = _build(metrics)
    token = ENGINE_ACTIVE.set(True)
    try:
        await callbacks.start(None, SimpleNamespace(), SimpleNamespace())
    finally:
        ENGINE_ACTIVE.reset(token)
    assert metrics.uninstrumented == 0


def test__no_request_started__conn_metrics_absent() -> None:
    assert current_conn_metrics() is None


async def test__request_started__conn_metrics_exist_but_carry_nothing_yet() -> None:
    callbacks, _ = _build()
    await callbacks.start(None, SimpleNamespace(), SimpleNamespace())
    metrics = current_conn_metrics()
    assert metrics is not None
    assert (metrics.dns, metrics.connect, metrics.pool_wait, metrics.reused) == (None, None, None, None)


async def test__dns_connect_and_pool_wait__timed_into_conn_metrics() -> None:
    callbacks, clock = _build()
    ns = SimpleNamespace()
    await callbacks.start(None, ns, ns)
    clock.now = 20.0
    await callbacks.queued_start(None, ns, ns)
    clock.now = 20.5
    await callbacks.queued_end(None, ns, ns)
    clock.now = 21.0
    await callbacks.dns_start(None, ns, ns)
    clock.now = 21.25
    await callbacks.dns_end(None, ns, ns)
    clock.now = 22.0
    await callbacks.connect_start(None, ns, ns)
    clock.now = 22.75
    await callbacks.connect_end(None, ns, ns)
    metrics = current_conn_metrics()
    assert metrics is not None
    assert metrics.pool_wait == 0.5
    assert metrics.dns == 0.25
    assert metrics.connect == 0.75
    assert metrics.reused is False


async def test__reused_connection__flagged_without_connect_timing() -> None:
    callbacks, _ = _build()
    ns = SimpleNamespace()
    await callbacks.start(None, ns, ns)
    await callbacks.reuseconn(None, ns, ns)
    metrics = current_conn_metrics()
    assert metrics is not None
    assert metrics.reused is True
    assert metrics.connect is None


async def test__normalizer_conn_metrics__reads_the_current_trace() -> None:
    callbacks, _ = _build()
    ns = SimpleNamespace()
    await callbacks.start(None, ns, ns)
    await callbacks.reuseconn(None, ns, ns)
    normalizer = AsyncAiohttpNormalizer()
    metrics = normalizer.conn_metrics(SimpleNamespace(native=None))  # type: ignore[arg-type]
    assert metrics is not None
    assert metrics.reused is True
