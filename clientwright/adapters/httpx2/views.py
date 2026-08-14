"""RequestView/ResponseView bindings over httpx2 objects.

Same names as the httpx adapter on purpose: migrating a service is one extra
and one import path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from .._httpx_shared import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION, FamilyRequestView, FamilyResponseView
from ._imports import httpx2


class _ReplayStream(httpx2.SyncByteStream, httpx2.AsyncByteStream):
    """A byte stream that can be iterated any number of times."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def __iter__(self) -> Iterator[bytes]:
        yield self._content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content


class HttpxRequestView(FamilyRequestView):
    __slots__ = ()

    def __init__(self, request: httpx2.Request, default_timeout: dict[str, float | None]) -> None:
        super().__init__(request, default_timeout, sdk=httpx2, replay_stream=_ReplayStream)


class HttpxResponseView(FamilyResponseView):
    __slots__ = ()


__all__ = [
    "IDEMPOTENT_EXTENSION",
    "ROUTE_EXTENSION",
    "HttpxRequestView",
    "HttpxResponseView",
    "_ReplayStream",
]
