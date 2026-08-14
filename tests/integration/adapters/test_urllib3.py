"""Behavioral conformance of the urllib3 adapter against a real origin.

Covers both retry modes: OWNED (the engine runs the loop) and DELEGATED (the
documented carve-out - urllib3's native Retry runs the loop below the seam,
per-attempt metrics honestly absent).
"""

from __future__ import annotations

import pytest

urllib3 = pytest.importorskip("urllib3", reason="requires the [urllib3] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps, ClientConfig, RetryConfig, TimeoutConfig  # noqa: E402
from clientwright.adapters.urllib3 import (  # noqa: E402
    Urllib3CircuitOpenError,
    Urllib3TooManyRedirectsError,
    call_options,
)
from clientwright.core.config import CircuitBreakerConfig, RetryMode  # noqa: E402
from clientwright.core.engine.suppress import suppressed  # noqa: E402
from clientwright.core.testing import OriginServer, RecordingMetrics  # noqa: E402

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)
FAST_DELEGATED = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0, mode=RetryMode.DELEGATED)


def config_for(**overrides: object) -> ClientConfig:
    return ClientConfig(service_name="conformance", **overrides)  # type: ignore[arg-type]


def build(config: ClientConfig, deps: AdapterDeps) -> urllib3.PoolManager:
    client = clientwright.build_sync("urllib3", config, deps)
    assert type(client) is urllib3.PoolManager
    return client


# --- basics ---


def test__echo__native_manager_and_injected_headers(origin: OriginServer, metrics: RecordingMetrics) -> None:
    deps = AdapterDeps(metrics=metrics, header_providers=(lambda: {"X-Request-ID": "rid-1"},))
    manager = build(config_for(headers={"X-Static": "yes"}), deps)
    response = manager.request("GET", origin.url + "/echo", headers={"X-Static": "caller-wins"})
    payload = response.json()
    assert payload["headers"]["x-request-id"] == "rid-1"
    assert payload["headers"]["x-static"] == "caller-wins"  # caller headers never overwritten
    manager.clear()


def test__call_options_route__becomes_metric_label(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    manager = build(config_for(), deps)
    with call_options(route="/echo-route"):
        manager.request("GET", origin.url + "/echo")
    manager.clear()
    assert metrics.calls[0]["route"] == "/echo-route"


def test__suppressed_context__bypasses_the_engine_silently(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    manager = build(config_for(), deps)
    with suppressed():
        response = manager.request("GET", origin.url + "/echo")
    assert response.status == 200  # native path still works...
    assert len(metrics.calls) == 0  # ...and the inner layer stayed silent
    manager.clear()


# --- owned retries ---


def test__503_then_200__retried_to_success(origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps) -> None:
    manager = build(config_for(retry=FAST_RETRY), deps)
    response = manager.request("GET", origin.url + "/flaky/u1/2")
    assert response.status == 200
    assert origin.request_count("/flaky/u1/2") == 3
    assert len(metrics.attempts) == 3
    manager.clear()


def test__post__not_retried_without_idempotency(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    manager = build(config_for(retry=FAST_RETRY), deps)
    response = manager.request("POST", origin.url + "/flaky/u2/1", body=b"data")
    assert response.status == 503
    assert origin.request_count("/flaky/u2/1") == 1
    assert metrics.retry_skips[0]["reason"] == "method"
    manager.clear()


# --- delegated retries ---


def test__flaky__recovered_by_native_machinery(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    manager = build(config_for(retry=FAST_DELEGATED), deps)
    response = manager.request("GET", origin.url + "/flaky/ud1/2")
    assert response.status == 200
    assert origin.request_count("/flaky/ud1/2") == 3  # native Retry did the work
    assert len(metrics.attempts) == 0  # per-attempt metrics honestly absent
    assert len(metrics.calls) == 1  # the logical call is still one record
    manager.clear()


# --- redirects ---


def test__chain__followed_by_engine_with_hop_metric(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    manager = build(config_for(), deps)
    response = manager.request("GET", origin.url + "/redirect/3")
    assert response.status == 200
    assert len(metrics.redirect_hops) == 3
    assert len(metrics.calls) == 1  # one logical call despite hops
    manager.clear()


def test__loop__raises_dual_family_too_many_redirects(origin: OriginServer, deps: AdapterDeps) -> None:
    manager = build(config_for(max_redirects=3), deps)
    with pytest.raises(Urllib3TooManyRedirectsError) as excinfo:
        manager.request("GET", origin.url + "/redirect-loop")
    assert isinstance(excinfo.value, urllib3.exceptions.MaxRetryError)
    manager.clear()


def test__post_303__demoted_to_get_with_dropped_body(origin: OriginServer, deps: AdapterDeps) -> None:
    manager = build(config_for(), deps)
    response = manager.request("POST", origin.url + "/redirect/1", body=b"body")
    assert response.status == 200
    payload = response.json()
    assert payload["method"] == "GET"
    assert payload["body"] == ""
    manager.clear()


# --- deadline ---


def test__soft_deadline__clamps_read_phase(origin: OriginServer, deps: AdapterDeps) -> None:
    manager = build(config_for(timeout=TimeoutConfig(total=0.5, connect=1.0), retry=None), deps)
    with pytest.raises(urllib3.exceptions.TimeoutError):
        manager.request("GET", origin.url + "/slow/3")
    manager.clear()


def test__deadline_header__stamped_with_remaining_budget(origin: OriginServer, deps: AdapterDeps) -> None:
    manager = build(config_for(timeout=TimeoutConfig(total=30.0), deadline_header="X-Deadline-Ms"), deps)
    response = manager.request("GET", origin.url + "/echo")
    stamped = int(response.json()["headers"]["x-deadline-ms"])
    assert 0 < stamped <= 30_000
    manager.clear()


# --- circuit breaker ---


def test__threshold__opens_and_rejects_without_touching_origin(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = config_for(
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    manager = build(config, deps)
    for _ in range(2):
        assert manager.request("GET", origin.url + "/status/503").status == 503
    before = origin.request_count("/status/503")
    with pytest.raises(Urllib3CircuitOpenError) as excinfo:
        manager.request("GET", origin.url + "/status/503")
    assert isinstance(excinfo.value, urllib3.exceptions.HTTPError)
    assert origin.request_count("/status/503") == before  # rejected locally
    assert metrics.inflight_balance == 0
    manager.clear()
