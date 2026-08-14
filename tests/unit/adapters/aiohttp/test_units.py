"""aiohttp adapter units: views, classification, dual-family errors, options channel."""

from __future__ import annotations

import asyncio
import ssl

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="requires the [aiohttp] extra")

from aiohttp.client_reqrep import ConnectionKey  # noqa: E402
from yarl import URL  # noqa: E402

import clientwright  # noqa: E402
from clientwright.adapters.aiohttp import (  # noqa: E402
    AiohttpAdapter,
    AiohttpCircuitOpenError,
    AiohttpDeadlineExceededError,
    AiohttpTooManyRedirectsError,
    call_options,
)
from clientwright.adapters.aiohttp.classify import classify_error  # noqa: E402
from clientwright.adapters.aiohttp.errors import translate_call_error  # noqa: E402
from clientwright.adapters.aiohttp.middleware import ProxyRouter  # noqa: E402
from clientwright.adapters.aiohttp.options import current_call_options  # noqa: E402
from clientwright.adapters.aiohttp.views import AiohttpRequestView  # noqa: E402
from clientwright.core.errors import (  # noqa: E402
    CallError,
    CircuitOpenError,
    DeadlineExceededError,
    TooManyRedirectsError,
    UnsupportedCapabilityError,
)
from clientwright.core.model import FailureKind  # noqa: E402


def make_request(method: str = "GET", url: str = "http://example.com/a", body: bytes | None = None) -> object:
    loop = asyncio.get_running_loop()
    kwargs: dict[str, object] = {"loop": loop}
    if body is not None:
        kwargs["data"] = body
    return aiohttp.ClientRequest(method, URL(url), **kwargs)  # type: ignore[arg-type]


def _conn_key(host: str = "example.com", port: int = 443, is_ssl: bool = True) -> ConnectionKey:
    """A ConnectionKey padded to however many fields this aiohttp version has."""
    padding = (None,) * (len(ConnectionKey._fields) - 3)
    return ConnectionKey(host, port, is_ssl, *padding)


# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (aiohttp.ServerDisconnectedError(), FailureKind.DISCONNECTED),
        (aiohttp.ClientOSError(), FailureKind.CONNECT_ERROR),
        (aiohttp.ClientPayloadError(), FailureKind.BODY_ERROR),
        (aiohttp.ServerTimeoutError(), FailureKind.CONNECT_TIMEOUT),
        (TimeoutError(), FailureKind.TOTAL_TIMEOUT),
        (asyncio.CancelledError(), FailureKind.CANCELLED),
        (ValueError("nope"), FailureKind.UNKNOWN),
    ],
)
def test__exception__maps_to_kind(exc: BaseException, expected: FailureKind) -> None:
    assert classify_error(exc) is expected


def test__timeout_subclasses__distinguish_connect_and_read() -> None:
    assert classify_error(aiohttp.ConnectionTimeoutError()) is FailureKind.CONNECT_TIMEOUT
    assert classify_error(aiohttp.SocketTimeoutError()) is FailureKind.READ_TIMEOUT


def test__response_error__is_protocol_error() -> None:
    exc = aiohttp.ClientResponseError(request_info=None, history=())  # type: ignore[arg-type]
    assert classify_error(exc) is FailureKind.PROTOCOL_ERROR


def test__connector_certificate_error__is_tls_error() -> None:
    exc = aiohttp.ClientConnectorCertificateError(_conn_key(), ssl.CertificateError("self signed"))
    assert classify_error(exc) is FailureKind.TLS_ERROR


def test__connector_ssl_error__is_tls_error() -> None:
    exc = aiohttp.ClientConnectorSSLError(_conn_key(), OSError("handshake failed"))
    assert classify_error(exc) is FailureKind.TLS_ERROR


def test__connector_dns_error__is_dns_error() -> None:
    exc = aiohttp.ClientConnectorDNSError(_conn_key(), OSError("no such host"))
    assert classify_error(exc) is FailureKind.DNS_ERROR


def test__connector_error_with_ssl_cause__is_tls_error() -> None:
    exc = aiohttp.ClientConnectorError(_conn_key(), OSError("boom"))
    exc.__cause__ = ssl.SSLError("bad handshake")
    assert classify_error(exc) is FailureKind.TLS_ERROR


def test__connector_error_without_ssl_cause__is_connect_error() -> None:
    exc = aiohttp.ClientConnectorError(_conn_key(port=80, is_ssl=False), OSError("connection refused"))
    assert classify_error(exc) is FailureKind.CONNECT_ERROR


def test__bare_client_ssl_error__is_tls_error_not_shadowed_by_connector() -> None:
    # ClientSSLError subclasses ClientConnectorError in aiohttp>=3.14; the
    # ladder must classify it as TLS before the generic connector branch.
    exc = aiohttp.ClientSSLError(_conn_key(), OSError("tls layer broke"))
    assert classify_error(exc) is FailureKind.TLS_ERROR


# --- dual-family errors ------------------------------------------------------


def test__circuit_open__catchable_in_both_families() -> None:
    error = translate_call_error(CircuitOpenError("http://x:80", 1.5))
    assert isinstance(error, AiohttpCircuitOpenError)
    assert isinstance(error, aiohttp.ClientError)
    assert isinstance(error, CircuitOpenError)


