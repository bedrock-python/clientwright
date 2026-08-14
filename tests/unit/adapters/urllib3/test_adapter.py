"""urllib3 engine urlopen and builder: pool-timeout forwarding, capability reporting, manager TLS kwargs.

The native class-level ``PoolManager.urlopen`` is stubbed at the SDK boundary
(no sockets); the instance-injected ``EngineUrlopen`` and the engine itself
run for real.
"""

from __future__ import annotations

from typing import Any

import pytest

urllib3 = pytest.importorskip("urllib3", reason="requires the [urllib3] extra")

import clientwright  # noqa: E402
from clientwright.core.capabilities import Capability  # noqa: E402
from clientwright.core.config import (  # noqa: E402
    ClientConfig,
    PoolConfig,
    ProxyConfig,
    TimeoutConfig,
    TlsConfig,
)


def _patch_native_urlopen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the SDK boundary; the last native urlopen records its arguments."""
    captured: dict[str, Any] = {}

    def fake_urlopen(self: urllib3.PoolManager, method: str, url: str, **kw: Any) -> urllib3.HTTPResponse:
        captured["method"] = method
        captured["url"] = url
        captured.update(kw)
        return urllib3.HTTPResponse(body=b"", status=200, headers={})

    monkeypatch.setattr(urllib3.PoolManager, "urlopen", fake_urlopen)
    return captured


# --- the engine-injected urlopen ---------------------------------------------


def test__blocking_pool__forwards_the_planned_pool_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_native_urlopen(monkeypatch)
    config = ClientConfig(
        service_name="s",
        pool=PoolConfig(max_connections_per_host=4),
        timeout=TimeoutConfig(pool_acquire=2.0),
    )
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        response = handle.client.request("GET", "http://example.com/x")
        assert response.status == 200
        assert captured["method"] == "GET"
        # The engine owns the loop: raw errors, no native retries or redirects.
        assert captured["retries"] is False
        assert captured["redirect"] is False
        assert isinstance(captured["timeout"], urllib3.util.Timeout)
        assert captured["pool_timeout"] == 2.0  # a blocking pool gets the planned pool_acquire
    finally:
        assert handle.close is not None
        handle.close()


def test__non_blocking_pool__never_passes_a_pool_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_native_urlopen(monkeypatch)
    config = ClientConfig(service_name="s")
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        handle.client.request("GET", "http://example.com/x")
        assert "pool_timeout" not in captured  # urlopen would reject it on a non-blocking pool
    finally:
        assert handle.close is not None
        handle.close()


# --- capability reporting ----------------------------------------------------


def test__blocking_pool__pool_knobs_reported_applied_natively() -> None:
    config = ClientConfig(
        service_name="s",
        pool=PoolConfig(max_connections_per_host=4),
        timeout=TimeoutConfig(pool_acquire=2.0),
    )
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        assert Capability.POOL_LIMIT_PER_HOST in handle.report.applied_natively
        assert Capability.TIMEOUT_POOL in handle.report.applied_natively
        assert Capability.TIMEOUT_POOL not in handle.report.dropped
    finally:
        assert handle.close is not None
        handle.close()


def test__inexpressible_knobs__reported_dropped() -> None:
    config = ClientConfig(
        service_name="s",
        timeout=TimeoutConfig(attempt=2.0, write=1.0),
        pool=PoolConfig(http2=True),
    )
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        dropped = handle.report.dropped
        assert Capability.TIMEOUT_ATTEMPT in dropped
        assert Capability.TIMEOUT_WRITE in dropped
        assert Capability.HTTP2 in dropped
    finally:
        assert handle.close is not None
        handle.close()


def test__pool_acquire_without_a_blocking_pool__dropped_with_hint() -> None:
    config = ClientConfig(service_name="s", timeout=TimeoutConfig(pool_acquire=1.0))
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        assert "blocking" in handle.report.dropped[Capability.TIMEOUT_POOL]
    finally:
        assert handle.close is not None
        handle.close()


def test__env_proxies__dropped_with_hint() -> None:
    config = ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True))
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        assert "environment" in handle.report.dropped[Capability.PROXY]
    finally:
        assert handle.close is not None
        handle.close()


# --- manager TLS kwargs ------------------------------------------------------


def _pool_kw(config: ClientConfig) -> dict[str, Any]:
    handle = clientwright.build_sync_handle("urllib3", config)
    try:
        return dict(handle.client.connection_pool_kw)
    finally:
        assert handle.close is not None
        handle.close()


def test__verify_false__maps_to_cert_reqs_none() -> None:
    kw = _pool_kw(ClientConfig(service_name="s", tls=TlsConfig(verify=False)))
    assert kw["cert_reqs"] == "CERT_NONE"


def test__ca_bundle__maps_to_ca_certs() -> None:
    kw = _pool_kw(ClientConfig(service_name="s", tls=TlsConfig(ca_bundle="bundle.pem")))
    assert kw["ca_certs"] == "bundle.pem"
    assert "cert_reqs" not in kw


def test__cert_string__maps_to_cert_file_alone() -> None:
    kw = _pool_kw(ClientConfig(service_name="s", tls=TlsConfig(cert="client.pem")))
    assert kw["cert_file"] == "client.pem"
    assert "key_file" not in kw


def test__cert_tuple__maps_to_cert_and_key_files() -> None:
    kw = _pool_kw(ClientConfig(service_name="s", tls=TlsConfig(cert=("client.crt", "client.key"))))
    assert kw["cert_file"] == "client.crt"
    assert kw["key_file"] == "client.key"
