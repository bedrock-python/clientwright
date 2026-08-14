"""RequestView/ResponseView implementations over urllib3 calls.

urllib3 has no request object with stable identity - the seam is the
``urlopen(method, url, **kw)`` signature. The adapter synthesizes a mutable
call spec and the view wraps that; the send callback translates it back into
positional/keyword arguments.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from ...core.model import IDEMPOTENT_METHODS, RequestInfo, ResolvedTimeouts, origin_of
from ...core.options import current_call_options
from ._imports import Timeout


class Urllib3CallSpec:
    """The mutable identity of one logical urlopen call."""

    __slots__ = ("body", "headers", "kw", "method", "planned", "url")

    def __init__(self, method: str, url: str, headers: dict[str, str], body: Any, kw: dict[str, Any]) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.kw = kw
        self.planned: ResolvedTimeouts | None = None


def caller_timeouts_from(timeout: object) -> ResolvedTimeouts | None:
    """Translate urllib3's ``timeout=`` forms: float or urllib3.util.Timeout."""
    if timeout is None:
        return None
    if isinstance(timeout, (int, float)):
        value = float(timeout)
        return ResolvedTimeouts(connect=value, read=value)
    if isinstance(timeout, Timeout):
        connect = timeout.connect_timeout
        read = timeout.read_timeout
        return ResolvedTimeouts(
            connect=float(connect) if isinstance(connect, (int, float)) else None,
            read=float(read) if isinstance(read, (int, float)) else None,
        )
    return None


class Urllib3RequestView:
    __slots__ = ("_caller", "_options", "_spec")

    def __init__(self, spec: Urllib3CallSpec) -> None:
        self._spec = spec
        self._options = current_call_options()
        self._caller = caller_timeouts_from(spec.kw.get("timeout"))

    @property
    def native(self) -> Urllib3CallSpec:
        return self._spec

    @property
    def info(self) -> RequestInfo:
        spec = self._spec
        options = self._options
        route = options.route if options is not None else None
        if options is not None and options.idempotent is not None:
            idempotent = options.idempotent
        else:
            idempotent = spec.method in IDEMPOTENT_METHODS
        return RequestInfo(
            method=spec.method, origin=origin_of(spec.url), url=spec.url, route=route, idempotent=idempotent
        )

    @property
    def headers(self) -> MutableMapping[str, str]:
        return self._spec.headers

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        return self._caller

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        self._spec.planned = timeouts

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        spec = self._spec
        spec.url = url
        if method is not None:
            spec.method = method
        if drop_body:
            for name in ("Content-Length", "Content-Type", "Transfer-Encoding"):
                spec.headers.pop(name, None)
            spec.body = None


class Urllib3ResponseView:
    __slots__ = ("_response",)

    def __init__(self, response: Any) -> None:
        self._response = response

    @property
    def native(self) -> Any:
        return self._response

    @property
    def status_code(self) -> int:
        return int(self._response.status)

    def header(self, name: str) -> str | None:
        value = self._response.headers.get(name)
        return value if isinstance(value, str) else None

    @property
    def location(self) -> str | None:
        return self.header("Location")


__all__ = ["Urllib3CallSpec", "Urllib3RequestView", "Urllib3ResponseView", "caller_timeouts_from"]
