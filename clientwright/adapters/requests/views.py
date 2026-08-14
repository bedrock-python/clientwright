"""RequestView/ResponseView implementations over requests objects.

The caller's per-request ``timeout=`` is not stored on the PreparedRequest;
the engine adapter receives it as a ``send()`` argument and parks it on the
request object before wrapping, which is where the view picks it up.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import cast
from urllib.parse import urlsplit

from ...core.model import IDEMPOTENT_METHODS, RequestInfo, ResolvedTimeouts, origin_of
from ...core.options import current_call_options
from ._imports import requests

# Attribute the engine adapter sets on the PreparedRequest before wrapping.
CALLER_TIMEOUT_ATTRIBUTE = "_clientwright_caller_timeout"

_BODY_HEADERS = ("Content-Length", "Content-Type", "Transfer-Encoding")


def caller_timeouts_from(timeout: object) -> ResolvedTimeouts | None:
    """Translate requests' ``timeout=`` forms: float, or (connect, read)."""
    if timeout is None:
        return None
    if isinstance(timeout, (int, float)):
        value = float(timeout)
        return ResolvedTimeouts(connect=value, read=value)
    if isinstance(timeout, tuple) and len(timeout) == 2:
        connect, read = timeout
        return ResolvedTimeouts(
            connect=float(connect) if connect is not None else None,
            read=float(read) if read is not None else None,
        )
    return None


class RequestsRequestView:
    __slots__ = ("_caller", "_options", "_request", "planned")

    def __init__(self, request: requests.PreparedRequest) -> None:
        self._request = request
        self._options = current_call_options()
        self._caller = caller_timeouts_from(getattr(request, CALLER_TIMEOUT_ATTRIBUTE, None))
        # The engine's per-attempt plan; the send callback translates it into
        # the (connect, read) tuple HTTPAdapter.send accepts.
        self.planned: ResolvedTimeouts | None = None

    @property
    def native(self) -> requests.PreparedRequest:
        return self._request

    @property
    def info(self) -> RequestInfo:
        request = self._request
        method = request.method or "GET"
        url = request.url or ""
        options = self._options
        route = options.route if options is not None else None
        if options is not None and options.idempotent is not None:
            idempotent = options.idempotent
        else:
            idempotent = method in IDEMPOTENT_METHODS
        return RequestInfo(method=method, origin=origin_of(url), url=url, route=route, idempotent=idempotent)

    @property
    def headers(self) -> MutableMapping[str, str]:
        return cast(MutableMapping[str, str], self._request.headers)

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        return self._caller

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        self.planned = timeouts

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        request = self._request
        request.url = url
        # requests never sets a Host header itself (http.client derives it from
        # the URL), but a caller-set one must not leak to the new host.
        if "Host" in request.headers:
            request.headers["Host"] = urlsplit(url).netloc
        if method is not None:
            request.method = method
        if drop_body:
            for name in _BODY_HEADERS:
                request.headers.pop(name, None)
            request.body = None


class RequestsResponseView:
    __slots__ = ("_response",)

    def __init__(self, response: requests.Response) -> None:
        self._response = response

    @property
    def native(self) -> requests.Response:
        return self._response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    def header(self, name: str) -> str | None:
        value = self._response.headers.get(name)
        return value if isinstance(value, str) else None

    @property
    def location(self) -> str | None:
        return self.header("Location")


__all__ = [
    "CALLER_TIMEOUT_ATTRIBUTE",
    "RequestsRequestView",
    "RequestsResponseView",
    "caller_timeouts_from",
]
