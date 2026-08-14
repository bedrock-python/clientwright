"""aiohttp builder units: TLS argument, proxy router selection, capability reporting, connector shape."""

from __future__ import annotations

import ssl
from types import SimpleNamespace

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="requires the [aiohttp] extra")

from yarl import URL  # noqa: E402

import clientwright  # noqa: E402
from clientwright.adapters.aiohttp.adapter import _proxy_router, _ssl_argument  # noqa: E402
from clientwright.core.capabilities import Capability  # noqa: E402
from clientwright.core.config import (  # noqa: E402
    ClientConfig,
    PoolConfig,
    ProxyConfig,
    TimeoutConfig,
    TlsConfig,
)

# --- TLS argument ------------------------------------------------------------


def test__ssl_argument__plain_verify_passes_through_as_bool() -> None:
    assert _ssl_argument(ClientConfig(service_name="s")) is True
    assert _ssl_argument(ClientConfig(service_name="s", tls=TlsConfig(verify=False))) is False


def test__ssl_argument__cert_with_verify_false_bakes_insecure_context(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(verify=False, cert=tls_material.combined))
    context = _ssl_argument(config)
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode is ssl.CERT_NONE


def test__ssl_argument__ca_bundle_with_cert_tuple_bakes_verifying_context(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(
        service_name="s",
        tls=TlsConfig(ca_bundle=tls_material.ca, cert=(tls_material.cert, tls_material.key)),
    )
    context = _ssl_argument(config)
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED


def test__ssl_argument__ca_bundle_alone_builds_a_verifying_context(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(ca_bundle=tls_material.ca))
    context = _ssl_argument(config)
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode is ssl.CERT_REQUIRED


# --- proxy router selection --------------------------------------------------


class _Req:
    def __init__(self, url: str) -> None:
        self.url = URL(url)
        self.proxy: object = URL("http://stale:1")


def test__proxy_router_selection__none_without_proxy_config() -> None:
    assert _proxy_router(ClientConfig(service_name="s")) is None


def test__proxy_router_selection__explicit_url_applies_everywhere() -> None:
    router = _proxy_router(ClientConfig(service_name="s", proxy=ProxyConfig(url="http://proxy.local:3128")))
    assert router is not None
    request = _Req("http://a.example/x")
    router.apply(request)  # type: ignore[arg-type]
    assert str(request.proxy) == "http://proxy.local:3128"


def test__proxy_router_selection__env_proxies_by_scheme_with_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://proxy.local:3128")
    monkeypatch.setenv("https_proxy", "http://secure-proxy.local:3128")
    monkeypatch.setenv("no_proxy", "internal.example")
    router = _proxy_router(ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True)))
    assert router is not None
    proxied = _Req("https://a.example/x")
    router.apply(proxied)  # type: ignore[arg-type]
    assert str(proxied.proxy) == "http://secure-proxy.local:3128"
    direct = _Req("http://svc.internal.example/x")
    router.apply(direct)  # type: ignore[arg-type]
    assert direct.proxy is None


def test__proxy_router_selection__empty_environment_means_no_router(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patched at the function level: on Windows getproxies() would otherwise
    # fall back to registry proxies and the test would depend on the machine.
    monkeypatch.setattr("clientwright.adapters.aiohttp.adapter.getproxies", dict)
    router = _proxy_router(ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True)))
    assert router is None


# --- capability reporting and connector shape --------------------------------


async def test__per_host_limit__applied_natively_on_the_connector() -> None:
    config = ClientConfig(service_name="s", pool=PoolConfig(max_connections_per_host=5))
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert Capability.POOL_LIMIT_PER_HOST in handle.report.applied_natively
        assert handle.client.connector.limit_per_host == 5
    finally:
        assert handle.aclose is not None
        await handle.aclose()


async def test__proxy__reported_emulated() -> None:
    config = ClientConfig(service_name="s", proxy=ProxyConfig(url="http://proxy.local:3128"))
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert Capability.PROXY in handle.report.emulated
    finally:
        assert handle.aclose is not None
        await handle.aclose()


async def test__pool_acquire_timeout__reported_dropped_with_reason() -> None:
    config = ClientConfig(service_name="s", timeout=TimeoutConfig(pool_acquire=1.0))
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert Capability.TIMEOUT_POOL in handle.report.dropped
        assert "pool" in handle.report.dropped[Capability.TIMEOUT_POOL]
    finally:
        assert handle.aclose is not None
        await handle.aclose()


async def test__http2__reported_dropped() -> None:
    config = ClientConfig(service_name="s", pool=PoolConfig(http2=True))
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert Capability.HTTP2 in handle.report.dropped
    finally:
        assert handle.aclose is not None
        await handle.aclose()


async def test__disabled_keepalive__forces_connection_close() -> None:
    config = ClientConfig(service_name="s", pool=PoolConfig(keepalive_expiry=None))
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert handle.client.connector.force_close is True
    finally:
        assert handle.aclose is not None
        await handle.aclose()
