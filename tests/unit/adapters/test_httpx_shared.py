"""Shared httpx-family machinery, exercised through the httpx bindings.

``adapters/_httpx_shared`` is SDK-agnostic by construction; these tests bind
it exactly the way the adapters do (mixin + httpx base class) and pin the
family contracts: TLS argument baking, NO_PROXY parsing, timed body streams
reporting exactly once, normalizer edge paths, per-scheme proxy routing and
the env-proxy build wiring.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

import clientwright  # noqa: E402
from clientwright.adapters._httpx_shared import (  # noqa: E402
    AsyncTimedStreamMixin,
    SyncTimedStreamMixin,
    host_bypasses_proxy,
    no_proxy_hosts,
    ssl_arguments,
)
from clientwright.adapters.httpx.classify import classify_error  # noqa: E402
from clientwright.adapters.httpx.normalize import AsyncHttpxNormalizer  # noqa: E402
from clientwright.adapters.httpx.normalize_sync import SyncHttpxNormalizer  # noqa: E402
from clientwright.adapters.httpx.transport import (  # noqa: E402
    AsyncEngineTransport,
    AsyncProxyRouterTransport,
    SyncEngineTransport,
    SyncProxyRouterTransport,
)
from clientwright.core.capabilities import Capability  # noqa: E402
from clientwright.core.config import ClientConfig, PoolConfig, ProxyConfig, TlsConfig  # noqa: E402
from clientwright.core.model import FailureKind, Outcome  # noqa: E402

DEFAULT_TIMEOUT = {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}


class _FakeClock:
    def __init__(self, now: float = 10.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# --- classify_family_error: branches shared by the whole family --------------


def test__cancelled_error__maps_to_cancelled() -> None:
    assert classify_error(asyncio.CancelledError()) is FailureKind.CANCELLED


def test__local_protocol_error__maps_to_protocol_error() -> None:
    assert classify_error(httpx.LocalProtocolError("malformed request")) is FailureKind.PROTOCOL_ERROR


def test__proxy_error__maps_to_connect_error() -> None:
    assert classify_error(httpx.ProxyError("proxy refused")) is FailureKind.CONNECT_ERROR


# --- ssl_arguments -----------------------------------------------------------


def test__ssl_arguments__default_config_passes_verify_flag() -> None:
    assert ssl_arguments(ClientConfig(service_name="s")) == {"verify": True}


def test__ssl_arguments__cert_with_plain_verify_passed_as_kwarg(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(cert=tls_material.combined))
    assert ssl_arguments(config) == {"verify": True, "cert": tls_material.combined}


def test__ssl_arguments__cert_with_verify_false_bakes_insecure_context(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(verify=False, cert=tls_material.combined))
    kwargs = ssl_arguments(config)
    # httpx's create_ssl_context(verify=False) would silently DROP the cert
    # kwarg, so the context must be baked here with the chain already loaded.
    assert set(kwargs) == {"verify"}
    context = kwargs["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode is ssl.CERT_NONE


def test__ssl_arguments__cert_tuple_with_ca_bundle_bakes_verifying_context(tls_material: SimpleNamespace) -> None:
    config = ClientConfig(
        service_name="s",
        tls=TlsConfig(ca_bundle=tls_material.ca, cert=(tls_material.cert, tls_material.key)),
    )
    kwargs = ssl_arguments(config)
    assert set(kwargs) == {"verify"}
    context = kwargs["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED


def test__ssl_arguments__bogus_cert_path_fails_at_build_time() -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(verify=False, cert="no-such-cert.pem"))
    with pytest.raises(OSError):  # FileNotFoundError or SSLError depending on the platform
        ssl_arguments(config)


# --- environment proxy parsing -----------------------------------------------


def test__no_proxy_hosts__parses_csv_and_drops_the_star_wildcard() -> None:
    proxies = {"no": " internal.example ,, .svc.local , * "}
    assert no_proxy_hosts(proxies) == ["internal.example", ".svc.local"]


def test__no_proxy_hosts__empty_when_no_entry_present() -> None:
    assert no_proxy_hosts({"http": "http://proxy.local:3128"}) == []


def test__host_bypasses_proxy__matches_exact_host_and_subdomains() -> None:
    assert host_bypasses_proxy("internal.example", ("internal.example",)) is True
    assert host_bypasses_proxy("svc.internal.example", (".internal.example",)) is True
    assert host_bypasses_proxy("notinternal.example", ("internal.example",)) is False


# --- timed body streams ------------------------------------------------------


class _TimedAsyncStream(AsyncTimedStreamMixin, httpx.AsyncByteStream):
    """Bound in the test exactly the way the adapters bind it."""


class _TimedSyncStream(SyncTimedStreamMixin, httpx.SyncByteStream):
    """Bound in the test exactly the way the adapters bind it."""


class _FailingAsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"chunk"
        raise ValueError("mid-body failure")


class _FailingSyncStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"chunk"
        raise ValueError("mid-body failure")


class _OnDoneRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Outcome, float]] = []

    def __call__(self, outcome: Outcome, duration: float) -> None:
        self.calls.append((outcome, duration))


async def test__async_timed_stream__reports_read_failure_once_and_reraises() -> None:
    recorder = _OnDoneRecorder()
    clock = _FakeClock(now=10.0)
    stream = _TimedAsyncStream(_FailingAsyncStream(), clock, recorder)
    clock.now = 10.25
    received: list[bytes] = []
    with pytest.raises(ValueError, match="mid-body failure"):
        async for chunk in stream:
            received.append(chunk)
    assert received == [b"chunk"]
    outcome, duration = recorder.calls[0]
    assert outcome.kind is FailureKind.BODY_ERROR
    assert isinstance(outcome.exception, ValueError)
    assert duration == 0.25
    await stream.aclose()  # a later close must NOT report a second outcome
    assert len(recorder.calls) == 1


def test__sync_timed_stream__reports_read_failure_once_and_reraises() -> None:
    recorder = _OnDoneRecorder()
    clock = _FakeClock(now=10.0)
    stream = _TimedSyncStream(_FailingSyncStream(), clock, recorder)
    clock.now = 10.25
    received: list[bytes] = []
    with pytest.raises(ValueError, match="mid-body failure"):
        received.extend(stream)
    assert received == [b"chunk"]
    outcome, duration = recorder.calls[0]
    assert outcome.kind is FailureKind.BODY_ERROR
    assert isinstance(outcome.exception, ValueError)
    assert duration == 0.25
    stream.close()  # a later close must NOT report a second outcome
    assert len(recorder.calls) == 1


# --- normalizer edge paths ---------------------------------------------------


class _UnreadableAsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise RuntimeError("stream cannot be read")
        yield b""  # pragma: no cover - makes this an async generator, mirroring the httpx base class


class _UnreadableSyncStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        raise RuntimeError("stream cannot be read")
        yield b""  # pragma: no cover - makes this a generator, mirroring the httpx base class


class _UncloseableAsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"body"

    async def aclose(self) -> None:
        raise RuntimeError("close failed")


class _UncloseableSyncStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"body"

    def close(self) -> None:
        raise RuntimeError("close failed")


def _async_normalizer() -> AsyncHttpxNormalizer:
    return AsyncHttpxNormalizer(dict(DEFAULT_TIMEOUT), _FakeClock())


def _sync_normalizer() -> SyncHttpxNormalizer:
    return SyncHttpxNormalizer(dict(DEFAULT_TIMEOUT), _FakeClock())


async def test__async_freeze__false_when_the_body_cannot_be_read() -> None:
    normalizer = _async_normalizer()
    request = httpx.Request("POST", "https://a.example/x", stream=_UnreadableAsyncStream())
    view = normalizer.wrap_request(request)
    assert await normalizer.freeze(view) is False


async def test__async_discard__swallows_a_failing_close() -> None:
    normalizer = _async_normalizer()
    view = normalizer.wrap_response(httpx.Response(200, stream=_UncloseableAsyncStream()))
    assert await normalizer.discard(view) is None


def test__async_conn_metrics__honestly_absent() -> None:
    normalizer = _async_normalizer()
    view = normalizer.wrap_response(httpx.Response(200))
    assert normalizer.conn_metrics(view) is None


def test__sync_freeze__false_when_the_body_cannot_be_read() -> None:
    normalizer = _sync_normalizer()
    request = httpx.Request("POST", "https://a.example/x", stream=_UnreadableSyncStream())
    view = normalizer.wrap_request(request)
    assert normalizer.freeze(view) is False


def test__sync_discard__swallows_a_failing_close() -> None:
    normalizer = _sync_normalizer()
    view = normalizer.wrap_response(httpx.Response(200, stream=_UncloseableSyncStream()))
    assert normalizer.discard(view) is None


def test__sync_conn_metrics__honestly_absent() -> None:
    normalizer = _sync_normalizer()
    view = normalizer.wrap_response(httpx.Response(200))
    assert normalizer.conn_metrics(view) is None


# --- proxy router transports -------------------------------------------------


class _MarkerAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=self.marker)

    async def aclose(self) -> None:
        self.closed = True


class _MarkerSyncTransport(httpx.BaseTransport):
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=self.marker)

    def close(self) -> None:
        self.closed = True


async def test__async_proxy_router__routes_by_scheme_and_no_proxy() -> None:
    router = AsyncProxyRouterTransport(
        _MarkerAsyncTransport("direct"),
        {"http": _MarkerAsyncTransport("http-proxy"), "https": _MarkerAsyncTransport("https-proxy")},
        ("internal.corp",),
    )
    assert (await router.handle_async_request(httpx.Request("GET", "http://a.example/"))).text == "http-proxy"
    assert (await router.handle_async_request(httpx.Request("GET", "https://a.example/"))).text == "https-proxy"
    assert (await router.handle_async_request(httpx.Request("GET", "https://svc.internal.corp/x"))).text == "direct"


async def test__async_proxy_router__unproxied_scheme_falls_back_to_direct() -> None:
    router = AsyncProxyRouterTransport(_MarkerAsyncTransport("direct"), {}, ())
    assert (await router.handle_async_request(httpx.Request("GET", "http://a.example/"))).text == "direct"


async def test__async_proxy_router__aclose_closes_direct_and_every_proxy_transport() -> None:
    direct = _MarkerAsyncTransport("direct")
    by_scheme = {"http": _MarkerAsyncTransport("h"), "https": _MarkerAsyncTransport("s")}
    router = AsyncProxyRouterTransport(direct, dict(by_scheme), ())
    await router.aclose()
    assert direct.closed is True
    assert all(transport.closed for transport in by_scheme.values())


def test__sync_proxy_router__close_closes_direct_and_every_proxy_transport() -> None:
    direct = _MarkerSyncTransport("direct")
    by_scheme = {"http": _MarkerSyncTransport("h"), "https": _MarkerSyncTransport("s")}
    router = SyncProxyRouterTransport(direct, dict(by_scheme), ())
    router.close()
    assert direct.closed is True
    assert all(transport.closed for transport in by_scheme.values())


# --- capability reporting through the shared builder -------------------------


def test__http2__reported_applied_natively() -> None:
    handle = clientwright.build_sync_handle("httpx", ClientConfig(service_name="s", pool=PoolConfig(http2=True)))
    try:
        assert Capability.HTTP2 in handle.report.applied_natively
    finally:
        assert handle.close is not None
        handle.close()


def test__explicit_proxy__reported_applied_natively() -> None:
    config = ClientConfig(service_name="s", proxy=ProxyConfig(url="http://proxy.local:3128"))
    handle = clientwright.build_sync_handle("httpx", config)
    try:
        assert Capability.PROXY in handle.report.applied_natively
    finally:
        assert handle.close is not None
        handle.close()


def test__per_host_limit__reported_emulated_not_dropped() -> None:
    config = ClientConfig(service_name="s", pool=PoolConfig(max_connections_per_host=5))
    handle = clientwright.build_sync_handle("httpx", config)
    try:
        assert Capability.POOL_LIMIT_PER_HOST in handle.report.emulated
        assert Capability.POOL_LIMIT_PER_HOST not in handle.report.dropped
    finally:
        assert handle.close is not None
        handle.close()


# --- environment proxies under the engine seam -------------------------------


def _set_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://proxy.local:3128")
    monkeypatch.setenv("https_proxy", "http://secure-proxy.local:3128")
    monkeypatch.setenv("no_proxy", "internal.example, *")


def test__sync_build_from_env__mounts_the_proxy_router_inside_the_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_proxy_env(monkeypatch)
    config = ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True))
    handle = clientwright.build_sync_handle("httpx", config)
    try:
        # White-box wiring check: the router must sit INSIDE the engine seam so
        # every owned-redirect hop re-routes (client-level mounts are resolved
        # only once per logical call and could not).
        transport = handle.client._transport
        assert isinstance(transport, SyncEngineTransport)
        router = transport._inner
        assert isinstance(router, SyncProxyRouterTransport)
        assert set(router._by_scheme) == {"http", "https"}
        assert router._no_proxy_hosts == ("internal.example",)  # the "*" wildcard is filtered out
    finally:
        assert handle.close is not None
        handle.close()  # walks the router: direct + every per-scheme transport is closed


async def test__async_build_from_env__mounts_the_proxy_router_inside_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_proxy_env(monkeypatch)
    config = ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True))
    handle = clientwright.build_handle("httpx", config)
    try:
        transport = handle.client._transport
        assert isinstance(transport, AsyncEngineTransport)
        router = transport._inner
        assert isinstance(router, AsyncProxyRouterTransport)
        assert set(router._by_scheme) == {"http", "https"}
        assert router._no_proxy_hosts == ("internal.example",)
    finally:
        assert handle.aclose is not None
        await handle.aclose()  # walks the router: direct + every per-scheme transport is closed


def test__from_env_without_proxies__keeps_the_direct_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patched at the function level: on Windows getproxies() would otherwise
    # fall back to registry proxies and the test would depend on the machine.
    monkeypatch.setattr("urllib.request.getproxies", dict)
    config = ClientConfig(service_name="s", proxy=ProxyConfig(from_env=True))
    handle = clientwright.build_sync_handle("httpx", config)
    try:
        inner = handle.client._transport._inner
        assert isinstance(inner, httpx.HTTPTransport)  # no router when the environment has nothing to say
    finally:
        assert handle.close is not None
        handle.close()
