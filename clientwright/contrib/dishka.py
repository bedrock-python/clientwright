"""Dishka integration (``[dishka]`` extra): APP-scope runtime, leak-free lifecycle.

Two lessons from the legacy kit are structural here:

- ``ClientRuntime`` (circuits, retry budgets, per-origin limiters) is APP
  scope. A REQUEST-scoped runtime resets breaker state on every request and
  turns the circuit breaker into decoration.
- The client is provided by a GENERATOR provide whose finally closes it - the
  legacy provider parked ``aclose`` on an AsyncExitStack that nothing ever
  closed, leaking a client per request.

Usage::

    container = make_async_container(
        ClientwrightProvider("httpx", config),
        ...,
    )
    handle = await container.get(ClientHandle)
    client: httpx.AsyncClient = handle.client

Known limitation: the ``http_client_circuit_state`` gauge is wired when the
ADAPTER builds the runtime; a runtime built here (to be shared) has no
telemetry listener, so state-change events are not exported as a gauge.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

try:
    from dishka import Provider, Scope, provide
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("Dishka integration requires clientwright[dishka]; install it.") from exc

from ..core.config import ClientConfig
from ..core.contracts.adapter import AdapterDeps, default_deps
from ..core.plan import ClientHandle, ClientRuntime
from ..core.registry import resolve_adapter


class ClientwrightProvider(Provider):
    """One async native client with an APP-scope runtime and guaranteed close.

    For several upstreams, instantiate one provider per upstream in separate
    containers, or subclass and add typed aliases (e.g. a provider returning
    ``httpx.AsyncClient`` from the handle) for ergonomic injection.
    """

    scope = Scope.APP

    def __init__(self, adapter: str, config: ClientConfig, deps: AdapterDeps | None = None) -> None:
        super().__init__()
        self._adapter = adapter
        self._config = config
        self._deps = deps or default_deps()

    @provide
    def client_runtime(self) -> ClientRuntime:
        if self._deps.runtime is not None:
            return self._deps.runtime
        return ClientRuntime.for_config(self._config, clock=self._deps.clock)

    @provide
    async def client_handle(self, runtime: ClientRuntime) -> AsyncIterator[ClientHandle[Any]]:
        adapter = resolve_adapter(self._adapter)()
        handle: ClientHandle[Any] = adapter.build_async(self._config, replace(self._deps, runtime=runtime))
        try:
            yield handle
        finally:
            # The whole point: close travels WITH the provide, not on a stack
            # nobody closes.
            if handle.aclose is not None:
                await handle.aclose()
            elif handle.close is not None:
                handle.close()


__all__ = ["ClientwrightProvider"]
