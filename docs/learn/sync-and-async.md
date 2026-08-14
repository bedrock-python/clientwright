# Sync and async

clientwright is not "an async library with a sync shim". The policy code — retry
decisions, timeout planning, the circuit-breaker state machine — is written as pure
synchronous functions, and two thin engines drive it: an async attempt loop and a
sync attempt loop. Both flavors are first-class.

## Two builders

=== "async"

    ```python
    from clientwright import build

    client = build("httpx", config)  # httpx.AsyncClient
    session = build("aiohttp", config)  # aiohttp.ClientSession
    ```

=== "sync"

    ```python
    from clientwright import build_sync

    client = build_sync("httpx", config)  # httpx.Client
    session = build_sync("requests", config)  # requests.Session
    manager = build_sync("urllib3", config)  # urllib3.PoolManager
    ```

Same `ClientConfig`, same defaults, same metric names. A service can run its async
API handlers on aiohttp and a sync worker on requests from the *same* configuration
module, and the two will retry, break and report identically.

## The one honest difference: hard vs soft deadlines

An async runtime can cancel a stuck attempt: the engine wraps every send in a
cancellation scope, so `timeout.total` is a **hard** wall — a hung read dies the
moment the budget runs out, classified as `total_timeout`.

A sync runtime cannot cancel a blocked socket read. The sync engine therefore
enforces the total as a **soft** deadline: it clamps every phase timeout of every
attempt to the remaining budget and re-checks the wall clock at attempt boundaries.
You still never wait meaningfully longer than `total` — but the failure arrives as
the clamped phase (`read_timeout` from the SDK), not as an abstract deadline error.

This is deliberately *not* papered over. Sync adapters declare
`DEADLINE_HARD: absent` in their [capability record](../guide/capabilities.md), and
the metric outcome tells you which mechanism fired. Pretending a sync deadline is
hard would be exactly the kind of lie clientwright exists to avoid.

!!! tip "Same origin, both flavors"

    `build()` and `build_sync()` accept the same `AdapterDeps`. If you pass a shared
    [`ClientRuntime`](../guide/dishka.md), the async and sync clients of one upstream
    share a circuit breaker and a retry budget — the upstream's health is one fact,
    not two.

## Where each adapter stands

| Adapter | async | sync |
|---|---|---|
| `httpx` | ✅ `httpx.AsyncClient` | ✅ `httpx.Client` |
| `httpx2` | ✅ `httpx2.AsyncClient` | ✅ `httpx2.Client` |
| `aiohttp` | ✅ `aiohttp.ClientSession` | — |
| `requests` | — | ✅ `requests.Session` |
| `urllib3` | — | ✅ `urllib3.PoolManager` |

Asking an adapter for a flavor it does not have raises at build time with the list
of adapters that do.
