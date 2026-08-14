# aiohttp

The high-throughput async stack. aiohttp's integration point is the **client
middleware** chain (aiohttp ≥ 3.12) — the engine runs as a middleware around each
request, backed by a `TraceConfig` for connection-level timings. The client you
get is a genuine `aiohttp.ClientSession`:

```python
import aiohttp
from clientwright import ClientConfig, build

session = build("aiohttp", ClientConfig(service_name="feed", base_url="https://api.example.com"))
assert type(session) is aiohttp.ClientSession

async with session.get("/items") as response:
    items = await response.json()
```

## Per-call options

aiohttp requests carry no extensions container, so the channel is the context
manager:

```python
from clientwright.adapters.aiohttp import call_options

with call_options(route="/items/{id}", idempotent=True):
    await session.post(f"/items/{item_id}", json=payload)
```

## The bypass sentinel

aiohttp allows a caller to *replace* the middleware chain per request —
`session.get(url, middlewares=())` — which would silently disable the entire
engine: no retries, no breaker, no deadline, no metrics. clientwright cannot
prevent that (it is the SDK's public API), so it does the next honest thing:
a `TraceConfig` watches every request, and one that never passed through the
engine increments

```text
http_client_uninstrumented_calls_total{service,adapter="aiohttp",seam="middleware"}
```

Alert on this metric being nonzero. It is the difference between "someone
accidentally turned off resilience" being a dashboard fact versus an incident
review finding.

## Sharp edges the adapter files down

These are things the adapter does *for* you — listed so the config makes sense,
not as chores:

- **The session-total timeout trap.** aiohttp's native `ClientTimeout(total=...)`
  would wrap the *whole* middleware chain — including the engine's retries and
  backoff — turning "10 s per call" into "10 s including all retries the engine
  planned around a different budget". The adapter therefore always builds the
  session with `total=None` and enforces your `timeout.total` itself, per the
  engine's [deadline semantics](../guide/timeouts.md).
- **Timer granularity.** aiohttp rounds timeouts *up* to whole seconds by default
  (`ceil_threshold`); the adapter disables that so a 300 ms budget is 300 ms.
- **The hidden connection retry.** aiohttp silently retries a request once when a
  reused keep-alive connection turns out dead. The adapter turns that off — the
  engine owns retries, and an invisible extra attempt would corrupt both the
  attempt metrics and the idempotency contract.
- **Write timeout**: not expressible per attempt in aiohttp — declared dropped,
  visible in the report.

## Capability notes

- **Boundary: headers.** The aiohttp seam completes when response *headers*
  arrive; the body is read by your code afterwards. Call metrics therefore time
  to-headers, with body read time reported separately as
  `http_client_body_duration_seconds` (measured via the trace hooks). A body
  that fails mid-read after a `200` is an error your code sees, but the call
  metric has honestly already closed — this is declared, not hidden.
- **DNS errors**: natively distinguishable (`dns_error` is real here, unlike
  httpx).
- **Pool wait**: folded by aiohttp into the connect phase — `pool_timeout` is
  declared collapsed into `connect_timeout`.
- **Errors**: dual-family as everywhere — `AiohttpCircuitOpenError` is both a
  `CircuitOpenError` and an `aiohttp.ClientError`.
