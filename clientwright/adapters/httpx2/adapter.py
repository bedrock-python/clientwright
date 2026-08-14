"""The httpx2 adapter: the shared family builder bound to the httpx2 SDK.

The class keeps the httpx adapter's name (``HttpxAdapter``) on purpose:
public names in the paired adapters are identical, so migrating a service is
one extra and one import path. The registry name is ``"httpx2"``.
"""

from __future__ import annotations

from .._httpx_shared import FamilyAdapter
from ._imports import httpx2
from .capabilities import CAPABILITIES
from .errors import translate_call_error
from .normalize import AsyncHttpxNormalizer
from .normalize_sync import SyncHttpxNormalizer
from .transport import (
    AsyncEngineTransport,
    AsyncProxyRouterTransport,
    SyncEngineTransport,
    SyncProxyRouterTransport,
)


class HttpxAdapter(FamilyAdapter):
    name = "httpx2"
    capabilities = CAPABILITIES
    sdk = httpx2
    async_normalizer = AsyncHttpxNormalizer
    sync_normalizer = SyncHttpxNormalizer
    async_engine_transport = AsyncEngineTransport
    sync_engine_transport = SyncEngineTransport
    async_proxy_router = AsyncProxyRouterTransport
    sync_proxy_router = SyncProxyRouterTransport
    translate = staticmethod(translate_call_error)


__all__ = ["HttpxAdapter"]
