# clientwright

[![PyPI](https://img.shields.io/pypi/v/clientwright?color=blue)](https://pypi.org/project/clientwright/)
[![Python](https://img.shields.io/pypi/pyversions/clientwright)](https://pypi.org/project/clientwright/)
[![License](https://img.shields.io/github/license/bedrock-python/clientwright)](LICENSE)
[![CI](https://github.com/bedrock-python/clientwright/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/bedrock-python/clientwright/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bedrock-python/clientwright/graph/badge.svg)](https://codecov.io/gh/bedrock-python/clientwright)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://bedrock-python.github.io/clientwright/)

One resilience and observability core, many HTTP clients.

**Documentation: <https://bedrock-python.github.io/clientwright/>** — a guided
tour from first client to writing your own adapter; this README is the elevator
version.

`clientwright` is to HTTP clients what [servicewright](https://github.com/bedrock-python/servicewright)
is to services: a zero-dependency kernel of policies (retries, circuit breaking, deadlines,
owned redirects, telemetry) plus adapters that wire it UNDER the public API of popular HTTP
libraries. You get back the **real native client** - a genuine `httpx.AsyncClient`, not a
wrapper - with the whole machinery already working inside it.

```python
import httpx
from clientwright import ClientConfig, TimeoutConfig, build, inspect

config = ClientConfig(
    service_name="google-oauth",
    base_url="https://oauth2.googleapis.com",
    timeout=TimeoutConfig(total=10.0, connect=2.0),
)
client: httpx.AsyncClient = build("httpx", config)
assert type(client) is httpx.AsyncClient  # not a subclass, not a wrapper

response = await client.post("/token", data={...})  # retries, breaker, deadline,
# metrics and spans already apply

handle = inspect(client)  # what actually got applied
print(handle.report.dropped)  # config the adapter could not express
```

## Why

- **Instrumentation under the public API.** The seam sits in the transport
  (httpx), not above the client - taking the raw native client never loses
  logging, metrics, retries or the circuit breaker.
- **One engine, not N reimplementations.** A single attempt loop owns retries,
  redirects, deadlines and telemetry for every adapter; adapters only translate
  messages and send.
- **Capability-honest.** Adapters declare what they can and cannot express
  (`AdapterCapabilities`); anything you configured that cannot be honored lands
  in a `ConfigApplicationReport` - and fails the build under
  `on_unsupported="strict"` instead of silently lying.
- **Owned redirects.** The engine follows redirects itself, so one logical call
  has ONE deadline, ONE retry budget and ONE breaker signal regardless of hops.
- **Total deadline everywhere.** httpx has no wall-clock timeout; clientwright
  enforces one across attempts, backoff sleeps and redirect hops (hard
  cancellation on async, phase clamping on sync).
- **Frozen telemetry schema.** `http_client_*` metric families with mandatory
  `adapter`/`seam` labels - backend divergence is observable on a dashboard,
  not buried in a README.
- **Batteries optional.** `pip install clientwright` has zero dependencies;
  adapters and observability backends are extras with lazy import guards.

## Install

```bash
pip install clientwright[httpx]            # httpx adapter (sync + async)
pip install clientwright[aiohttp]          # aiohttp adapter (async)
pip install clientwright[httpx,metrics]    # + Prometheus backend
pip install clientwright[httpx,tracing]    # + OpenTelemetry backend
```

## Sync twin

```python
from clientwright import build_sync

client = build_sync("httpx", config)  # a genuine httpx.Client
```

The kernel's policies are pure synchronous functions; the same retry decision
code drives both the async and the sync engine.

## Retry and idempotency

Per-call channel via httpx `extensions`:

```python
from clientwright.adapters.httpx import IDEMPOTENT_EXTENSION, ROUTE_EXTENSION

await client.post(
    "/orders",
    json=payload,
    extensions={
        ROUTE_EXTENSION: "/orders",  # low-cardinality metric/breaker label
        IDEMPOTENT_EXTENSION: True,  # this POST is safe to retry
    },
)
```

aiohttp has no request extensions; the same channel is a context manager:

```python
from clientwright.adapters.aiohttp import call_options

with call_options(route="/orders", idempotent=True):
    await session.post("/orders", json=payload)
```

Retries respect `Retry-After`, an origin-wide token-bucket budget (max ~10%
retry traffic by default), body replayability and the remaining deadline.

## DI scope

`ClientRuntime` (circuits, retry budgets, per-origin limiters) must live in
**APP scope** and be shared across REQUEST-scoped clients via
`AdapterDeps(runtime=...)` - otherwise breaker state dies with every request.
With `clientwright[dishka]`, `contrib.dishka.ClientwrightProvider` does both:
APP-scope runtime and a generator provide that closes the client in `finally`.

## Deadline budgets

With `clientwright[deadline]`, the remaining budget of the request being
served caps every outgoing call:

```python
from deadline_budget import BudgetContext

from clientwright import AdapterDeps, build
from clientwright.contrib.deadline import AmbientDeadlineSource, use_budget

deps = AdapterDeps(deadline_source=AmbientDeadlineSource())
client = build("httpx", config, deps)

with use_budget(BudgetContext.create(total_seconds=5.0)):
    await client.get("/users")  # runs with what is left of those 5 seconds
```

## Adapters

| adapter | modes | notes |
|---|---|---|
| `httpx` | sync + async | the reference adapter; cleanest seam |
| `httpx2` | sync + async | Pydantic's httpx successor; identical public names |
| `aiohttp` | async | requires aiohttp >= 3.12 (client middleware) |
| `requests` | sync | closes requests' no-default-timeout hole |
| `urllib3` | sync | home of `RetryMode.DELEGATED` |

Third-party adapters plug in via `register_adapter("name", "module:Class", "module:CAPS")`.

## License

Apache-2.0
