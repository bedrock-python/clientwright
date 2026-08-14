"""requests exception -> FailureKind classification.

requests rewrites most urllib3 failures into its own hierarchy and folds
protocol violations into ConnectionError; the cause chain is inspected to tell
a DNS failure or a mid-stream disconnect from a refused connection.
"""

from __future__ import annotations

import http.client
import ssl

from ...core.model import FailureKind
from ._imports import requests, urllib3


def _cause_chain(exc: BaseException) -> list[BaseException]:
    seen: set[int] = set()
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        for nested in getattr(current, "args", ()):
            if isinstance(nested, BaseException) and id(nested) not in seen:
                chain.append(nested)
        current = current.__cause__ or current.__context__
    return chain


def _classify_connection_error(exc: requests.exceptions.ConnectionError) -> FailureKind:
    for cause in _cause_chain(exc):
        if isinstance(cause, urllib3.exceptions.NameResolutionError):
            return FailureKind.DNS_ERROR
        if isinstance(cause, (urllib3.exceptions.ProtocolError, http.client.RemoteDisconnected, ConnectionResetError)):
            return FailureKind.DISCONNECTED
        if isinstance(cause, (ssl.SSLError, ssl.CertificateError)):
            return FailureKind.TLS_ERROR
    return FailureKind.CONNECT_ERROR


def classify_error(exc: BaseException) -> FailureKind:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return FailureKind.CONNECT_TIMEOUT
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return FailureKind.READ_TIMEOUT
    if isinstance(exc, requests.exceptions.Timeout):
        return FailureKind.TOTAL_TIMEOUT
    if isinstance(exc, requests.exceptions.SSLError):
        return FailureKind.TLS_ERROR
    if isinstance(exc, requests.exceptions.ProxyError):
        return FailureKind.CONNECT_ERROR
    if isinstance(exc, (requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError)):
        return FailureKind.BODY_ERROR
    if isinstance(exc, requests.exceptions.ConnectionError):
        return _classify_connection_error(exc)
    if isinstance(exc, TimeoutError):
        return FailureKind.TOTAL_TIMEOUT
    return FailureKind.UNKNOWN


__all__ = ["classify_error"]
