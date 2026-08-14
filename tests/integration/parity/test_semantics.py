"""Cross-adapter semantics parity: the product promise, asserted.

Every scenario runs verbatim against every installed adapter and expects the
SAME behavior: same attempt counts, same metric outcomes, same local decisions.
Adapter-specific seams are covered by their own conformance suites; this file
only asserts what must NOT differ.
"""

from __future__ import annotations

import itertools
import time

import pytest

from clientwright.core.config import CircuitBreakerConfig, RetryConfig, TimeoutConfig
from clientwright.core.testing import OriginServer
from tests.helpers.drivers import (
    ASYNC_ADAPTERS,
    SYNC_ADAPTERS,
    adapter_params,
    battery_config,
    fresh_deps,
    get_driver,
)

FAST_RETRY = RetryConfig(max_attempts=3, initial_backoff=0.01, jitter=0.0)

_unique = itertools.count()


def flaky_path(tag: str, fails: int) -> str:
    return f"/flaky/parity-{tag}-{next(_unique)}/{fails}"


# --- one flaky 503 recovers with exactly one extra attempt -------------------


async def _flaky_recovery(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    path = flaky_path(adapter_name, 1)
    try:
        response = await driver.request(client, origin.url, "GET", path)
    finally:
        await driver.close(client)
    assert response.status == 200
    assert origin.request_count(path) == 2
    assert len(metrics.attempts) == 2
    assert [record["outcome"] for record in metrics.calls] == ["success"]


def _flaky_recovery_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    path = flaky_path(adapter_name, 1)
    try:
        response = driver.request(client, origin.url, "GET", path)
    finally:
        driver.close(client)
    assert response.status == 200
    assert origin.request_count(path) == 2
    assert len(metrics.attempts) == 2
    assert [record["outcome"] for record in metrics.calls] == ["success"]


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__flaky_503__one_extra_attempt_everywhere(adapter_name: str, origin: OriginServer) -> None:
    await _flaky_recovery(adapter_name, origin)


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__flaky_503__one_extra_attempt_everywhere_sync(adapter_name: str, origin: OriginServer) -> None:
    _flaky_recovery_sync(adapter_name, origin)


# --- 500 is final: returned, never retried -----------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__500__returned_without_retry(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    try:
        response = await driver.request(client, origin.url, "GET", "/status/500")
    finally:
        await driver.close(client)
    assert response.status == 500
    assert len(metrics.attempts) == 1
    assert metrics.calls[0]["outcome"] == "status"


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__500__returned_without_retry_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    try:
        response = driver.request(client, origin.url, "GET", "/status/500")
    finally:
        driver.close(client)
    assert response.status == 500
    assert len(metrics.attempts) == 1
    assert metrics.calls[0]["outcome"] == "status"


# --- POST: no retry without the idempotency flag, retry with it --------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__post_idempotency_gate__same_on_every_adapter(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    try:
        plain = await driver.request(client, origin.url, "POST", flaky_path(adapter_name, 1), body=b"data")
        assert plain.status == 503  # a non-idempotent POST is never repeated
        assert len(metrics.attempts) == 1
        marked = await driver.request(
            client, origin.url, "POST", flaky_path(adapter_name, 1), body=b"data", idempotent=True
        )
        assert marked.status == 200  # the per-call flag unlocks the retry
        assert len(metrics.attempts) == 3
    finally:
        await driver.close(client)


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__post_idempotency_gate__same_on_every_adapter_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=FAST_RETRY), deps)
    try:
        plain = driver.request(client, origin.url, "POST", flaky_path(adapter_name, 1), body=b"data")
        assert plain.status == 503
        assert len(metrics.attempts) == 1
        marked = driver.request(client, origin.url, "POST", flaky_path(adapter_name, 1), body=b"data", idempotent=True)
        assert marked.status == 200
        assert len(metrics.attempts) == 3
    finally:
        driver.close(client)


# --- circuit breaker: one 5xx signal, local rejection, origin untouched ------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__circuit__opens_and_rejects_locally(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(
        driver, origin, retry=None, circuit_breaker=CircuitBreakerConfig(fail_threshold=1, recovery_timeout=60.0)
    )
    client = driver.build(config, deps)
    path = f"/status/500?breaker={adapter_name}-{next(_unique)}"
    try:
        first = await driver.request(client, origin.url, "GET", path)
        assert first.status == 500
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", path)
    finally:
        await driver.close(client)
    assert origin.request_count(path) == 1  # the rejection never left the process
    assert [record["outcome"] for record in metrics.calls] == ["status", "circuit_open"]


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__circuit__opens_and_rejects_locally_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(
        driver, origin, retry=None, circuit_breaker=CircuitBreakerConfig(fail_threshold=1, recovery_timeout=60.0)
    )
    client = driver.build(config, deps)
    path = f"/status/500?breaker={adapter_name}-{next(_unique)}"
    try:
        first = driver.request(client, origin.url, "GET", path)
        assert first.status == 500
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", path)
    finally:
        driver.close(client)
    assert origin.request_count(path) == 1
    assert [record["outcome"] for record in metrics.calls] == ["status", "circuit_open"]


# --- total deadline caps a slow origin ---------------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__total_deadline__caps_slow_origin(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, origin, retry=None, timeout=TimeoutConfig(total=0.4, connect=1.0))
    client = driver.build(config, deps)
    started = time.monotonic()
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", "/slow/3")
    finally:
        await driver.close(client)
    assert time.monotonic() - started < 2.5  # nowhere near the 3s the origin wanted
    assert metrics.calls[0]["outcome"] == "total_timeout"


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__total_deadline__caps_slow_origin_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    config = battery_config(driver, origin, retry=None, timeout=TimeoutConfig(total=0.4, connect=1.0))
    client = driver.build(config, deps)
    started = time.monotonic()
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", "/slow/3")
    finally:
        driver.close(client)
    assert time.monotonic() - started < 2.5
    # The DECLARED divergence (DEADLINE_HARD: ABSENT): a sync runtime cannot
    # cancel a blocked read, so the deadline arrives as the clamped read phase
    # and is honestly labelled read_timeout rather than total_timeout.
    assert metrics.calls[0]["outcome"] == "read_timeout"


# --- owned redirects: hops inside ONE logical call ---------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__redirect_chain__one_logical_call_with_hops(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=None), deps)
    try:
        response = await driver.request(client, origin.url, "GET", "/redirect/2")
    finally:
        await driver.close(client)
    assert response.status == 200
    assert len(metrics.calls) == 1  # hops never inflate the call count
    assert len(metrics.redirect_hops) == 2


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__redirect_chain__one_logical_call_with_hops_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=None), deps)
    try:
        response = driver.request(client, origin.url, "GET", "/redirect/2")
    finally:
        driver.close(client)
    assert response.status == 200
    assert len(metrics.calls) == 1
    assert len(metrics.redirect_hops) == 2


# --- redirect loops are bounded ----------------------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__redirect_loop__bounded_by_max_redirects(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=None, max_redirects=2), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, origin.url, "GET", "/redirect-loop")
    finally:
        await driver.close(client)
    assert len(metrics.calls) == 1
    assert len(metrics.redirect_hops) == 2


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__redirect_loop__bounded_by_max_redirects_sync(adapter_name: str, origin: OriginServer) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(battery_config(driver, origin, retry=None, max_redirects=2), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, origin.url, "GET", "/redirect-loop")
    finally:
        driver.close(client)
    assert len(metrics.calls) == 1
    assert len(metrics.redirect_hops) == 2
