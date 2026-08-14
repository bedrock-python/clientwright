# Per-call options

Two facts about a request are known only at the call site, not in the config:

- **The route template.** Metrics need a low-cardinality label. The URL
  `/users/3f2a.../orders/991` is poison for a time-series database; the template
  `/users/{id}/orders/{order_id}` is what you actually want to graph — and only
  the caller knows it.
- **Idempotency of a POST.** The engine will never retry a `POST` on its own.
  But *you* may know this particular POST is safe — it carries an idempotency key,
  or it is a pure computation. That knowledge lives at the call site too.

clientwright gives both facts a per-call channel. The channel's shape follows each
SDK's idiom.

## httpx family: request extensions

httpx carries per-request metadata in `extensions` — so that is where the options
go, with no context managers and no ambient state:

```python
from clientwright.adapters.httpx import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION

await client.post(
    f"/users/{user_id}/orders",
    json=payload,
    extensions={
        ROUTE_EXTENSION: "/users/{id}/orders",
        IDEMPOTENT_EXTENSION: True,
    },
)
```

(`clientwright.adapters.httpx2` exports the same two names for httpx2.)

## aiohttp, requests, urllib3: a context manager

These SDKs have no per-request extension container, so the same channel travels
through a context manager around the call. It is a `ContextVar` underneath —
task-local in async code, thread-local in sync code, inherited by tasks you spawn
inside the block:

=== "aiohttp"

    ```python
    from clientwright.adapters.aiohttp import call_options

    with call_options(route="/users/{id}/orders", idempotent=True):
        await session.post(f"/users/{user_id}/orders", json=payload)
    ```

=== "requests"

    ```python
    from clientwright.adapters.requests import call_options

    with call_options(route="/users/{id}/orders", idempotent=True):
        session.post(url, json=payload)
    ```

=== "urllib3"

    ```python
    from clientwright.adapters.urllib3 import call_options

    with call_options(route="/users/{id}/orders", idempotent=True):
        manager.request("POST", url, json=payload)
    ```

All three imports are the same object — a block applies to whichever clientwright
client sends inside it, uniformly. It is also exported from the package root, which
is the import to prefer when a module talks to more than one adapter:

```python
from clientwright import call_options
```

## What each option does

**`route`** becomes the `route` label on `http_client_requests_total` and the
duration histograms, and — with `CircuitKey.ORIGIN_ROUTE` — part of the breaker
key. Without it the label is `unknown`: everything still works, you just cannot
tell your endpoints apart on a graph. Make it a template, never an interpolated
URL.

**`idempotent=True`** unlocks the [retry gates](retries.md#the-gates-a-retry-must-pass)
for a non-idempotent method. It is a statement about *your* semantics ("repeating
this request is safe"), not a request for more aggressive retrying — all other
gates (attempts, body replayability, deadline, budget) still apply. `False` works
in the other direction: it forbids retrying a normally-idempotent method.

!!! warning "Say it truthfully"

    `idempotent=True` on a POST that charges a credit card without an idempotency
    key is how double charges happen. The flag exists precisely so this decision is
    written where a reviewer can see it, next to the request it describes.