def test__deadline__catchable_as_timeout_and_client_error() -> None:
    error = translate_call_error(DeadlineExceededError(2.0))
    assert isinstance(error, AiohttpDeadlineExceededError)
    assert isinstance(error, TimeoutError)
    assert isinstance(error, aiohttp.ClientError)
    assert "2.000" in str(error)


def test__too_many_redirects__catchable_and_printable() -> None:
    error = translate_call_error(TooManyRedirectsError(5))
    assert isinstance(error, AiohttpTooManyRedirectsError)
    assert isinstance(error, aiohttp.TooManyRedirects)
    assert str(error) == "Exceeded 5 redirect hops"
    assert error.hops == 5


def test__foreign_call_error__passed_through() -> None:
    original = CallError("as-is")
    assert translate_call_error(original) is original


# --- call options ------------------------------------------------------------


def test__nested_options__inner_wins_and_restores() -> None:
    assert current_call_options() is None
    with call_options(route="/users/{id}"):
        outer = current_call_options()
        assert outer is not None and outer.route == "/users/{id}"
        with call_options(route="/orders/{id}", idempotent=True):
            inner = current_call_options()
            assert inner is not None and inner.route == "/orders/{id}" and inner.idempotent is True
        restored = current_call_options()
        assert restored is not None and restored.route == "/users/{id}"
    assert current_call_options() is None


# --- request view ------------------------------------------------------------


async def test__info__reads_options_and_method_idempotency() -> None:
    request = make_request("POST")
    with call_options(route="/tpl", idempotent=True):
        view = AiohttpRequestView(request)  # type: ignore[arg-type]
    info = view.info
    assert info.route == "/tpl"
    assert info.idempotent is True
    assert info.method == "POST"
    assert info.origin == "http://example.com:80"


async def test__info__defaults_to_method_semantics() -> None:
    view = AiohttpRequestView(make_request("POST"))  # type: ignore[arg-type]
    assert view.info.idempotent is False
    assert view.info.route is None


async def test__retarget__rewrites_url_host_and_method() -> None:
    request = make_request("POST", "http://example.com/a", body=b"data")
    view = AiohttpRequestView(request)  # type: ignore[arg-type]
    view.retarget("http://other.example:8080/b", method="GET", drop_body=True)
    native = view.native
    assert str(native.url) == "http://other.example:8080/b"
    assert native.headers["Host"] == "other.example:8080"
    assert native.method == "GET"
    assert "Content-Length" not in native.headers
    assert view.pending_empty_body is True


async def test__retarget_to_a_default_port__host_header_omits_the_port() -> None:
    request = make_request("GET", "http://example.com:8080/a")
    view = AiohttpRequestView(request)  # type: ignore[arg-type]
    view.retarget("https://other.example/b")
    assert view.native.headers["Host"] == "other.example"
    assert str(view.native.url) == "https://other.example/b"


async def test__caller_timeouts__has_no_channel() -> None:
    view = AiohttpRequestView(make_request())  # type: ignore[arg-type]
    assert view.caller_timeouts() is None


# --- proxy router ------------------------------------------------------------


def test__explicit_proxy__applied_to_every_request() -> None:
    router = ProxyRouter("http://proxy.local:3128")

    class Req:
        url = URL("http://example.com/a")
        proxy = None

    request = Req()
    router.apply(request)  # type: ignore[arg-type]
    assert str(request.proxy) == "http://proxy.local:3128"


def test__env_proxies__respect_no_proxy_suffix() -> None:
    router = ProxyRouter(None, {"http": "http://proxy.local:3128"}, ("internal.example",))

    class Req:
        def __init__(self, url: str) -> None:
            self.url = URL(url)
            self.proxy = URL("http://stale:1")

    direct = Req("http://svc.internal.example/x")
    router.apply(direct)  # type: ignore[arg-type]
    assert direct.proxy is None

    proxied = Req("http://example.com/x")
    router.apply(proxied)  # type: ignore[arg-type]
    assert str(proxied.proxy) == "http://proxy.local:3128"


# --- build gates -------------------------------------------------------------


def test__build_sync__raises_async_only() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="async-only"):
        clientwright.build_sync("aiohttp", clientwright.ClientConfig(service_name="s"))


async def test__write_timeout__dropped_and_strict_raises() -> None:
    config = clientwright.ClientConfig(
        service_name="s",
        timeout=clientwright.TimeoutConfig(write=1.0),
        on_unsupported=clientwright.UnsupportedPolicy.STRICT,
    )
    with pytest.raises(UnsupportedCapabilityError, match="timeout_write"):
        AiohttpAdapter().build_async(config, clientwright.default_deps())


async def test__build__returns_exact_native_session_with_report() -> None:
    config = clientwright.ClientConfig(service_name="s")
    handle = clientwright.build_handle("aiohttp", config)
    try:
        assert type(handle.client) is aiohttp.ClientSession
        assert handle.adapter == "aiohttp"
        assert not handle.report.has_issues
        assert clientwright.inspect(handle.client) is handle
    finally:
        assert handle.aclose is not None
        await handle.aclose()
