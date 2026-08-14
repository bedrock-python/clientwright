"""Self-test of the fault-injecting origin over bare http.client.

The chaos battery trusts these routes to fail in a specific way; this file pins
that behavior with the standard library only, so it also runs in the core-only
environment and documents each fault's exact wire shape.
"""

from __future__ import annotations

import http.client
from urllib.parse import urlsplit

import pytest

from clientwright.core.testing import OriginServer


def _connection(origin: OriginServer) -> http.client.HTTPConnection:
    parts = urlsplit(origin.url)
    assert parts.hostname is not None
    assert parts.port is not None
    return http.client.HTTPConnection(parts.hostname, parts.port, timeout=5.0)


def _get(origin: OriginServer, path: str) -> http.client.HTTPResponse:
    connection = _connection(origin)
    connection.request("GET", path)
    return connection.getresponse()


def test__drop_body__announces_ten_bytes_but_dies_after_three(origin: OriginServer) -> None:
    response = _get(origin, "/drop-body")
    assert response.status == 200
    assert response.getheader("Content-Length") == "10"
    with pytest.raises(http.client.IncompleteRead) as excinfo:
        response.read()
    assert excinfo.value.partial == b"abc"


def test__garbage__is_not_even_http(origin: OriginServer) -> None:
    connection = _connection(origin)
    connection.request("GET", "/garbage")
    with pytest.raises(http.client.BadStatusLine):
        connection.getresponse()


def test__reset__is_a_hard_tcp_reset(origin: OriginServer) -> None:
    connection = _connection(origin)
    connection.request("GET", "/reset")
    with pytest.raises((ConnectionResetError, ConnectionAbortedError, http.client.BadStatusLine)):
        connection.getresponse().read()


def test__disconnect__closes_without_any_response(origin: OriginServer) -> None:
    connection = _connection(origin)
    connection.request("GET", "/disconnect")
    with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
        connection.getresponse()


def test__hang_body__delivers_everything_to_a_patient_reader(origin: OriginServer) -> None:
    response = _get(origin, "/hang-body/0.2")
    assert response.read() == b"0123456789"


def test__flaky_disconnect__drops_then_recovers(origin: OriginServer) -> None:
    first = _connection(origin)
    first.request("GET", "/flaky-disconnect/selftest/1")
    with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
        first.getresponse()
    second = _get(origin, "/flaky-disconnect/selftest/1")
    assert second.status == 200
    assert second.read() == b"recovered"


def test__retry_after__stamped_on_the_503(origin: OriginServer) -> None:
    response = _get(origin, "/retry-after/7")
    assert response.status == 503
    assert response.getheader("Retry-After") == "7"
    response.read()


def test__methods__put_delete_head_and_unknown_route(origin: OriginServer) -> None:
    for method in ("PUT", "DELETE"):
        connection = _connection(origin)
        connection.request(method, "/echo", body=b"payload")
        response = connection.getresponse()
        assert response.status == 200
        assert f'"method": "{method}"' in response.read().decode()
        connection.close()
    head = _connection(origin)
    head.request("HEAD", "/echo")
    head_response = head.getresponse()
    assert head_response.status == 200
    assert head_response.read() == b""  # HEAD carries headers only
    head.close()
    missing = _get(origin, "/no-such-route")
    assert missing.status == 404
