"""httpx adapter units: views, classification, dual-family errors, native validation."""

from __future__ import annotations

import gc
import pathlib
import ssl
import weakref

import pytest

httpx = pytest.importorskip("httpx", reason="requires the [httpx] extra")

import clientwright  # noqa: E402
from clientwright import TimeoutConfig, UnsupportedPolicy  # noqa: E402
from clientwright.adapters.httpx import (  # noqa: E402
    IDEMPOTENT_EXTENSION,
    ROUTE_EXTENSION,
    HttpxAdapter,
    HttpxCircuitOpenError,
    HttpxDeadlineExceededError,
    HttpxTooManyRedirectsError,
)
from clientwright.adapters.httpx.classify import classify_error  # noqa: E402
from clientwright.adapters.httpx.errors import translate_call_error  # noqa: E402
from clientwright.adapters.httpx.transport import SyncProxyRouterTransport  # noqa: E402
from clientwright.adapters.httpx.views import HttpxRequestView, _ReplayStream  # noqa: E402
from clientwright.core.capabilities import Capability  # noqa: E402
from clientwright.core.config import ClientConfig, NativeOptions, TlsConfig  # noqa: E402
from clientwright.core.errors import (  # noqa: E402
    CircuitOpenError,
    DeadlineExceededError,
    NotReplayableError,
    ReservedNativeKeyError,
    TooManyRedirectsError,
    UnknownNativeKeyError,
    UnsupportedCapabilityError,
)
from clientwright.core.model import FailureKind, ResolvedTimeouts  # noqa: E402

DEFAULT_TIMEOUT = {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}


def view(request: httpx.Request) -> HttpxRequestView:
    return HttpxRequestView(request, DEFAULT_TIMEOUT)


# --- request view ------------------------------------------------------------


def test__info__derived_from_request_and_extensions() -> None:
    request = httpx.Request(
        "POST",
        "https://api.example.com/users/42",
        extensions={ROUTE_EXTENSION: "/users/{id}", IDEMPOTENT_EXTENSION: True},
    )
    info = view(request).info
    assert info.origin == "https://api.example.com:443"
    assert info.route == "/users/{id}"
    assert info.idempotent  # forced by the extension despite POST


def test__caller_timeouts__none_when_matching_defaults() -> None:
    request = httpx.Request("GET", "https://a/x", extensions={"timeout": dict(DEFAULT_TIMEOUT)})
    assert view(request).caller_timeouts() is None


def test__caller_timeouts__detected_when_caller_overrides() -> None:
    request = httpx.Request("GET", "https://a/x", extensions={"timeout": {"connect": 1.0, "read": 2.0}})
    caller = view(request).caller_timeouts()
    assert caller is not None
    assert caller.read == 2.0


def test__apply_timeouts__writes_extension_dict() -> None:
    request = httpx.Request("GET", "https://a/x")
    v = view(request)
    v.apply_timeouts(ResolvedTimeouts(connect=1.0, read=2.0, write=3.0, pool_acquire=4.0))
    assert request.extensions["timeout"] == {"connect": 1.0, "read": 2.0, "write": 3.0, "pool": 4.0}


def test__retarget__mutates_original_request_in_place() -> None:
    request = httpx.Request("POST", "https://a.example/x", content=b"payload")
    request.read()
    v = view(request)
    v.retarget("https://b.example/y", method="GET", drop_body=True)
    # Identity is the contract: httpx's client layer holds THIS object and
    # attributes cookies/response.url to it after the transport returns.
    assert v.native is request
    assert str(request.url) == "https://b.example/y"
    assert request.method == "GET"
    assert request.headers["host"] == "b.example"
    assert "content-length" not in request.headers
    assert request.read() == b""


def test__retarget_307__body_preserved() -> None:
    request = httpx.Request("POST", "https://a.example/x", content=b"payload")
    request.read()
    v = view(request)
    v.retarget("https://a.example/y")
    assert v.native is request
    assert v.native.read() == b"payload"


def test__caller_timeouts__not_confused_by_engine_writes() -> None:
    request = httpx.Request("GET", "https://a/x", extensions={"timeout": dict(DEFAULT_TIMEOUT)})
    v = view(request)
    v.apply_timeouts(ResolvedTimeouts(connect=1.0, read=1.0, write=1.0, pool_acquire=1.0))
    # The engine's own writes on hop 1 must not read back as a caller
    # override on hop 2.
    assert v.caller_timeouts() is None


# --- replay stream -----------------------------------------------------------


def test__replay_stream__sync_iteration_replays_any_number_of_times() -> None:
    stream = _ReplayStream(b"payload")
    assert list(stream) == [b"payload"]
    assert list(stream) == [b"payload"]


async def test__replay_stream__async_iteration_replays_any_number_of_times() -> None:
    stream = _ReplayStream(b"payload")
    assert [chunk async for chunk in stream] == [b"payload"]
    assert [chunk async for chunk in stream] == [b"payload"]


# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx.ConnectTimeout("t"), FailureKind.CONNECT_TIMEOUT),
        (httpx.ReadTimeout("t"), FailureKind.READ_TIMEOUT),
        (httpx.WriteTimeout("t"), FailureKind.WRITE_TIMEOUT),
        (httpx.PoolTimeout("t"), FailureKind.POOL_TIMEOUT),
        (httpx.ConnectError("boom"), FailureKind.CONNECT_ERROR),
        (httpx.ReadError("boom"), FailureKind.DISCONNECTED),
        (httpx.RemoteProtocolError("boom"), FailureKind.PROTOCOL_ERROR),
        (TimeoutError(), FailureKind.TOTAL_TIMEOUT),
        (RuntimeError("boom"), FailureKind.UNKNOWN),
    ],
)
def test__exception__mapped_to_kind(exc: BaseException, kind: FailureKind) -> None:
    assert classify_error(exc) is kind


