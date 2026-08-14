"""Kernel errors dual-inherited into the aiohttp family.

A user's ``except aiohttp.ClientError`` (or ``except asyncio.TimeoutError``)
keeps working when clientwright raises on its own authority.
"""

from __future__ import annotations

from ...core.errors import CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ._imports import aiohttp


class AiohttpCircuitOpenError(CircuitOpenError, aiohttp.ClientError):
    """Circuit open, catchable as aiohttp.ClientError."""


class AiohttpDeadlineExceededError(DeadlineExceededError, aiohttp.ServerTimeoutError):
    """Total deadline exhausted, catchable as asyncio.TimeoutError and aiohttp.ClientError."""


class AiohttpTooManyRedirectsError(TooManyRedirectsError, aiohttp.TooManyRedirects):
    """Owned redirect limit exceeded, catchable as aiohttp.TooManyRedirects.

    ``ClientResponseError.__init__`` demands request_info/history positionally,
    which breaks the cooperative super chain - so this class initializes both
    parents by hand and pins the aiohttp-side attributes its ``__str__`` needs.
    """

    def __init__(self, hops: int) -> None:
        Exception.__init__(self, f"Exceeded {hops} redirect hops")
        self.hops = hops
        self.request_info = None  # type: ignore[assignment]
        self.history = ()
        self.status = 0
        self.message = f"Exceeded {hops} redirect hops"
        self.headers = None

    def __str__(self) -> str:
        return self.message


def translate_call_error(error: CallError) -> BaseException:
    if isinstance(error, CircuitOpenError):
        return AiohttpCircuitOpenError(error.key, error.retry_after)
    if isinstance(error, DeadlineExceededError):
        return AiohttpDeadlineExceededError(error.total)
    if isinstance(error, TooManyRedirectsError):
        return AiohttpTooManyRedirectsError(error.hops)
    return error


__all__ = [
    "AiohttpCircuitOpenError",
    "AiohttpDeadlineExceededError",
    "AiohttpTooManyRedirectsError",
    "translate_call_error",
]
