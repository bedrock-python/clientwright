"""urllib3 adapter units: call spec, classification, retry translation, delegated plan."""

from __future__ import annotations

import socket

import pytest

urllib3 = pytest.importorskip("urllib3", reason="requires the [urllib3] extra")

import clientwright  # noqa: E402
from clientwright.adapters.urllib3 import (  # noqa: E402
    Urllib3Adapter,
    Urllib3CircuitOpenError,
    Urllib3DeadlineExceededError,
    Urllib3TooManyRedirectsError,
    translate_retry,
)
from clientwright.adapters.urllib3.classify import classify_error  # noqa: E402
from clientwright.adapters.urllib3.errors import translate_call_error  # noqa: E402
from clientwright.adapters.urllib3.views import (  # noqa: E402
    Urllib3CallSpec,
    Urllib3RequestView,
    caller_timeouts_from,
)
from clientwright.core.config import RetryConfig, RetryMode  # noqa: E402
from clientwright.core.errors import (  # noqa: E402
    CallError,
    CircuitOpenError,
    DeadlineExceededError,
    TooManyRedirectsError,
    UnsupportedCapabilityError,
)
from clientwright.core.model import FailureKind  # noqa: E402
from clientwright.core.options import call_options  # noqa: E402

# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (urllib3.exceptions.ConnectTimeoutError(), FailureKind.CONNECT_TIMEOUT),
        (urllib3.exceptions.ProtocolError(), FailureKind.DISCONNECTED),
        (urllib3.exceptions.DecodeError(), FailureKind.BODY_ERROR),
        (urllib3.exceptions.TimeoutError(), FailureKind.TOTAL_TIMEOUT),
        (urllib3.exceptions.ProxyError("bad proxy", OSError("refused")), FailureKind.CONNECT_ERROR),
        (urllib3.exceptions.SSLError("handshake failed"), FailureKind.TLS_ERROR),
        (ValueError("nope"), FailureKind.UNKNOWN),
    ],
)
def test__exception__maps_to_kind(exc: BaseException, expected: FailureKind) -> None:
    assert classify_error(exc) is expected


def test__pool_errors__map_to_pool_timeout() -> None:
    empty = urllib3.exceptions.EmptyPoolError(None, "no connections left")  # type: ignore[arg-type]
    assert classify_error(empty) is FailureKind.POOL_TIMEOUT
    closed = urllib3.exceptions.ClosedPoolError(None, "pool is closed")  # type: ignore[arg-type]
    assert classify_error(closed) is FailureKind.POOL_TIMEOUT


def test__max_retry_error__classified_by_its_reason() -> None:
    reason = urllib3.exceptions.ConnectTimeoutError()
    exc = urllib3.exceptions.MaxRetryError(None, "http://x/", reason=reason)  # type: ignore[arg-type]
    assert classify_error(exc) is FailureKind.CONNECT_TIMEOUT


def test__max_retry_error_without_a_reason__unknown() -> None:
    exc = urllib3.exceptions.MaxRetryError(None, "http://x/", reason=None)  # type: ignore[arg-type]
    assert classify_error(exc) is FailureKind.UNKNOWN


def test__read_timeout__maps_to_read_kind() -> None:
    exc = urllib3.exceptions.ReadTimeoutError(None, "http://x/", "read timed out")  # type: ignore[arg-type]
    assert classify_error(exc) is FailureKind.READ_TIMEOUT


def test__name_resolution_error__is_dns_despite_the_inheritance_chain() -> None:
    # urllib3 v2 derives NameResolutionError/NewConnectionError from
    # ConnectTimeoutError; the ladder tests most-specific first so DNS is
    # seen natively - exactly what capabilities.py promises with DNS_ERROR
    # in ``emits``.
    exc = urllib3.exceptions.NameResolutionError(
        "api.example.com",
        None,  # type: ignore[arg-type]
        socket.gaierror(8, "nodename nor servname provided"),
    )
    assert classify_error(exc) is FailureKind.DNS_ERROR


def test__new_connection_error__is_connect_error_not_a_timeout() -> None:
    exc = urllib3.exceptions.NewConnectionError(None, "connection refused")  # type: ignore[arg-type]
    assert classify_error(exc) is FailureKind.CONNECT_ERROR


# --- dual-family errors ------------------------------------------------------


def test__all_three__catchable_in_both_families() -> None:
    circuit = translate_call_error(CircuitOpenError("http://x:80"))
    assert isinstance(circuit, Urllib3CircuitOpenError)
    assert isinstance(circuit, urllib3.exceptions.HTTPError)

    deadline = translate_call_error(DeadlineExceededError(2.0))
    assert isinstance(deadline, Urllib3DeadlineExceededError)
    assert isinstance(deadline, urllib3.exceptions.TimeoutError)

    redirects = translate_call_error(TooManyRedirectsError(5))
    assert isinstance(redirects, Urllib3TooManyRedirectsError)
    assert isinstance(redirects, urllib3.exceptions.MaxRetryError)
    assert str(redirects) == "Exceeded 5 redirect hops"


