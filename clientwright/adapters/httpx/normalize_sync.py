"""Sync normalizer binding: same contract, blocking body operations."""

from __future__ import annotations

from collections.abc import Callable

from .._httpx_shared import SyncFamilyNormalizer, SyncTimedStreamMixin
from ._imports import httpx
from .views import HttpxRequestView


class _TimedSyncStream(SyncTimedStreamMixin, httpx.SyncByteStream):
    """Times body consumption and reports read failures exactly once."""


class SyncHttpxNormalizer(SyncFamilyNormalizer):
    def __init__(self, default_timeout: dict[str, float | None], clock: Callable[[], float]) -> None:
        super().__init__(
            default_timeout,
            clock,
            sdk=httpx,
            request_view=lambda native: HttpxRequestView(native, default_timeout),
            timed_stream=_TimedSyncStream,
        )


__all__ = ["SyncHttpxNormalizer"]
