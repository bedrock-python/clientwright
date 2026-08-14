"""Behavioral conformance of the httpx2 adapter against a real origin.

The implementation is the shared family builder, so this suite is a compact
smoke of both modes; the exhaustive behavior suite runs against httpx.
"""

from __future__ import annotations

import pytest

httpx2 = pytest.importorskip("httpx2", reason="requires the [httpx2] extra")

import clientwright  # noqa: E402
from clientwright import AdapterDeps, RetryConfig, TimeoutConfig  # noqa: E402
from clientwright.adapters.httpx2 import (  # noqa: E402
    ROUTE_EXTENSION,
    HttpxCircuitOpenError,
    HttpxTooManyRedirectsError,
)
from clientwright.core.config import CircuitBreakerConfig  # noqa: E402
from clientwright.core.testing import OriginServer, RecordingMetrics  # noqa: E402

from ..conftest import base_config  # noqa: E402

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)

# --- async smoke ---


async def test__echo__exact_native_type_and_route_label(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = clientwright.build("httpx2", base_config(origin), deps)
    assert type(client) is httpx2.AsyncClient
    response = await client.get("/echo", extensions={ROUTE_EXTENSION: "/echo-route"})
    assert response.status_code == 200
    assert metrics.calls[0]["route"] == "/echo-route"
    assert metrics.calls[0]["adapter"] == "httpx2"
    await client.aclose()


async def test__503_then_200__retried_to_success(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = clientwright.build("httpx2", base_config(origin, retry=FAST_RETRY), deps)
    response = await client.get("/flaky/h2a/2")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert origin.request_count("/flaky/h2a/2") == 3
    assert len(metrics.attempts) == 3
    await client.aclose()  # type: ignore[attr-defined]


async def test__redirect_chain__owned_with_final_attribution(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = clientwright.build("httpx2", base_config(origin), deps)
    response = await client.get("/redirect/3")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert str(response.url).endswith("/echo")
    assert len(metrics.redirect_hops) == 3
    assert len(metrics.calls) == 1
    await client.aclose()  # type: ignore[attr-defined]


async def test__redirect_loop__raises_dual_family_error(origin: OriginServer, deps: AdapterDeps) -> None:
    client = clientwright.build("httpx2", base_config(origin, max_redirects=3), deps)
    with pytest.raises(HttpxTooManyRedirectsError) as excinfo:
        await client.get("/redirect-loop")  # type: ignore[attr-defined]
    assert isinstance(excinfo.value, httpx2.TooManyRedirects)
    await client.aclose()  # type: ignore[attr-defined]


async def test__slow_response__deadline_translates_into_httpx2_family(origin: OriginServer, deps: AdapterDeps) -> None:
    config = base_config(origin, timeout=TimeoutConfig(total=0.5, connect=2.0), retry=None)
    client = clientwright.build("httpx2", config, deps)
    with pytest.raises(httpx2.TimeoutException):
        await client.get("/slow/3")  # type: ignore[attr-defined]
    await client.aclose()  # type: ignore[attr-defined]


async def test__circuit_breaker__opens_and_rejects_locally(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    config = base_config(
        origin,
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=2, recovery_timeout=60.0),
    )
    client = clientwright.build("httpx2", config, deps)
    for _ in range(2):
        response = await client.get("/status/503")  # type: ignore[attr-defined]
        assert response.status_code == 503
    before = origin.request_count("/status/503")
    with pytest.raises(HttpxCircuitOpenError) as excinfo:
        await client.get("/status/503")  # type: ignore[attr-defined]
    assert isinstance(excinfo.value, httpx2.HTTPError)
    assert origin.request_count("/status/503") == before
    assert metrics.inflight_balance == 0
    await client.aclose()  # type: ignore[attr-defined]


# --- sync smoke ---


def test__echo_and_retry__work_via_native_sync_client(
    origin: OriginServer, metrics: RecordingMetrics, deps: AdapterDeps
) -> None:
    client = clientwright.build_sync("httpx2", base_config(origin, retry=FAST_RETRY), deps)
    assert type(client) is httpx2.Client
    response = client.get("/flaky/h2s/2")
    assert response.status_code == 200
    assert origin.request_count("/flaky/h2s/2") == 3
    assert len(metrics.attempts) == 3
    client.close()
