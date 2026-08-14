"""Kernel errors dual-inherited into the httpx family.

A user's ``except httpx.HTTPError`` (or ``except httpx.TimeoutException``)
keeps working when clientwright raises on its own authority.
"""

from __future__ import annotations

from ...core.errors import CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from .._httpx_shared import make_error_translator
from ._imports import httpx


class HttpxCircuitOpenError(CircuitOpenError, httpx.HTTPError):
    """Circuit open, catchable as httpx.HTTPError."""


class HttpxDeadlineExceededError(DeadlineExceededError, httpx.TimeoutException):
    """Total deadline exhausted, catchable as httpx.TimeoutException."""


class HttpxTooManyRedirectsError(TooManyRedirectsError, httpx.TooManyRedirects):
    """Owned redirect limit exceeded, catchable as httpx.TooManyRedirects."""


translate_call_error = make_error_translator(
    HttpxCircuitOpenError, HttpxDeadlineExceededError, HttpxTooManyRedirectsError
)

__all__ = [
    "HttpxCircuitOpenError",
    "HttpxDeadlineExceededError",
    "HttpxTooManyRedirectsError",
    "translate_call_error",
]
