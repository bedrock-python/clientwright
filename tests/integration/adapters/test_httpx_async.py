"""Behavioral conformance of the httpx ASYNC adapter against a real origin."""

from __future__ import annotations

import asyncio

import pytest

httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps, ClientConfig, RetryConfig, TimeoutConfig  # noqa: E402
from clientwright.adapters.httpx import (  # noqa: E402
    IDEMPOTENT_EXTENSION,
    ROUTE_EXTENSION,
    HttpxCircuitOpenError,
    HttpxTooManyRedirectsError,
)
from clientwright.core.config import CircuitBreakerConfig  # noqa: E402
from clientwright.core.testing import OriginServer, RecordingMetrics  # noqa: E402

from ..conftest import base_config  # noqa: E402

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)


async def build(config: ClientConfig, deps: AdapterDeps) -> httpx.AsyncClient:
    client = clientwright.build("httpx", config, deps)
    assert type(client) is httpx.AsyncClient
    return client


# --- basics ---


async def test__echo__native_client_and_injected_headers(origin: OriginServer, metrics: RecordingMetrics) -> None:
    deps = AdapterDeps(metrics=metrics, header_providers=(lambda: {"X-Request-ID": "rid-1"},))
    config = base_config(origin, headers={"X-Static": "yes"})
    client = await build(config, deps)
    response = await client.get("/echo", headers={"X-Static": "caller-wins"})
    payload = response.json()
    assert payload["headers"]["x-request-id"] == "rid-1"
    assert payload["headers"]["x-static"] == "caller-wins"  # caller headers never overwritten
    await client.aclose()


async def test__route_extension__becomes_metric_label(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = await build(base_config(origin), deps)
    await client.get("/echo", extensions={ROUTE_EXTENSION: "/echo-route"})
    await client.aclose()
    assert metrics.calls[0]["route"] == "/echo-route"


async def test__inspect__returns_handle_with_report(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin), deps)
    handle = clientwright.inspect(client)
    assert handle is not None
    assert handle.adapter == "httpx"
    assert not handle.report.has_issues
    await handle.aclose()  # type: ignore[misc]


# --- retries ---


async def test__503_then_200__retried_to_success(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = await build(base_config(origin, retry=FAST_RETRY), deps)
    response = await client.get("/flaky/k1/2")
    assert response.status_code == 200
    assert origin.request_count("/flaky/k1/2") == 3
    assert len(metrics.attempts) == 3
    await client.aclose()


async def test__500__not_retried_and_returned(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin, retry=FAST_RETRY), deps)
    response = await client.get("/status/500")
    assert response.status_code == 500
    assert origin.request_count("/status/500") == 1
    await client.aclose()


async def test__disconnect__retried_as_disconnected(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin, retry=FAST_RETRY), deps)
    with pytest.raises(httpx.HTTPError):
        await client.get("/disconnect")
    assert origin.request_count("/disconnect") == 3  # all attempts consumed
    await client.aclose()


async def test__post__not_retried_without_idempotency(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = await build(base_config(origin, retry=FAST_RETRY), deps)
    response = await client.post("/flaky/p1/1", content=b"data")
    assert response.status_code == 503
    assert origin.request_count("/flaky/p1/1") == 1
    assert metrics.retry_skips[0]["reason"] == "method"
    await client.aclose()


async def test__post_with_idempotency_extension__retried_with_body(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin, retry=FAST_RETRY), deps)
    response = await client.post("/flaky/p2/1", content=b"data", extensions={IDEMPOTENT_EXTENSION: True})
    assert response.status_code == 200
    assert origin.request_count("/flaky/p2/1") == 2
    await client.aclose()


async def test__retry_after_header__delay_honored(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(origin, retry=RetryConfig(max_attempts=2, initial_backoff=0.01, jitter=0.0))
    client = await build(config, deps)
    started = asyncio.get_running_loop().time()
    response = await client.get("/retry-after/1")
    elapsed = asyncio.get_running_loop().time() - started
    assert response.status_code == 503  # stays 503, but the wait was respected
    assert elapsed >= 1.0
    await client.aclose()


# --- redirects ---


async def test__chain__followed_by_engine_with_hop_metric(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = await build(base_config(origin), deps)
    response = await client.get("/redirect/3")
    assert response.status_code == 200
    # In-place retarget keeps httpx's request identity: the final response
    # is attributed to the FINAL URL (cookies, response.url).
    assert str(response.url).endswith("/echo")
    assert len(metrics.redirect_hops) == 3
    assert len(metrics.calls) == 1  # one logical call despite hops
    await client.aclose()


async def test__loop__raises_dual_family_too_many_redirects(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin, max_redirects=3), deps)
    with pytest.raises(HttpxTooManyRedirectsError) as excinfo:
        await client.get("/redirect-loop")
    assert isinstance(excinfo.value, httpx.TooManyRedirects)
    await client.aclose()


async def test__post_303__demoted_to_get(origin: OriginServer, deps: AdapterDeps) -> None:
    client = await build(base_config(origin), deps)
    response = await client.post("/redirect/1", content=b"body")
    assert response.status_code == 200
    assert response.json()["method"] == "GET"
    await client.aclose()


# --- deadline ---


async def test__slow_body__total_deadline_cancels_and_translates(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(origin, timeout=TimeoutConfig(total=0.5, connect=2.0), retry=None)
    client = await build(config, deps)
    with pytest.raises(httpx.TimeoutException):
        await client.get("/slow/3")
    await client.aclose()


async def test__deadline_header__stamped_with_remaining_budget(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(origin, timeout=TimeoutConfig(total=30.0), deadline_header="X-Deadline-Ms")
    client = await build(config, deps)
    response = await client.get("/echo")
    stamped = int(response.json()["headers"]["x-deadline-ms"])
    assert 0 < stamped <= 30_000
    await client.aclose()


# --- circuit breaker ---


async def test__threshold__opens_and_rejects_without_touching_origin(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = base_config(
        origin,
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    client = await build(config, deps)
    for _ in range(2):
        response = await client.get("/status/503")
        assert response.status_code == 503
    before = origin.request_count("/status/503")
    with pytest.raises(HttpxCircuitOpenError) as excinfo:
        await client.get("/status/503")
    assert isinstance(excinfo.value, httpx.HTTPError)
    assert origin.request_count("/status/503") == before  # rejected locally
    assert metrics.calls[-1]["outcome"] == "circuit_open"
    assert metrics.inflight_balance == 0
    await client.aclose()


# --- observability invariants ---


async def test__failure_paths__never_leak_inflight(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = base_config(origin, timeout=TimeoutConfig(total=0.4, connect=0.2), retry=None)
    client = await build(config, deps)
    with pytest.raises(httpx.HTTPError):
        await client.get("/slow/2")
    with pytest.raises(httpx.HTTPError):
        await client.get("/disconnect")
    assert metrics.inflight_balance == 0
    statuses = [record["status"] for record in metrics.calls]
    assert statuses.count("none") == 2  # both failures observed with status=none
    await client.aclose()
