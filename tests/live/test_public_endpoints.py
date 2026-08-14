"""The engine against real servers: TLS, DNS, redirects and deadlines in the wild.

Every scenario runs on every installed adapter. The in-process suite already
proves the semantics; what these add is that nothing in the stack depends on our
own test server being unusually well-behaved.
"""

from __future__ import annotations

import time

import pytest

from clientwright.core.config import RetryConfig, TimeoutConfig
from tests.helpers.drivers import (
    ASYNC_ADAPTERS,
    SYNC_ADAPTERS,
    adapter_params,
    battery_config,
    fresh_deps,
    get_driver,
)
from tests.live.conftest import USER_AGENT, LiveOrigin

EXAMPLE = LiveOrigin("https://example.com")
LIVE_TIMEOUT = TimeoutConfig(total=30.0, connect=10.0)
RETRY_TWICE = RetryConfig(max_attempts=3, initial_backoff=0.2, jitter=0.0)

# --- a plain GET over real TLS ------------------------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__example_com__succeeds_over_real_tls(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, EXAMPLE, timeout=LIVE_TIMEOUT, headers={"User-Agent": USER_AGENT})
    client = driver.build(config, deps)
    try:
        response = await driver.request(client, EXAMPLE.url, "GET", "/")
    finally:
        await driver.close(client)
    assert response.status == 200
    assert b"Example Domain" in response.body
    assert metrics.calls[0]["outcome"] == "success"
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__example_com__succeeds_over_real_tls_sync(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, EXAMPLE, timeout=LIVE_TIMEOUT, headers={"User-Agent": USER_AGENT})
    client = driver.build(config, deps)
    try:
        response = driver.request(client, EXAMPLE.url, "GET", "/")
    finally:
        driver.close(client)
    assert response.status == 200
    assert b"Example Domain" in response.body
    assert metrics.calls[0]["outcome"] == "success"


# --- configured headers survive the whole real round trip ---------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__configured_headers__arrive_at_a_real_server(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    _, deps = fresh_deps()
    config = battery_config(
        driver,
        httpbin,
        timeout=LIVE_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "X-Clientwright-Live": "yes"},
    )
    client = driver.build(config, deps)
    try:
        response = await driver.request(client, httpbin.url, "GET", "/get")
    finally:
        await driver.close(client)
    assert response.status == 200
    assert b"x-clientwright-live" in response.body.lower()  # the echo, however the server spells it


# --- retries against a server that really answers 503 -------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__persistent_503__retried_the_configured_number_of_times(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(
        driver, httpbin, timeout=LIVE_TIMEOUT, retry=RETRY_TWICE, headers={"User-Agent": USER_AGENT}
    )
    client = driver.build(config, deps)
    try:
        response = await driver.request(client, httpbin.url, "GET", "/status/503")
    finally:
        await driver.close(client)
    assert response.status == 503
    assert len(metrics.attempts) == 3  # the real network did not change the accounting
    assert metrics.calls[0]["outcome"] == "status"


# --- owned redirects across a real redirect chain -----------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__real_redirect_chain__followed_as_one_logical_call(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, httpbin, timeout=LIVE_TIMEOUT, retry=None, headers={"User-Agent": USER_AGENT})
    client = driver.build(config, deps)
    try:
        response = await driver.request(client, httpbin.url, "GET", "/redirect/2")
    finally:
        await driver.close(client)
    assert response.status == 200
    assert len(metrics.calls) == 1
    assert len(metrics.redirect_hops) == 2


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__real_redirect_chain__followed_as_one_logical_call_sync(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, httpbin, timeout=LIVE_TIMEOUT, retry=None, headers={"User-Agent": USER_AGENT})
    client = driver.build(config, deps)
    try:
        response = driver.request(client, httpbin.url, "GET", "/redirect/2")
    finally:
        driver.close(client)
    assert response.status == 200
    assert len(metrics.calls) == 1
    assert len(metrics.redirect_hops) == 2


# --- the total deadline against a genuinely slow endpoint ---------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__slow_endpoint__cut_off_by_the_total_deadline(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(
        driver,
        httpbin,
        timeout=TimeoutConfig(total=3.0, connect=10.0),
        retry=None,
        headers={"User-Agent": USER_AGENT},
    )
    client = driver.build(config, deps)
    started = time.monotonic()
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, httpbin.url, "GET", "/delay/10")
    finally:
        await driver.close(client)
    elapsed = time.monotonic() - started
    assert elapsed < 9.0  # nowhere near the ten seconds the endpoint wanted
    assert metrics.calls[0]["outcome"] in {"total_timeout", "read_timeout"}


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__slow_endpoint__cut_off_by_the_total_deadline_sync(adapter_name: str, httpbin: LiveOrigin) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(
        driver,
        httpbin,
        timeout=TimeoutConfig(total=3.0, connect=10.0),
        retry=None,
        headers={"User-Agent": USER_AGENT},
    )
    client = driver.build(config, deps)
    started = time.monotonic()
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, httpbin.url, "GET", "/delay/10")
    finally:
        driver.close(client)
    assert time.monotonic() - started < 9.0
    assert metrics.calls[0]["outcome"] in {"total_timeout", "read_timeout"}
