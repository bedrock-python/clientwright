"""Engine-driven httpx transports: shared mixin logic bound to httpx bases.

The seam sits UNDER the public API: the returned client is a genuine
``httpx.AsyncClient`` / ``httpx.Client`` and every request that flows through
it - including one sent via a raw ``client.send`` - passes the engine.
"""

from __future__ import annotations

from .._httpx_shared import (
    AsyncEngineTransportMixin,
    AsyncProxyRouterMixin,
    SyncEngineTransportMixin,
    SyncProxyRouterMixin,
)
from ._imports import httpx


class AsyncEngineTransport(AsyncEngineTransportMixin, httpx.AsyncBaseTransport):
    pass


class SyncEngineTransport(SyncEngineTransportMixin, httpx.BaseTransport):
    pass


class AsyncProxyRouterTransport(AsyncProxyRouterMixin, httpx.AsyncBaseTransport):
    pass


class SyncProxyRouterTransport(SyncProxyRouterMixin, httpx.BaseTransport):
    pass


__all__ = [
    "AsyncEngineTransport",
    "AsyncProxyRouterTransport",
    "SyncEngineTransport",
    "SyncProxyRouterTransport",
]
