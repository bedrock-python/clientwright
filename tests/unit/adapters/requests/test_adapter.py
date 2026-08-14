"""requests engine seam and builder: suppression bypass, capability reporting, session wiring.

The native ``HTTPAdapter.send`` is stubbed at the SDK boundary (no sockets);
everything above it - the engine, the timeout planner, the suppression
ContextVar - runs for real.
"""

from __future__ import annotations

from typing import Any

import pytest

requests = pytest.importorskip("requests", reason="requires the [requests] extra")

import clientwright  # noqa: E402
from clientwright.adapters.requests.views import CALLER_TIMEOUT_ATTRIBUTE  # noqa: E402
from clientwright.core.capabilities import Capability  # noqa: E402
from clientwright.core.config import (  # noqa: E402
    ClientConfig,
    NativeOptions,
    PoolConfig,
    ProxyConfig,
    TimeoutConfig,
    TlsConfig,
)
from clientwright.core.engine.suppress import suppressed  # noqa: E402
from clientwright.core.errors import UnsupportedCapabilityError  # noqa: E402


def _stub_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = "http://example.com/a"
    return response


def _patch_native_send(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub the SDK boundary; each native send records its kwargs."""
    calls: list[dict[str, Any]] = []

    def fake_send(
        self: requests.adapters.HTTPAdapter,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        calls.append({"request": request, "stream": stream, "timeout": timeout, "verify": verify})
        return _stub_response()

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return calls


# --- the suppression seam ----------------------------------------------------


def test__suppressed_call__bypasses_the_engine_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_native_send(monkeypatch)
    handle = clientwright.build_sync_handle("requests", ClientConfig(service_name="s"))
    try:
        engine_adapter = handle.client.get_adapter("http://example.com/a")
        request = requests.Request("GET", "http://example.com/a").prepare()
        with suppressed():
            response = engine_adapter.send(request, timeout=3.0)
        assert response.status_code == 200
        # The suppressed branch returns BEFORE the engine: nothing was parked
        # on the request and the caller timeout went through verbatim.
        assert not hasattr(request, CALLER_TIMEOUT_ATTRIBUTE)
        assert len(calls) == 1
        assert calls[0]["timeout"] == 3.0
    finally:
        assert handle.close is not None
        handle.close()


def test__unsuppressed_call__runs_the_engine_and_plans_the_attempt_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_native_send(monkeypatch)
    handle = clientwright.build_sync_handle("requests", ClientConfig(service_name="s"))
    try:
        engine_adapter = handle.client.get_adapter("http://example.com/a")
        request = requests.Request("GET", "http://example.com/a").prepare()
        response = engine_adapter.send(request, timeout=3.0)
        assert response.status_code == 200
        assert getattr(request, CALLER_TIMEOUT_ATTRIBUTE) == 3.0
        assert len(calls) == 1
        # The engine translated the caller's float into its planned (connect, read).
        assert calls[0]["timeout"] == (3.0, 3.0)
    finally:
        assert handle.close is not None
        handle.close()


# --- capability reporting ----------------------------------------------------


def test__per_host_limit_and_explicit_proxy__applied_natively() -> None:
    config = ClientConfig(
        service_name="s",
        pool=PoolConfig(max_connections_per_host=7),
        proxy=ProxyConfig(url="http://proxy.local:3128"),
    )
    handle = clientwright.build_sync_handle("requests", config)
    try:
        assert Capability.POOL_LIMIT_PER_HOST in handle.report.applied_natively
        assert Capability.PROXY in handle.report.applied_natively
        assert handle.client.proxies == {"http": "http://proxy.local:3128", "https": "http://proxy.local:3128"}
    finally:
        assert handle.close is not None
        handle.close()


def test__inexpressible_knobs__reported_dropped() -> None:
    config = ClientConfig(
        service_name="s",
        timeout=TimeoutConfig(attempt=2.0, write=1.0, pool_acquire=1.0),
        pool=PoolConfig(http2=True),
    )
    handle = clientwright.build_sync_handle("requests", config)
    try:
        dropped = handle.report.dropped
        assert Capability.TIMEOUT_ATTEMPT in dropped
        assert Capability.TIMEOUT_WRITE in dropped
        assert Capability.TIMEOUT_POOL in dropped
        assert Capability.HTTP2 in dropped
    finally:
        assert handle.close is not None
        handle.close()


# --- session wiring ----------------------------------------------------------


def test__client_cert_with_key_password__rejected_with_a_clear_error() -> None:
    config = ClientConfig(service_name="s", tls=TlsConfig(cert=("client.crt", "client.key", "key-password")))
    with pytest.raises(UnsupportedCapabilityError, match="password"):
        clientwright.build_sync_handle("requests", config)


def test__native_session_attributes__applied_to_the_built_session() -> None:
    config = ClientConfig(service_name="s", native=NativeOptions.of(session={"trust_env": False}))
    handle = clientwright.build_sync_handle("requests", config)
    try:
        assert handle.client.trust_env is False
    finally:
        assert handle.close is not None
        handle.close()