def test__connect_error_with_ssl_cause__is_tls_error() -> None:
    error = httpx.ConnectError("boom")
    error.__cause__ = ssl.SSLError("bad cert")
    assert classify_error(error) is FailureKind.TLS_ERROR


# --- dual-family errors ------------------------------------------------------


def test__circuit_open__catchable_both_ways() -> None:
    error = translate_call_error(CircuitOpenError("key", 1.0))
    assert isinstance(error, HttpxCircuitOpenError)
    assert isinstance(error, httpx.HTTPError)
    assert isinstance(error, CircuitOpenError)


def test__deadline__catchable_as_httpx_timeout() -> None:
    error = translate_call_error(DeadlineExceededError(5.0))
    assert isinstance(error, HttpxDeadlineExceededError)
    assert isinstance(error, httpx.TimeoutException)


def test__redirects__catchable_as_httpx_too_many_redirects() -> None:
    error = translate_call_error(TooManyRedirectsError(5))
    assert isinstance(error, HttpxTooManyRedirectsError)
    assert isinstance(error, httpx.TooManyRedirects)


def test__other_call_errors__pass_through() -> None:
    original = NotReplayableError("nope")
    assert translate_call_error(original) is original


# --- native option validation through the adapter ----------------------------


def test__reserved_transport_retries__rejected_with_hint() -> None:
    config = ClientConfig(service_name="svc", native=NativeOptions.of(transport={"retries": 3}))
    with pytest.raises(ReservedNativeKeyError, match=r"ClientConfig\.retry"):
        HttpxAdapter().build_async(config, clientwright.default_deps())


def test__typo_in_transport_slot__suggested() -> None:
    config = ClientConfig(service_name="svc", native=NativeOptions.of(transport={"local_addres": "10.0.0.1"}))
    with pytest.raises(UnknownNativeKeyError, match="local_address"):
        HttpxAdapter().build_async(config, clientwright.default_deps())


def test__legit_native_options__accepted() -> None:
    config = ClientConfig(
        service_name="svc",
        native=NativeOptions.of(client={"trust_env": False}, transport={"local_address": "0.0.0.0"}),
    )
    handle = clientwright.build_handle("httpx", config)
    assert type(handle.client) is httpx.AsyncClient


# --- TLS wiring --------------------------------------------------------------


def test__ca_bundle_with_bogus_cert__fails_at_build_not_silently(tmp_path: object) -> None:
    ca = pathlib.Path(str(tmp_path)) / "ca.pem"
    ca.write_text("not a real cert")
    config = ClientConfig(
        service_name="svc",
        tls=TlsConfig(ca_bundle=str(ca), cert=("missing.crt", "missing.key")),
    )
    # The legacy behavior silently dropped the client cert; now a bad TLS
    # config surfaces at build time.
    with pytest.raises((FileNotFoundError, ssl.SSLError)):
        clientwright.build_handle("httpx", config)


# --- sync capability honesty -------------------------------------------------


def test__sync_attempt_ceiling__reported_dropped_and_strict_fails() -> None:
    config = ClientConfig(service_name="svc", timeout=TimeoutConfig(attempt=2.0))
    handle = clientwright.build_sync_handle("httpx", config)
    assert Capability.TIMEOUT_ATTEMPT in handle.report.dropped
    handle.close()  # type: ignore[misc]
    strict = ClientConfig(
        service_name="svc", timeout=TimeoutConfig(attempt=2.0), on_unsupported=UnsupportedPolicy.STRICT
    )
    with pytest.raises(UnsupportedCapabilityError, match="timeout_attempt"):
        clientwright.build_sync_handle("httpx", strict)


def test__async_attempt_ceiling__still_emulated_not_dropped() -> None:
    config = ClientConfig(service_name="svc", timeout=TimeoutConfig(attempt=2.0))
    handle = clientwright.build_handle("httpx", config)
    assert Capability.TIMEOUT_ATTEMPT not in handle.report.dropped
    assert Capability.TIMEOUT_ATTEMPT in handle.report.emulated


# --- handle lifetime ---------------------------------------------------------


def test__dropped_client__is_garbage_collected() -> None:
    config = ClientConfig(service_name="svc")
    client = clientwright.build_sync("httpx", config)
    assert clientwright.inspect(client) is not None
    ref = weakref.ref(client)
    client.close()  # type: ignore[attr-defined]
    del client
    for _ in range(3):
        gc.collect()
    assert ref() is None  # the registry must not pin the client forever


# --- proxy router ------------------------------------------------------------


def _marker_transport(marker: str) -> httpx.BaseTransport:
    class _Marker(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=marker)

    return _Marker()


def test__routing__no_proxy_and_scheme_selection() -> None:
    router = SyncProxyRouterTransport(
        direct=_marker_transport("direct"),
        by_scheme={
            "http": _marker_transport("http-proxy"),
            "https": _marker_transport("https-proxy"),
        },
        no_proxy_hosts=("internal.corp", ".svc.local"),
    )
    assert router.handle_request(httpx.Request("GET", "http://a.example/")).text == "http-proxy"
    assert router.handle_request(httpx.Request("GET", "https://a.example/")).text == "https-proxy"
    assert router.handle_request(httpx.Request("GET", "https://internal.corp/x")).text == "direct"
    assert router.handle_request(httpx.Request("GET", "https://api.svc.local/x")).text == "direct"
