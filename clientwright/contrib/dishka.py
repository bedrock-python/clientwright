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
    handle = await container.get(ClientHandle[Any])
    client: httpx.AsyncClient = handle.client

Several upstreams in one container are Dishka components: one provider per
upstream, each in its own component, and ``client_type`` for injection sites
that want the native client rather than the handle::

    container = make_async_container(
        ClientwrightProvider("httpx", login_config, component="github-oauth", client_type=httpx.AsyncClient),
        ClientwrightProvider("httpx", api_config, component="github-api", client_type=httpx.AsyncClient),
    )
    api = await container.get(httpx.AsyncClient, component="github-api")

The runtime built here carries the ``http_client_circuit_state`` listener the
way a runtime built by an adapter does; a runtime passed in through
``deps.runtime`` is handed back as it came.
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
from ..core.telemetry.emitter import ClientTelemetry


class ClientwrightProvider(Provider):
    """One async native client with an APP-scope runtime and guaranteed close.

    ``component`` puts everything the provider gives out in a Dishka component,
    which is how several upstreams share one container: resolve with
    ``container.get(..., component="github-api")`` or inject with
    ``Annotated[..., FromComponent("github-api")]``. ``client_type`` also
    provides the native client under that type (``httpx.AsyncClient``, ...),
    the same object the handle holds.
    """

    scope = Scope.APP

    def __init__(
        self,
        adapter: str,
        config: ClientConfig,
        deps: AdapterDeps | None = None,
        *,
        component: str | None = None,
        client_type: type[Any] | None = None,
    ) -> None:
        super().__init__(component=component)
        self._adapter = adapter
        self._config = config
        self._deps = deps or default_deps()
        if client_type is not None:
            self.provide(self._native_client, provides=client_type)

    @provide
    def client_runtime(self) -> ClientRuntime:
        if self._deps.runtime is not None:
            return self._deps.runtime
        # An adapter wires the circuit-state gauge only to a runtime it builds
        # itself; this runtime is built here, so the wiring happens here.
        adapter = resolve_adapter(self._adapter)()
        telemetry = ClientTelemetry(
            service=self._config.service_name,
            adapter=adapter.name,
            seam=adapter.capabilities.seam,
            config=self._config.observability,
            metrics=self._deps.metrics,
            tracer=None,
        )
        return ClientRuntime.for_config(
            self._config, clock=self._deps.clock, circuit_listener=telemetry.circuit_state_changed
        )

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

    def _native_client(self, handle: ClientHandle[Any]) -> Any:
        return handle.client


__all__ = ["ClientwrightProvider"]
