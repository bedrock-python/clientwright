"""Behavioral conformance of the httpx SYNC adapter: same engine, blocking IO."""

from __future__ import annotations

import httpx
import pytest

import clientwright
from clientwright import AdapterDeps, ClientConfig, RetryConfig, TimeoutConfig
from clientwright.adapters.httpx import HttpxCircuitOpenError, HttpxTooManyRedirectsError
from clientwright.core.config import CircuitBreakerConfig
from clientwright.core.testing import OriginServer, RecordingMetrics

from ..conftest import base_config

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)


def build(config: ClientConfig, deps: AdapterDeps) -> httpx.Client:
    client = clientwright.build_sync("httpx", config, deps)
    assert type(client) is httpx.Client
    return client


def test__echo__works_via_native_client(origin: OriginServer, deps: AdapterDeps) -> None:
    client = build(base_config(origin), deps)
    response = client.get("/echo")
    assert response.status_code == 200
    client.close()


def test__503_then_200__retried(origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps) -> None:
    client = build(base_config(origin, retry=FAST_RETRY), deps)
    response = client.get("/flaky/s1/2")
    assert response.status_code == 200
    assert origin.request_count("/flaky/s1/2") == 3
    assert len(metrics.attempts) == 3
    client.close()


def test__redirect_chain__followed_with_one_logical_call(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = build(base_config(origin), deps)
    response = client.get("/redirect/2")
    assert response.status_code == 200
    assert len(metrics.redirect_hops) == 2
    assert len(metrics.calls) == 1
    client.close()


def test__redirect_loop__raises_dual_family_error(origin: OriginServer, deps: AdapterDeps) -> None:
    client = build(base_config(origin, max_redirects=2), deps)
    with pytest.raises(HttpxTooManyRedirectsError):
        client.get("/redirect-loop")
    client.close()


def test__soft_deadline__clamps_read_phase(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(origin, timeout=TimeoutConfig(total=0.5, connect=1.0), retry=None)
    client = build(config, deps)
    with pytest.raises(httpx.TimeoutException):
        client.get("/slow/3")
    client.close()


def test__circuit_breaker__opens_after_threshold(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = base_config(
        origin,
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    client = build(config, deps)
    for _ in range(2):
        assert client.get("/status/503").status_code == 503
    with pytest.raises(HttpxCircuitOpenError):
        client.get("/status/503")
    assert metrics.inflight_balance == 0
    client.close()


def test__runtime_shared_between_clients__breaker_state_survives(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(
        origin,
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    first = clientwright.build_sync_handle("httpx", config, deps)
    client_one = first.client
    assert isinstance(client_one, httpx.Client)
    for _ in range(2):
        client_one.get("/status/503")
    client_one.close()
    shared = AdapterDeps(metrics=deps.metrics, runtime=first.runtime)
    client_two = build(config, shared)
    with pytest.raises(HttpxCircuitOpenError):
        client_two.get("/status/503")  # APP-scope runtime carried the open circuit over
    client_two.close()
