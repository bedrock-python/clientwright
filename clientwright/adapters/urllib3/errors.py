"""Kernel errors dual-inherited into the urllib3 family.

A user's ``except urllib3.exceptions.HTTPError`` keeps working when
clientwright raises on its own authority.
"""

from __future__ import annotations

from ...core.errors import CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ._imports import urllib3


class Urllib3CircuitOpenError(CircuitOpenError, urllib3.exceptions.HTTPError):
    """Circuit open, catchable as urllib3.exceptions.HTTPError."""


class Urllib3DeadlineExceededError(DeadlineExceededError, urllib3.exceptions.TimeoutError):
    """Total deadline exhausted, catchable as urllib3.exceptions.TimeoutError."""


class Urllib3TooManyRedirectsError(TooManyRedirectsError, urllib3.exceptions.MaxRetryError):
    """Owned redirect limit exceeded, catchable as urllib3.exceptions.MaxRetryError.

    ``MaxRetryError.__init__`` demands pool/url positionally, which breaks the
    cooperative super chain - so this class initializes by hand and pins the
    attributes urllib3's ``__str__`` machinery expects.
    """

    def __init__(self, hops: int) -> None:
        Exception.__init__(self, f"Exceeded {hops} redirect hops")
        self.hops = hops
        self.pool = None  # type: ignore[assignment]
        self.url = ""
        self.reason = None

    def __str__(self) -> str:
        return f"Exceeded {self.hops} redirect hops"


def translate_call_error(error: CallError) -> BaseException:
    if isinstance(error, CircuitOpenError):
        return Urllib3CircuitOpenError(error.key, error.retry_after)
    if isinstance(error, DeadlineExceededError):
        return Urllib3DeadlineExceededError(error.total)
    if isinstance(error, TooManyRedirectsError):
        return Urllib3TooManyRedirectsError(error.hops)
    return error


__all__ = [
    "Urllib3CircuitOpenError",
    "Urllib3DeadlineExceededError",
    "Urllib3TooManyRedirectsError",
    "translate_call_error",
]
