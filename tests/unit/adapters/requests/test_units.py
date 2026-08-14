"""requests adapter units: views, classification, dual-family errors, build gates."""

from __future__ import annotations

import socket
import ssl

import pytest

requests = pytest.importorskip("requests", reason="requires the [requests] extra")
# requests sits on urllib3, and these tests reach for its exception types directly.
urllib3 = pytest.importorskip("urllib3", reason="requires the [requests] extra")

import clientwright  # noqa: E402
from clientwright.adapters.requests import (  # noqa: E402
    RequestsAdapter,
    RequestsCircuitOpenError,
    RequestsDeadlineExceededError,
    RequestsTooManyRedirectsError,
)
from clientwright.adapters.requests.classify import classify_error  # noqa: E402
from clientwright.adapters.requests.errors import translate_call_error  # noqa: E402
from clientwright.adapters.requests.views import (  # noqa: E402
    CALLER_TIMEOUT_ATTRIBUTE,
    RequestsRequestView,
    caller_timeouts_from,
)
from clientwright.core.errors import (  # noqa: E402
    CallError,
    CircuitOpenError,
    DeadlineExceededError,
    TooManyRedirectsError,
    UnsupportedCapabilityError,
)
from clientwright.core.model import FailureKind  # noqa: E402


def prepared(method: str = "GET", url: str = "http://example.com/a", body: bytes | None = None) -> object:
    return requests.Request(method, url, data=body).prepare()


# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (requests.exceptions.ConnectTimeout(), FailureKind.CONNECT_TIMEOUT),
        (requests.exceptions.ReadTimeout(), FailureKind.READ_TIMEOUT),
        (requests.exceptions.Timeout(), FailureKind.TOTAL_TIMEOUT),
        (requests.exceptions.SSLError(), FailureKind.TLS_ERROR),
        (requests.exceptions.ProxyError(), FailureKind.CONNECT_ERROR),
        (requests.exceptions.ChunkedEncodingError(), FailureKind.BODY_ERROR),
        (requests.exceptions.ConnectionError(), FailureKind.CONNECT_ERROR),
        (TimeoutError(), FailureKind.TOTAL_TIMEOUT),
        (ValueError("nope"), FailureKind.UNKNOWN),
    ],
)
def test__exception__maps_to_kind(exc: BaseException, expected: FailureKind) -> None:
    assert classify_error(exc) is expected


def test__connection_error__cause_chain_distinguishes_disconnect() -> None:
    inner = urllib3.exceptions.ProtocolError("Connection aborted")
    exc = requests.exceptions.ConnectionError(inner)
    assert classify_error(exc) is FailureKind.DISCONNECTED


def test__connection_error__cause_chain_distinguishes_dns_failure() -> None:
    reason = urllib3.exceptions.NameResolutionError(
        "api.example.com",
        None,  # type: ignore[arg-type]
        socket.gaierror(8, "nodename nor servname provided"),
    )
    exc = requests.exceptions.ConnectionError(reason)
    assert classify_error(exc) is FailureKind.DNS_ERROR


def test__connection_error__ssl_cause_is_tls_error() -> None:
    exc = requests.exceptions.ConnectionError("wrapped")
    exc.__cause__ = ssl.SSLError("handshake failed")
    assert classify_error(exc) is FailureKind.TLS_ERROR


# --- dual-family errors ------------------------------------------------------


def test__all_three__catchable_in_both_families() -> None:
    circuit = translate_call_error(CircuitOpenError("http://x:80"))
    assert isinstance(circuit, RequestsCircuitOpenError)
    assert isinstance(circuit, requests.RequestException)

    deadline = translate_call_error(DeadlineExceededError(2.0))
    assert isinstance(deadline, RequestsDeadlineExceededError)
    assert isinstance(deadline, requests.Timeout)

    redirects = translate_call_error(TooManyRedirectsError(5))
    assert isinstance(redirects, RequestsTooManyRedirectsError)
    assert isinstance(redirects, requests.TooManyRedirects)


def test__foreign_call_error__passed_through() -> None:
    original = CallError("as-is")
    assert translate_call_error(original) is original


# --- caller timeouts ---------------------------------------------------------


def test__float__applies_to_connect_and_read() -> None:
    resolved = caller_timeouts_from(2.5)
    assert resolved is not None
    assert resolved.connect == 2.5
    assert resolved.read == 2.5


def test__tuple__maps_positionally() -> None:
    resolved = caller_timeouts_from((1.0, 7.0))
    assert resolved is not None
    assert resolved.connect == 1.0
    assert resolved.read == 7.0


def test__none__means_no_override() -> None:
    assert caller_timeouts_from(None) is None


def test__unrecognized_forms__ignored() -> None:
    assert caller_timeouts_from("weird") is None
    assert caller_timeouts_from((1.0, 2.0, 3.0)) is None


def test__view__reads_the_parked_attribute() -> None:
    request = prepared()
    setattr(request, CALLER_TIMEOUT_ATTRIBUTE, (0.5, 1.5))
    view = RequestsRequestView(request)  # type: ignore[arg-type]
    caller = view.caller_timeouts()
    assert caller is not None
    assert caller.read == 1.5


# --- request view ------------------------------------------------------------


def test__retarget__rewrites_url_method_and_drops_body() -> None:
    request = prepared("POST", body=b"data")
    view = RequestsRequestView(request)  # type: ignore[arg-type]
    view.retarget("http://other.example:8080/b", method="GET", drop_body=True)
    native = view.native
    assert native.url == "http://other.example:8080/b"
    assert native.method == "GET"
    assert native.body is None
    assert "Content-Length" not in native.headers


def test__retarget__rewrites_a_caller_set_host_header() -> None:
    request = requests.Request("GET", "http://a.example/x", headers={"Host": "a.example"}).prepare()
    view = RequestsRequestView(request)  # type: ignore[arg-type]
    view.retarget("http://b.example:8080/y")
    assert view.native.headers["Host"] == "b.example:8080"


# --- build gates -------------------------------------------------------------


def test__build_async__raises_sync_only() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="sync-only"):
        clientwright.build("requests", clientwright.ClientConfig(service_name="s"))


def test__base_url__rejected_with_hint() -> None:
    config = clientwright.ClientConfig(service_name="s", base_url="http://api.example.com")
    with pytest.raises(UnsupportedCapabilityError, match="base_url"):
        RequestsAdapter().build_sync(config, clientwright.default_deps())


def test__build__returns_exact_native_session_with_report() -> None:
    handle = clientwright.build_sync_handle("requests", clientwright.ClientConfig(service_name="s"))
    assert type(handle.client) is requests.Session
    assert handle.adapter == "requests"
    assert not handle.report.has_issues
    assert clientwright.inspect(handle.client) is handle
    assert handle.close is not None
    handle.close()
