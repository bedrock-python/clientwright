"""Per-origin in-flight limiters emulating a per-host connection limit.

This limits in-flight REQUESTS, not connections - close but not identical,
which is why adapters relying on it declare ``POOL_LIMIT_PER_HOST: EMULATED``.

The async limiter keys its semaphores by the RUNNING EVENT LOOP: an APP-scoped
runtime may serve several loops over its lifetime (worker threads, sequential
``asyncio.run`` calls, test suites), and an ``asyncio.Semaphore`` binds to the
loop of its first contended acquire. Per-loop state also dies with its loop,
so slots consumed in a dead loop cannot shrink the limit forever.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from types import TracebackType


class AsyncOriginLimiter:
    """Per-(event loop, origin) semaphores; safe to share across loops and threads."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._per_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]] = (
            weakref.WeakKeyDictionary()
        )
        self._lock = threading.Lock()

    def _semaphore(self, origin: str) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._lock:
            per_origin = self._per_loop.get(loop)
            if per_origin is None:
                per_origin = {}
                self._per_loop[loop] = per_origin
            semaphore = per_origin.get(origin)
            if semaphore is None:
                semaphore = asyncio.Semaphore(self._limit)
                per_origin[origin] = semaphore
        return semaphore

    def acquire(self, origin: str) -> _AsyncSlot:
        return _AsyncSlot(self._semaphore(origin))


class _AsyncSlot:
    def __init__(self, semaphore: asyncio.Semaphore) -> None:
        self._semaphore = semaphore

    async def __aenter__(self) -> None:
        await self._semaphore.acquire()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._semaphore.release()


class SyncOriginLimiter:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()

    def _semaphore(self, origin: str) -> threading.BoundedSemaphore:
        with self._lock:
            semaphore = self._semaphores.get(origin)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(self._limit)
                self._semaphores[origin] = semaphore
            return semaphore

    def acquire(self, origin: str) -> _SyncSlot:
        return _SyncSlot(self._semaphore(origin))


class _SyncSlot:
    def __init__(self, semaphore: threading.BoundedSemaphore) -> None:
        self._semaphore = semaphore

    def __enter__(self) -> None:
        self._semaphore.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._semaphore.release()


__all__ = ["AsyncOriginLimiter", "SyncOriginLimiter"]
