"""httpx2 adapter units: family classification, replay stream and native builds.

The httpx2 adapter is the shared family logic bound to the successor SDK;
the deep behavior is covered through the httpx bindings, so these tests pin
what is httpx2-specific: the SDK actually classifies, the replay stream
iterates over httpx2 base classes and the builder returns GENUINE httpx2
clients under the registered ``"httpx2"`` name.
"""

from __future__ import annotations

import ssl

import pytest

httpx2 = pytest.importorskip("httpx2", reason="requires the [httpx2] extra")

import clientwright  # noqa: E402
from clientwright.adapters.httpx2.classify import classify_error  # noqa: E402
from clientwright.adapters.httpx2.views import _ReplayStream  # noqa: E402
from clientwright.core.model import FailureKind  # noqa: E402

# --- classification ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx2.ConnectTimeout("t"), FailureKind.CONNECT_TIMEOUT),
        (httpx2.ReadTimeout("t"), FailureKind.READ_TIMEOUT),
        (httpx2.WriteTimeout("t"), FailureKind.WRITE_TIMEOUT),
        (httpx2.PoolTimeout("t"), FailureKind.POOL_TIMEOUT),
        (httpx2.ConnectError("boom"), FailureKind.CONNECT_ERROR),
        (httpx2.ReadError("boom"), FailureKind.DISCONNECTED),
        (httpx2.LocalProtocolError("bad"), FailureKind.PROTOCOL_ERROR),
        (httpx2.ProxyError("proxy refused"), FailureKind.CONNECT_ERROR),
        (TimeoutError(), FailureKind.TOTAL_TIMEOUT),
        (RuntimeError("boom"), FailureKind.UNKNOWN),
    ],
)
def test__exception__mapped_to_kind(exc: BaseException, kind: FailureKind) -> None:
    assert classify_error(exc) is kind


def test__remote_protocol_error__disconnect_wording_is_retryable_disconnect() -> None:
    exc = httpx2.RemoteProtocolError("Server disconnected without sending a response.")
    assert classify_error(exc) is FailureKind.DISCONNECTED
    assert classify_error(httpx2.RemoteProtocolError("malformed chunk")) is FailureKind.PROTOCOL_ERROR


def test__connect_error_with_ssl_cause__is_tls_error() -> None:
    error = httpx2.ConnectError("boom")
    error.__cause__ = ssl.SSLError("bad cert")
    assert classify_error(error) is FailureKind.TLS_ERROR


# --- replay stream -----------------------------------------------------------


def test__replay_stream__sync_iteration_replays_any_number_of_times() -> None:
    stream = _ReplayStream(b"payload")
    assert list(stream) == [b"payload"]
    assert list(stream) == [b"payload"]


async def test__replay_stream__async_iteration_replays_any_number_of_times() -> None:
    stream = _ReplayStream(b"payload")
    assert [chunk async for chunk in stream] == [b"payload"]
    assert [chunk async for chunk in stream] == [b"payload"]


# --- builds ------------------------------------------------------------------


def test__build_sync__returns_exact_native_httpx2_client() -> None:
    handle = clientwright.build_sync_handle("httpx2", clientwright.ClientConfig(service_name="s"))
    assert type(handle.client) is httpx2.Client
    assert handle.adapter == "httpx2"
    assert not handle.report.has_issues
    assert clientwright.inspect(handle.client) is handle
    assert handle.close is not None
    handle.close()


async def test__build_async__returns_exact_native_httpx2_async_client() -> None:
    handle = clientwright.build_handle("httpx2", clientwright.ClientConfig(service_name="s"))
    assert type(handle.client) is httpx2.AsyncClient
    assert handle.adapter == "httpx2"
    assert clientwright.inspect(handle.client) is handle
    assert handle.aclose is not None
    await handle.aclose()
