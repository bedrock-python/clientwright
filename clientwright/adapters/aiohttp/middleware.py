"""The engine-driven client middleware.

The seam sits UNDER the public API: the returned client is a genuine
``aiohttp.ClientSession`` and every request that flows through it passes the
engine - unless the caller writes ``middlewares=()``, which aiohttp treats as
a full replacement; the TraceConfig sentinel counts those bypasses.

The middleware is a long-lived hashable object on purpose: aiohttp caches the
built middleware chain per ``(handler, middlewares)`` key, so a per-request
closure would thrash that LRU on every call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ...core.contracts.message import RequestView
from ...core.engine.aio import AsyncAttemptEngine
from ._imports import URL, aiohttp
from .trace import ENGINE_ACTIVE
from .views import AiohttpRequestView

type ClientHandler = Callable[[aiohttp.ClientRequest], Awaitable[aiohttp.ClientResponse]]


class ProxyRouter:
    """Per-hop proxy choice: explicit URL, or environment proxies by scheme."""

    __slots__ = ("_by_scheme", "_explicit", "_no_proxy_hosts")

    def __init__(
        self,
        explicit: str | None,
        by_scheme: Mapping[str, str] | None = None,
        no_proxy_hosts: tuple[str, ...] = (),
    ) -> None:
        self._explicit = URL(explicit) if explicit is not None else None
        self._by_scheme = {scheme: URL(url) for scheme, url in (by_scheme or {}).items()}
        self._no_proxy_hosts = no_proxy_hosts

    def _bypasses(self, host: str) -> bool:
        for entry in self._no_proxy_hosts:
            candidate = entry.lstrip(".")
            if host == candidate or host.endswith("." + candidate):
                return True
        return False

    def apply(self, request: aiohttp.ClientRequest) -> None:
        if self._explicit is not None:
            request.proxy = self._explicit
            return
        host = request.url.host or ""
        if self._bypasses(host):
            request.proxy = None
            return
        request.proxy = self._by_scheme.get(request.url.scheme)


async def _clear_body(request: aiohttp.ClientRequest) -> None:
    """Drop the body the aiohttp way: ``update_body`` closes the old payload."""
    update = getattr(request, "update_body", None)
    if update is None:  # pragma: no cover - update_body exists on aiohttp>=3.12
        request.body = b""
        return
    result = update(b"")
    if result is not None and hasattr(result, "__await__"):
        await result


class EngineMiddleware:
    """One logical call per invocation; the engine owns retries, redirects, deadline."""

    __slots__ = ("_engine", "_proxy")

    def __init__(self, engine: AsyncAttemptEngine, proxy: ProxyRouter | None = None) -> None:
        self._engine = engine
        self._proxy = proxy

    async def _send(self, view: RequestView, handler: ClientHandler) -> aiohttp.ClientResponse:
        native = view.native
        if isinstance(view, AiohttpRequestView) and view.pending_empty_body:
            await _clear_body(native)
            view.pending_empty_body = False
        if self._proxy is not None:
            # Inside the engine seam: every owned-redirect hop re-routes.
            self._proxy.apply(native)
        return await handler(native)

    async def __call__(self, request: aiohttp.ClientRequest, handler: ClientHandler) -> aiohttp.ClientResponse:
        token = ENGINE_ACTIVE.set(True)
        try:

            async def send(view: RequestView) -> aiohttp.ClientResponse:
                return await self._send(view, handler)

            response = await self._engine.run(request, send)
            assert isinstance(response, aiohttp.ClientResponse)
            return response
        finally:
            ENGINE_ACTIVE.reset(token)


__all__ = ["EngineMiddleware", "ProxyRouter"]
