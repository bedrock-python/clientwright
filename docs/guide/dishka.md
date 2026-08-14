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

Resolve the handle (or alias the client type in your own provider for ergonomic
injection):

```python
from typing import Any

import httpx

from clientwright import ClientHandle

handle = await container.get(ClientHandle[Any])
client: httpx.AsyncClient = handle.client
```

The provider is `Scope.APP`: one runtime, one client, built once. The client is
yielded from a generator provide whose `finally` calls `aclose()` — closing the
container closes the client, deterministically.

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

## Several upstreams

One provider serves one upstream. For several, instantiate one provider per
upstream and give each a typed alias so injection sites stay readable:

```python
from dishka import Provider, Scope, provide


class WarehouseClient(Provider):
    scope = Scope.APP

    @provide
    def client(self, handle: ClientHandle[Any]) -> httpx.AsyncClient:
        return handle.client
```

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
