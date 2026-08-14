"""RequestView/ResponseView bindings over httpx objects.

The logic lives in ``adapters/_httpx_shared``; this module binds it to the
httpx SDK. The request class is shared by the sync and async clients, so one
pair of views serves both normalizers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from .._httpx_shared import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION, FamilyRequestView, FamilyResponseView
from ._imports import httpx


class _ReplayStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A byte stream that can be iterated any number of times."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def __iter__(self) -> Iterator[bytes]:
        yield self._content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content


class HttpxRequestView(FamilyRequestView):
    __slots__ = ()

    def __init__(self, request: httpx.Request, default_timeout: dict[str, float | None]) -> None:
        super().__init__(request, default_timeout, sdk=httpx, replay_stream=_ReplayStream)


class HttpxResponseView(FamilyResponseView):
    __slots__ = ()


__all__ = [
    "IDEMPOTENT_EXTENSION",
    "ROUTE_EXTENSION",
    "HttpxRequestView",
    "HttpxResponseView",
    "_ReplayStream",
]
