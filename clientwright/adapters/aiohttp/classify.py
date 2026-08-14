"""aiohttp exception -> FailureKind classification.

aiohttp folds pool waiting, DNS, TCP and TLS into one connect phase, so there
is no POOL_TIMEOUT here (declared as a collapse into CONNECT_TIMEOUT). DNS
failures, unlike httpx, ARE distinguishable natively.
"""

from __future__ import annotations

import asyncio
import ssl

from ...core.model import FailureKind
from ._imports import aiohttp


def _has_ssl_cause(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ssl.SSLError, ssl.CertificateError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def classify_error(exc: BaseException) -> FailureKind:
    if isinstance(exc, asyncio.CancelledError):
        return FailureKind.CANCELLED
    if isinstance(exc, aiohttp.ConnectionTimeoutError):
        return FailureKind.CONNECT_TIMEOUT
    if isinstance(exc, aiohttp.SocketTimeoutError):
        return FailureKind.READ_TIMEOUT
    if isinstance(exc, aiohttp.ServerTimeoutError):
        return FailureKind.CONNECT_TIMEOUT
    if isinstance(exc, aiohttp.ClientSSLError):
        # Covers ClientConnectorCertificateError and ClientConnectorSSLError;
        # must sit ABOVE ClientConnectorError, which it subclasses in
        # aiohttp>=3.14 - below it the branch is dead code.
        return FailureKind.TLS_ERROR
    if isinstance(exc, aiohttp.ClientConnectorDNSError):
        return FailureKind.DNS_ERROR
    if isinstance(exc, aiohttp.ClientConnectorError):
        return FailureKind.TLS_ERROR if _has_ssl_cause(exc) else FailureKind.CONNECT_ERROR
    if isinstance(exc, aiohttp.ServerDisconnectedError):
        return FailureKind.DISCONNECTED
    if isinstance(exc, aiohttp.ClientOSError):
        return FailureKind.CONNECT_ERROR
    if isinstance(exc, aiohttp.ClientPayloadError):
        return FailureKind.BODY_ERROR
    if isinstance(exc, aiohttp.ClientResponseError):
        return FailureKind.PROTOCOL_ERROR
    if isinstance(exc, TimeoutError):
        return FailureKind.TOTAL_TIMEOUT
    return FailureKind.UNKNOWN


__all__ = ["classify_error"]
