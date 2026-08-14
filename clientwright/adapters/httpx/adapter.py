"""The httpx adapter: the shared family builder bound to the httpx SDK.

Constructor traps the shared builder dodges (verified against httpx 0.28):
- ``Client(transport=...)`` silently ignores ``verify``/``http2``/``limits`` -
  everything pool/TLS-related therefore goes into the TRANSPORT constructor;
- a custom transport disables env-proxy support - when asked, proxies are
  parsed from the environment into engine-wrapped routing.
"""

from __future__ import annotations

from .._httpx_shared import FamilyAdapter
from ._imports import httpx
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
    name = "httpx"
    capabilities = CAPABILITIES
    sdk = httpx
    async_normalizer = AsyncHttpxNormalizer
    sync_normalizer = SyncHttpxNormalizer
    async_engine_transport = AsyncEngineTransport
    sync_engine_transport = SyncEngineTransport
    async_proxy_router = AsyncProxyRouterTransport
    sync_proxy_router = SyncProxyRouterTransport
    translate = staticmethod(translate_call_error)


__all__ = ["HttpxAdapter"]
