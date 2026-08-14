"""Model helpers: origin normalization and circuit keys."""

from __future__ import annotations

from clientwright.core.model import CircuitKey, RequestInfo, origin_of

# --- origin_of ---


def test__https_default_port__made_explicit() -> None:
    assert origin_of("https://API.Example.com/path?q=1") == "https://api.example.com:443"


def test__http_custom_port__preserved() -> None:
    assert origin_of("http://localhost:8080/x") == "http://localhost:8080"


# --- RequestInfo ---


def test__circuit_key__origin_route_and_method_modes() -> None:
    info = RequestInfo(method="GET", origin="https://a:443", url="https://a/u", route="/u")
    assert info.circuit_key(CircuitKey.ORIGIN) == "https://a:443"
    assert info.circuit_key(CircuitKey.ORIGIN_ROUTE) == "https://a:443 /u"
    assert info.circuit_key(CircuitKey.ORIGIN_METHOD) == "https://a:443 GET"


def test__circuit_key__missing_route__labelled_unknown() -> None:
    info = RequestInfo(method="GET", origin="https://a:443", url="https://a/u")
    assert info.circuit_key(CircuitKey.ORIGIN_ROUTE) == "https://a:443 unknown"
