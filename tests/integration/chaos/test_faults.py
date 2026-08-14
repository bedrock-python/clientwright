"""Chaos battery: mid-stream and protocol-level faults against every adapter.

The universal contract under chaos is narrow and absolute: the caller gets an
error of the SDK's own family (never a clientwright internal), telemetry closes
exactly once, and the in-flight gauge returns to zero. Outcome labels are only
asserted for faults that break BEFORE the body: adapters with a headers
boundary (aiohttp) honestly close the call metric at headers, so a body-phase
fault lands outside their seam.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clientwright.core.config import TimeoutConfig
from clientwright.core.testing import OriginServer
from tests.helpers.drivers import (
    ASYNC_ADAPTERS,
    SYNC_ADAPTERS,
    adapter_params,
    battery_config,
    fresh_deps,
    get_driver,
)

# Faults that kill the exchange before a valid response head: every adapter's
# engine sees these, so the outcome label is asserted universally.
PRE_BODY_FAULTS = ("garbage", "reset", "disconnect")
# Faults inside the body phase: the raise is universal, the outcome label is not.
BODY_FAULTS = ("drop-body",)

CHAOS_TIMEOUTS = TimeoutConfig(total=5.0, connect=2.0, read=1.0)


def chaos_config(driver: object, origin: OriginServer) -> object:
    return battery_config(driver, origin, retry=None, circuit_breaker=None, timeout=CHAOS_TIMEOUTS)


@pytest.fixture
def dead_origin_url() -> Iterator[str]:
    """A localhost URL whose port was just closed: connections are refused."""
    server = OriginServer()
    url = server.url
    server.server_close()
    yield url


# --- pre-body faults: error + closed telemetry + honest outcome --------------


@pytest.mark.parametrize("fault", PRE_BODY_FAULTS)
@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__pre_body_fault__native_error_and_closed_telemetry(
    adapter_name: str, fault: str, origin: OriginServer
) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", f"/{fault}")
    finally:
        await driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.calls[0]["outcome"] != "success"
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("fault", PRE_BODY_FAULTS)
@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__pre_body_fault__native_error_and_closed_telemetry_sync(
    adapter_name: str, fault: str, origin: OriginServer
) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", f"/{fault}")
    finally:
        driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.calls[0]["outcome"] != "success"
    assert metrics.inflight_balance == 0


# --- body-phase faults: error + balanced gauge (outcome depends on boundary) --


@pytest.mark.parametrize("fault", BODY_FAULTS)
@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__body_fault__native_error_and_balanced_gauge(
    adapter_name: str, fault: str, origin: OriginServer
) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", f"/{fault}")
    finally:
        await driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("fault", BODY_FAULTS)
@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__body_fault__native_error_and_balanced_gauge_sync(adapter_name: str, fault: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", f"/{fault}")
    finally:
        driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.inflight_balance == 0


# --- a stalled body hits the read timeout, not the total ----------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__mid_body_stall__read_timeout_family_error(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", "/hang-body/3")
    finally:
        await driver.close(client)
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__mid_body_stall__read_timeout_family_error_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(chaos_config(driver, origin), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", "/hang-body/3")
    finally:
        driver.close(client)
    assert metrics.inflight_balance == 0


# --- connection refused: the failure never reaches a socket exchange ----------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__connection_refused__classified_and_closed(
    adapter_name: str, origin: OriginServer, dead_origin_url: str
) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    dead = _DeadOrigin(dead_origin_url)
    client = driver.build(chaos_config(driver, dead), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, dead_origin_url, "GET", "/echo")
    finally:
        await driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.calls[0]["outcome"] != "success"
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__connection_refused__classified_and_closed_sync(
    adapter_name: str, origin: OriginServer, dead_origin_url: str
) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    dead = _DeadOrigin(dead_origin_url)
    client = driver.build(chaos_config(driver, dead), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, dead_origin_url, "GET", "/echo")
    finally:
        driver.close(client)
    assert len(metrics.calls) == 1
    assert metrics.calls[0]["outcome"] != "success"
    assert metrics.inflight_balance == 0


class _DeadOrigin:
    """Duck-typed stand-in for OriginServer where only .url matters."""

    def __init__(self, url: str) -> None:
        self.url = url


# --- retries recover from dropped connections, not just from 503s -------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__flaky_disconnect__retried_to_success(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, circuit_breaker=None), deps)
    path = f"/flaky-disconnect/chaos-{adapter_name}/1"
    try:
        response = await driver.request(client, origin.url, "GET", path)
    finally:
        await driver.close(client)
    assert response.status == 200
    assert response.body == b"recovered"
    assert [record["outcome"] for record in metrics.calls] == ["success"]


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__flaky_disconnect__retried_to_success_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, circuit_breaker=None), deps)
    path = f"/flaky-disconnect/chaos-{adapter_name}-sync/1"
    try:
        response = driver.request(client, origin.url, "GET", path)
    finally:
        driver.close(client)
    assert response.status == 200
    assert response.body == b"recovered"
    assert [record["outcome"] for record in metrics.calls] == ["success"]
