"""Minimal RequestView/ResponseView fakes shared by core unit tests."""

from __future__ import annotations

from clientwright.core.model import RequestInfo, ResolvedTimeouts, origin_of


class FakeRequest:
    def __init__(self, method: str, url: str) -> None:
        self._info = RequestInfo(method=method, origin=origin_of(url), url=url)
        self.headers: dict[str, str] = {}

    @property
    def native(self) -> object:
        return self

    @property
    def info(self) -> RequestInfo:
        return self._info

    def caller_timeouts(self) -> ResolvedTimeouts | None:
        return None

    def apply_timeouts(self, timeouts: ResolvedTimeouts) -> None:
        return None

    def retarget(self, url: str, *, method: str | None = None, drop_body: bool = False) -> None:
        return None


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self._status = status_code
        self._headers = {name.lower(): value for name, value in (headers or {}).items()}

    @property
    def native(self) -> object:
        return self

    @property
    def status_code(self) -> int:
        return self._status

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    @property
    def location(self) -> str | None:
        return self.header("location")


__all__ = ["FakeRequest", "FakeResponse"]
