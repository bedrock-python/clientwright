"""Async normalizer binding: shared family logic over the httpx2 SDK."""

from __future__ import annotations

from collections.abc import Callable

from .._httpx_shared import AsyncFamilyNormalizer, AsyncTimedStreamMixin
from ._imports import httpx2
from .views import HttpxRequestView


class _TimedAsyncStream(AsyncTimedStreamMixin, httpx2.AsyncByteStream):
    """Times body consumption and reports read failures exactly once."""


class AsyncHttpxNormalizer(AsyncFamilyNormalizer):
    def __init__(self, default_timeout: dict[str, float | None], clock: Callable[[], float]) -> None:
        super().__init__(
            default_timeout,
            clock,
            sdk=httpx2,
            request_view=lambda native: HttpxRequestView(native, default_timeout),
            timed_stream=_TimedAsyncStream,
        )


__all__ = ["AsyncHttpxNormalizer"]
