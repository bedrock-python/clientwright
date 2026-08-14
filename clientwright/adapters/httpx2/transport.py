"""Engine-driven httpx2 transports: shared mixin logic bound to httpx2 bases."""

from __future__ import annotations

from .._httpx_shared import (
    AsyncEngineTransportMixin,
    AsyncProxyRouterMixin,
    SyncEngineTransportMixin,
    SyncProxyRouterMixin,
)
from ._imports import httpx2


class AsyncEngineTransport(AsyncEngineTransportMixin, httpx2.AsyncBaseTransport):
    pass


class SyncEngineTransport(SyncEngineTransportMixin, httpx2.BaseTransport):
    pass


class AsyncProxyRouterTransport(AsyncProxyRouterMixin, httpx2.AsyncBaseTransport):
    pass


class SyncProxyRouterTransport(SyncProxyRouterMixin, httpx2.BaseTransport):
    pass


__all__ = [
    "AsyncEngineTransport",
    "AsyncProxyRouterTransport",
    "SyncEngineTransport",
    "SyncProxyRouterTransport",
]
