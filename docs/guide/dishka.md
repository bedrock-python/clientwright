# Dependency injection

Two lifecycle rules make or break a resilient client, and both are easy to get
wrong in a DI container:

1. **`ClientRuntime` must be application-scoped.** It holds the circuit breakers,
   retry budgets and per-origin limiters. Rebuild it per request and the breaker
   forgets every failure the moment the request ends — a decoration, not a
   breaker.
2. **The client must actually get closed.** The classic leak is parking `aclose`
   on an exit stack that nothing ever exits: one leaked connection pool per
   request, forever.

With `clientwright[dishka]`, `ClientwrightProvider` encodes both rules so you
cannot re-derive them wrong:

```python
from dishka import make_async_container

from clientwright import ClientConfig
from clientwright.contrib.dishka import ClientwrightProvider

config = ClientConfig(service_name="orders", base_url="https://wh.example.com")
container = make_async_container(
    ClientwrightProvider("httpx", config),
    # ... your other providers
)
```

Resolve the handle:

```python
from typing import Any

import httpx

from clientwright import ClientHandle

handle = await container.get(ClientHandle[Any])
client: httpx.AsyncClient = handle.client
```

Or ask for the client itself. `client_type=` makes the provider also provide
the native client under that type — the same object the handle holds — which
is what an injection site usually wants:

```python
container = make_async_container(
    ClientwrightProvider("httpx", config, client_type=httpx.AsyncClient),
)
client = await container.get(httpx.AsyncClient)
```

The provider is `Scope.APP`: one runtime, one client, built once. The client is
yielded from a generator provide whose `finally` calls `aclose()` — closing the
container closes the client, deterministically. A request scope opening and
closing does not touch it; nothing is parked on a request-scoped exit stack.

## Several upstreams

One provider serves one upstream. A service with several registers one provider
per upstream, each in its own Dishka component, and names the component at the
injection site:

```python
from typing import Annotated

import httpx
from dishka import FromComponent, make_async_container

from clientwright.contrib.dishka import ClientwrightProvider

container = make_async_container(
    ClientwrightProvider("httpx", login_config, component="github-oauth", client_type=httpx.AsyncClient),
    ClientwrightProvider("httpx", api_config, component="github-api", client_type=httpx.AsyncClient),
)


class GitHubOAuthProvider:
    def __init__(
        self,
        login_client: Annotated[httpx.AsyncClient, FromComponent("github-oauth")],
        api_client: Annotated[httpx.AsyncClient, FromComponent("github-api")],
    ) -> None: ...


api = await container.get(httpx.AsyncClient, component="github-api")
```

Dishka resolves a component's dependencies inside that component, so each
provider's client is built on the runtime of its own component: two upstreams
are two breakers, two budgets, two clients, each closed when the container
closes. The cost is that every injection site names the upstream —
`FromComponent("github-api")` or `component="github-api"` — the same trade-off
`grpc_client_kit.dishka` makes. A single upstream stays in the default
component and needs none of this.

## Sharing a runtime across rebuilds

If your service rebuilds containers (tests, config reload, one container per
worker), pass the runtime in explicitly and breaker state survives the rebuild:

```python
from clientwright import AdapterDeps, ClientRuntime

runtime = ClientRuntime.for_config(config)  # build once, own it
deps = AdapterDeps(runtime=runtime)

container = make_async_container(ClientwrightProvider("httpx", config, deps))
```

An upstream that was failing before the rebuild is still remembered as failing
after it — which is the entire point of a breaker.

## The circuit-state gauge

An adapter wires the [`http_client_circuit_state`](observability.md#the-metric-families)
gauge to the runtime it builds. The provider builds the runtime, so it does the
same wiring: with `AdapterDeps(metrics=...)` and `observability.metrics` on, a
breaker transition on a provider-built runtime reaches the gauge exactly as it
does with `build()`. The one runtime that carries no listener is one you built
yourself and passed through `AdapterDeps(runtime=...)` — it is handed back as it
came, so give `ClientRuntime.for_config(config, circuit_listener=...)` a
listener that records into your metrics sink if you want the gauge there too.

## Without dishka

The rules, not the library, are the contract. Any container works if it holds
them: build `ClientRuntime.for_config(config)` once at startup, pass it via
`AdapterDeps(runtime=...)` to every `build()` for that upstream, and close the
client where you tear the application down.

!!! warning "Never request-scope the client"

    A request-scoped client resets breaker and budget state per request *and*
    pays connection-pool warmup per request. If your framework nudges you toward
    request scope, resist — the whole design of `ClientRuntime` exists so the
    long-lived state has one obvious home.
