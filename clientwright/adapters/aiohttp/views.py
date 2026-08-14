"""RequestView/ResponseView implementations over aiohttp objects."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import cast

from ...core.model import IDEMPOTENT_METHODS, RequestInfo, ResolvedTimeouts, origin_of
from ._imports import URL, aiohttp
from .options import current_call_options

_BODY_HEADERS = ("Content-Length", "Content-Type", "Transfer-Encoding")


def _host_header(url: URL) -> str:
    host = url.host or ""
    if url.explicit_port is None or url.is_default_port():
        return host
    return f"{host}:{url.explicit_port}"


class AiohttpRequestView:
    __slots__ = ("_options", "_request", "pending_empty_body")

    def __init__(self, request: aiohttp.ClientRequest) -> None:
        self._request = request
        # Snapshot ONCE: the view lives for the whole logical call, while the
        # caller's context may have moved on by the time a retry fires.
        self._options = current_call_options()
        # Bodies can only be replaced with an await (update_body); a sync
        # retarget marks the drop and the middleware applies it before send.
        self.pending_empty_body = False

    @property
    def native(self) -> aiohttp.ClientRequest:
        return self._request

    @property
    def info(self) -> RequestInfo:
        request = self._request
        method = request.method
        url = str(request.url)
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
        # Per-request timeout= exists in aiohttp but is consumed by _request
        # before the middleware runs; there is no channel to observe it here.
        return None

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        # Phase timeouts are fixed at session level (ClientRequest.timeout is
        # read-only); the engine's own asyncio.timeout enforces the attempt
        # ceiling, which is the knob that actually varies per attempt.
        return None

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        request = self._request
        target = URL(url)
        request.url = target
        # aiohttp builds each ClientResponse from original_url; without this the
        # final response (and its cookies) would be attributed to the
        # pre-redirect URL.
        request.original_url = target
        # Host was computed at construction time; a retargeted request must
        # not present the old host to the new server.
        request.headers["Host"] = _host_header(target)
        if method is not None:
            request.method = method
        if drop_body:
            for name in _BODY_HEADERS:
                request.headers.pop(name, None)
            self.pending_empty_body = True


class AiohttpResponseView:
    __slots__ = ("_response",)

    def __init__(self, response: aiohttp.ClientResponse) -> None:
        self._response = response

    @property
    def native(self) -> aiohttp.ClientResponse:
        return self._response

    @property
    def status_code(self) -> int:
        return self._response.status

    def header(self, name: str) -> str | None:
        value = self._response.headers.get(name)
        return value if isinstance(value, str) else None

    @property
    def location(self) -> str | None:
        return self.header("Location")


__all__ = ["AiohttpRequestView", "AiohttpResponseView"]
