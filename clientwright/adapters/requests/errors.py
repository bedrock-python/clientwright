"""Kernel errors dual-inherited into the requests family.

A user's ``except requests.RequestException`` (or ``except requests.Timeout``)
keeps working when clientwright raises on its own authority.
"""

from __future__ import annotations

from ...core.errors import CallError, CircuitOpenError, DeadlineExceededError, TooManyRedirectsError
from ._imports import requests


class RequestsCircuitOpenError(CircuitOpenError, requests.RequestException):
    """Circuit open, catchable as requests.RequestException."""


class RequestsDeadlineExceededError(DeadlineExceededError, requests.Timeout):
    """Total deadline exhausted, catchable as requests.Timeout."""


class RequestsTooManyRedirectsError(TooManyRedirectsError, requests.TooManyRedirects):
    """Owned redirect limit exceeded, catchable as requests.TooManyRedirects."""


def translate_call_error(error: CallError) -> BaseException:
    if isinstance(error, CircuitOpenError):
        return RequestsCircuitOpenError(error.key, error.retry_after)
    if isinstance(error, DeadlineExceededError):
        return RequestsDeadlineExceededError(error.total)
    if isinstance(error, TooManyRedirectsError):
        return RequestsTooManyRedirectsError(error.hops)
    return error


__all__ = [
    "RequestsCircuitOpenError",
    "RequestsDeadlineExceededError",
    "RequestsTooManyRedirectsError",
    "translate_call_error",
]
