"""Kernel errors dual-inherited into the httpx2 family.

A user's ``except httpx2.HTTPError`` (or ``except httpx2.TimeoutException``)
keeps working when clientwright raises on its own authority. Class names
mirror the httpx adapter on purpose.
"""

from __future__ import annotations

from ...core.errors import CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from .._httpx_shared import make_error_translator
from ._imports import httpx2


class HttpxCircuitOpenError(CircuitOpenError, httpx2.HTTPError):
    """Circuit open, catchable as httpx2.HTTPError."""


class HttpxDeadlineExceededError(DeadlineExceededError, httpx2.TimeoutException):
    """Total deadline exhausted, catchable as httpx2.TimeoutException."""


class HttpxTooManyRedirectsError(TooManyRedirectsError, httpx2.TooManyRedirects):
    """Owned redirect limit exceeded, catchable as httpx2.TooManyRedirects."""


translate_call_error = make_error_translator(
    HttpxCircuitOpenError, HttpxDeadlineExceededError, HttpxTooManyRedirectsError
)

__all__ = [
    "HttpxCircuitOpenError",
    "HttpxDeadlineExceededError",
    "HttpxTooManyRedirectsError",
    "translate_call_error",
]
