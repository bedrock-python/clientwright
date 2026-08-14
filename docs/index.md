# clientwright

One resilience and observability core. Many HTTP clients. **Zero wrappers.**

You configure retries, circuit breaking, deadlines and telemetry once — and get back
the *real* native client of the library you already use:

```python
import httpx
from clientwright import ClientConfig, TimeoutConfig, build

config = ClientConfig(
    service_name="billing",
    base_url="https://api.payments.example.com",
    timeout=TimeoutConfig(total=10.0, connect=2.0),
)

client = build("httpx", config)
assert type(client) is httpx.AsyncClient  # (1)!

response = await client.get("/invoices/42")  # (2)!
```

1. Not a subclass. Not a proxy object. `type(...) is httpx.AsyncClient` — every
   httpx feature, every third-party integration, every `isinstance` check keeps working.
2. This one line already has: a wall-clock deadline over all attempts, retries with
   jittered backoff and a retry budget, a circuit breaker per origin, redirect
   ownership, Prometheus metrics and an OpenTelemetry span. You wrote none of it.

The same config builds an `aiohttp.ClientSession`, a `requests.Session`, a
`urllib3.PoolManager` or an `httpx2.AsyncClient` — with the same semantics, the same
metric names and the same failure taxonomy on every one of them.

## The idea in one paragraph

Every service ends up with the same checklist: retries that respect `Retry-After`,
a total timeout that actually covers the whole call, a circuit breaker that is not
reset on every request, metrics that look the same on every dashboard. Most teams
re-implement that checklist per HTTP library, in wrappers that quietly stop working
the moment someone reaches for the raw client underneath. clientwright turns the
checklist into one engine and installs it **under** the public API of each library —
in the httpx transport, the aiohttp client middleware, the requests `HTTPAdapter`,
the urllib3 `urlopen`. There is no raw client underneath to reach for. The native
client *is* the instrumented client.

## What you get

<div class="grid cards" markdown>

- **One engine, not N reimplementations**

    A single attempt loop owns retries, redirects, deadlines and telemetry for every
    adapter. Adapters only translate messages and send.

- **A real total deadline**

    httpx has no wall-clock timeout. clientwright enforces one across attempts,
    backoff sleeps and redirect hops — hard cancellation on async, honest phase
    clamping on sync.

- **Capability honesty**

    Every adapter declares what it can and cannot express. Config it cannot honor
    lands in a report — and fails the build under `on_unsupported="strict"` instead
    of silently doing nothing.

- **A frozen metric schema**

    `http_client_*` families with mandatory `adapter` and `seam` labels. Swapping
    aiohttp for httpx changes one label value, not your dashboards.

</div>

## Where to start

- Never used it? Read [Why clientwright](learn/why.md), then build
  [your first client](learn/first-client.md) in about five minutes.
- Migrating a service? The [migration guide](advanced/migration.md) maps raw-SDK and
  legacy-wrapper patterns onto clientwright one by one.
- Looking for a specific knob? The [Guide](guide/configuration.md) has one page per
  concern; the [API Reference](reference/index.md) has the rest.

## Install

```bash
pip install clientwright[httpx]
```

The bare `clientwright` package has **zero dependencies** — adapters and
observability backends are extras. See [Installation](learn/install.md) for the
full matrix.
