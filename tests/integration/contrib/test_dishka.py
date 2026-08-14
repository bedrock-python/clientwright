"""A dishka container serving a clientwright client end-to-end against a real origin."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("dishka", reason="requires the [dishka] extra")
httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

from dishka import make_async_container  # noqa: E402

from clientwright import AdapterDeps, ClientConfig, RetryConfig  # noqa: E402
from clientwright.contrib.dishka import ClientwrightProvider  # noqa: E402
from clientwright.core.config import CircuitBreakerConfig  # noqa: E402
from clientwright.core.plan import ClientHandle, ClientRuntime  # noqa: E402
from clientwright.core.testing import OriginServer, RecordingMetrics  # noqa: E402


async def test__container_client__serves_calls_with_injected_metrics(origin: OriginServer) -> None:
    config = ClientConfig(
        service_name="di-integration",
        base_url=origin.url,
        retry=RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0),
    )
    metrics = RecordingMetrics()
    container = make_async_container(ClientwrightProvider("httpx", config, AdapterDeps(metrics=metrics)))
    handle = await container.get(ClientHandle[Any])
    client = handle.client
    assert type(client) is httpx.AsyncClient

    response = await client.get("/flaky/di-flow/1")
    assert response.status_code == 200
    assert len(metrics.attempts) == 2  # the engine under the DI-provided client retried
    assert [record["outcome"] for record in metrics.calls] == ["success"]

    await container.close()
    assert client.is_closed
    assert metrics.inflight_balance == 0


async def test__two_container_generations__breaker_state_lives_in_the_runtime(origin: OriginServer) -> None:
    # The runtime carries circuit state; handing the SAME runtime to a new
    # container generation keeps the breaker armed across client rebuilds.
    config = ClientConfig(
        service_name="di-runtime",
        base_url=origin.url,
        retry=None,
        circuit_breaker=CircuitBreakerConfig(fail_threshold=1, recovery_timeout=60.0),
    )
    runtime = ClientRuntime.for_config(config)
    deps = AdapterDeps(runtime=runtime)

    first = make_async_container(ClientwrightProvider("httpx", config, deps))
    handle = await first.get(ClientHandle[Any])
    trip = await handle.client.get("/status/500")
    assert trip.status_code == 500  # one 5xx signal arms the breaker
    await first.close()

    second = make_async_container(ClientwrightProvider("httpx", config, deps))
    rebuilt = await second.get(ClientHandle[Any])
    assert rebuilt.runtime is runtime
    with pytest.raises(httpx.HTTPError):
        await rebuilt.client.get("/status/500")  # rejected locally: state survived the rebuild
    assert origin.request_count("/status/500") == 1
    await second.close()
