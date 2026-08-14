"""Real TLS failures and real NXDOMAIN, checked against the capability records.

This is where the capability model stops being paperwork: an adapter that
declares it emits ``dns_error`` has to produce it against an actual
unresolvable name, and one that declares the kind collapsed has to produce the
coarser label instead. Nothing else in the suite can verify that - our own
origin server cannot fail DNS or present an expired certificate.
"""

from __future__ import annotations

import pytest

from clientwright.core.config import TimeoutConfig, TlsConfig
from clientwright.core.model import FailureKind
from tests.helpers.drivers import (
    ASYNC_ADAPTERS,
    SYNC_ADAPTERS,
    adapter_params,
    battery_config,
    fresh_deps,
    get_driver,
)
from tests.live.conftest import UNRESOLVABLE, USER_AGENT, LiveOrigin, capabilities_of, expected_outcome

TLS_TIMEOUT = TimeoutConfig(total=20.0, connect=10.0)
# A reserved .invalid name is NXDOMAIN, but the resolver still walks its whole
# search list first - measured at ~11s here. A tighter connect budget would make
# the async stacks report the timeout that fired instead of the DNS failure
# underneath it, which says nothing about classification.
DNS_TIMEOUT = TimeoutConfig(total=90.0, connect=60.0)

EXPIRED = LiveOrigin("https://expired.badssl.com")
SELF_SIGNED = LiveOrigin("https://self-signed.badssl.com")
UNRESOLVABLE_ORIGIN = LiveOrigin(UNRESOLVABLE)


def tls_config(origin: LiveOrigin, driver: object, timeout: TimeoutConfig = TLS_TIMEOUT, **overrides: object) -> object:
    return battery_config(driver, origin, timeout=timeout, retry=None, headers={"User-Agent": USER_AGENT}, **overrides)


# --- an expired certificate is a TLS failure, whatever the SDK calls it -------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__expired_certificate__classified_as_the_record_promises(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(EXPIRED, driver), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, EXPIRED.url, "GET", "/")
    finally:
        await driver.close(client)
    expected = expected_outcome(capabilities_of(adapter_name), FailureKind.TLS_ERROR)
    assert metrics.calls[0]["outcome"] == expected
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__expired_certificate__classified_as_the_record_promises_sync(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(EXPIRED, driver), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, EXPIRED.url, "GET", "/")
    finally:
        driver.close(client)
    expected = expected_outcome(capabilities_of(adapter_name), FailureKind.TLS_ERROR)
    assert metrics.calls[0]["outcome"] == expected


# --- verify=False really reaches the SDK -------------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__self_signed_with_verification_off__actually_connects(adapter_name: str) -> None:
    # The TlsConfig plumbing is only provable against a certificate a real
    # verifier would reject.
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(SELF_SIGNED, driver, tls=TlsConfig(verify=False)), deps)
    try:
        response = await driver.request(client, SELF_SIGNED.url, "GET", "/")
    finally:
        await driver.close(client)
    assert response.status == 200
    assert metrics.calls[0]["outcome"] == "success"


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__self_signed_with_verification_off__actually_connects_sync(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(SELF_SIGNED, driver, tls=TlsConfig(verify=False)), deps)
    try:
        response = driver.request(client, SELF_SIGNED.url, "GET", "/")
    finally:
        driver.close(client)
    assert response.status == 200
    assert metrics.calls[0]["outcome"] == "success"


# --- a name that cannot resolve ----------------------------------------------


@pytest.mark.parametrize("adapter_name", adapter_params(ASYNC_ADAPTERS))
async def test__unresolvable_host__classified_as_the_record_promises(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(UNRESOLVABLE_ORIGIN, driver, timeout=DNS_TIMEOUT), deps)
    try:
        with pytest.raises(driver.family_errors()):
            await driver.request(client, UNRESOLVABLE, "GET", "/")
    finally:
        await driver.close(client)
    expected = expected_outcome(capabilities_of(adapter_name), FailureKind.DNS_ERROR)
    assert metrics.calls[0]["outcome"] == expected
    assert metrics.inflight_balance == 0


@pytest.mark.parametrize("adapter_name", adapter_params(SYNC_ADAPTERS))
def test__unresolvable_host__classified_as_the_record_promises_sync(adapter_name: str) -> None:
    driver = get_driver(adapter_name)
    metrics, deps = fresh_deps()
    client = driver.build(tls_config(UNRESOLVABLE_ORIGIN, driver, timeout=DNS_TIMEOUT), deps)
    try:
        with pytest.raises(driver.family_errors()):
            driver.request(client, UNRESOLVABLE, "GET", "/")
    finally:
        driver.close(client)
    expected = expected_outcome(capabilities_of(adapter_name), FailureKind.DNS_ERROR)
    assert metrics.calls[0]["outcome"] == expected
