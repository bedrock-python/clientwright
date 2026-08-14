"""urllib3 exception -> FailureKind classification."""

from __future__ import annotations

from ...core.model import FailureKind
from ._imports import urllib3

_EXC = urllib3.exceptions


def classify_error(exc: BaseException) -> FailureKind:
    if isinstance(exc, _EXC.MaxRetryError):
        # Native retries exhausted (DELEGATED mode): the last real failure is
        # the reason; classify that, not the wrapper.
        if exc.reason is not None:
            return classify_error(exc.reason)
        return FailureKind.UNKNOWN
    # urllib3 v2 subclasses NameResolutionError < NewConnectionError <
    # ConnectTimeoutError, so the ladder MUST test most-specific first or DNS
    # failures and refused connections masquerade as connect timeouts.
    if isinstance(exc, _EXC.NameResolutionError):
        return FailureKind.DNS_ERROR
    if isinstance(exc, _EXC.NewConnectionError):
        return FailureKind.CONNECT_ERROR
    if isinstance(exc, _EXC.ConnectTimeoutError):
        return FailureKind.CONNECT_TIMEOUT
    if isinstance(exc, _EXC.ReadTimeoutError):
        return FailureKind.READ_TIMEOUT
    if isinstance(exc, _EXC.ProxyError):
        return FailureKind.CONNECT_ERROR
    if isinstance(exc, _EXC.SSLError):
        return FailureKind.TLS_ERROR
    if isinstance(exc, _EXC.ProtocolError):
        return FailureKind.DISCONNECTED
    if isinstance(exc, _EXC.DecodeError):
        return FailureKind.BODY_ERROR
    if isinstance(exc, _EXC.EmptyPoolError):
        return FailureKind.POOL_TIMEOUT
    if isinstance(exc, _EXC.PoolError):
        return FailureKind.POOL_TIMEOUT
    if isinstance(exc, (_EXC.TimeoutError, TimeoutError)):
        return FailureKind.TOTAL_TIMEOUT
    return FailureKind.UNKNOWN


__all__ = ["classify_error"]