def test__foreign_call_error__passed_through() -> None:
    original = CallError("as-is")
    assert translate_call_error(original) is original


# --- retry translation -------------------------------------------------------


def test__config__maps_into_native_retry() -> None:
    config = RetryConfig(
        max_attempts=4,
        initial_backoff=0.5,
        max_backoff=8.0,
        jitter=0.2,
        retryable_status=frozenset({503}),
        mode=RetryMode.DELEGATED,
    )
    retry = translate_retry(config, max_redirects=3)
    assert retry.total == 3  # attempts - 1
    assert retry.redirect == 3
    assert retry.backoff_factor == 0.5
    assert retry.backoff_max == 8.0
    assert retry.status_forcelist == {503}
    assert retry.raise_on_status is False


def test__delegated_mode__disables_attempt_metrics_in_plan() -> None:
    config = clientwright.ClientConfig(
        service_name="s",
        retry=RetryConfig(mode=RetryMode.DELEGATED),
    )
    handle = clientwright.build_sync_handle("urllib3", config)
    assert handle.plan.retry_policy is None
    assert handle.plan.emit_attempt_metrics is False
    assert handle.close is not None
    handle.close()


def test__owned_mode__keeps_attempt_metrics() -> None:
    handle = clientwright.build_sync_handle("urllib3", clientwright.ClientConfig(service_name="s"))
    assert handle.plan.retry_policy is not None
    assert handle.plan.emit_attempt_metrics is True
    assert handle.close is not None
    handle.close()


# --- call spec and caller timeouts -------------------------------------------


def test__caller_timeout__detected_from_timeout_object() -> None:
    resolved = caller_timeouts_from(urllib3.util.Timeout(connect=1.0, read=6.0))
    assert resolved is not None
    assert resolved.connect == 1.0
    assert resolved.read == 6.0


def test__caller_timeout__float_applies_to_connect_and_read() -> None:
    resolved = caller_timeouts_from(2.5)
    assert resolved is not None
    assert resolved.connect == 2.5
    assert resolved.read == 2.5


def test__caller_timeout__unrecognized_forms_ignored() -> None:
    assert caller_timeouts_from(None) is None
    assert caller_timeouts_from("weird") is None


def test__info__reads_ambient_call_options() -> None:
    spec = Urllib3CallSpec("POST", "http://example.com/users/42", {}, None, {})
    with call_options(route="/users/{id}", idempotent=True):
        view = Urllib3RequestView(spec)
    info = view.info
    assert info.route == "/users/{id}"
    assert info.idempotent is True  # forced by the option despite POST


def test__info__defaults_to_method_semantics() -> None:
    view = Urllib3RequestView(Urllib3CallSpec("POST", "http://example.com/a", {}, None, {}))
    assert view.info.idempotent is False
    assert view.info.route is None


def test__retarget__rewrites_spec_and_drops_body() -> None:
    spec = Urllib3CallSpec("POST", "http://example.com/a", {"Content-Length": "4"}, b"data", {})
    view = Urllib3RequestView(spec)
    view.retarget("http://other.example/b", method="GET", drop_body=True)
    assert spec.url == "http://other.example/b"
    assert spec.method == "GET"
    assert spec.body is None
    assert "Content-Length" not in spec.headers


# --- build gates -------------------------------------------------------------


def test__build_async__raises_sync_only() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="sync-only"):
        clientwright.build("urllib3", clientwright.ClientConfig(service_name="s"))


def test__base_url__rejected_with_hint() -> None:
    config = clientwright.ClientConfig(service_name="s", base_url="http://api.example.com")
    with pytest.raises(UnsupportedCapabilityError, match="base_url"):
        Urllib3Adapter().build_sync(config, clientwright.default_deps())


def test__build__returns_exact_native_pool_manager() -> None:
    handle = clientwright.build_sync_handle("urllib3", clientwright.ClientConfig(service_name="s"))
    assert type(handle.client) is urllib3.PoolManager  # no subclass: instance urlopen injection
    assert handle.adapter == "urllib3"
    assert clientwright.inspect(handle.client) is handle
    assert handle.close is not None
    handle.close()


def test__explicit_proxy__builds_genuine_proxy_manager() -> None:
    config = clientwright.ClientConfig(
        service_name="s",
        proxy=clientwright.ProxyConfig(url="http://proxy.local:3128"),
    )
    handle = clientwright.build_sync_handle("urllib3", config)
    assert type(handle.client) is urllib3.ProxyManager
    assert handle.close is not None
    handle.close()
