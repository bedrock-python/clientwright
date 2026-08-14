# Adapters

Adapter packages import their SDK, so their API docs cannot be auto-rendered in
an extras-free build. Their public surfaces are small and intentionally uniform;
this page is the complete list.

## Per-adapter exports

Every adapter package exports its adapter class, its per-call channel, and its
dual-family error trio (each inherits both the clientwright error and the SDK's
native family):

| Package | Per-call channel | Errors |
|---|---|---|
| `clientwright.adapters.httpx` | `ROUTE_EXTENSION`, `IDEMPOTENT_EXTENSION` (request extensions) | `HttpxCircuitOpenError`, `HttpxDeadlineExceededError`, `HttpxTooManyRedirectsError` |
| `clientwright.adapters.httpx2` | same names as httpx | same class names as httpx, inheriting `httpx2`'s family |
| `clientwright.adapters.aiohttp` | `call_options(route=..., idempotent=...)` | `AiohttpCircuitOpenError`, `AiohttpDeadlineExceededError`, `AiohttpTooManyRedirectsError` |
| `clientwright.adapters.requests` | `call_options(...)` | `RequestsCircuitOpenError`, `RequestsDeadlineExceededError`, `RequestsTooManyRedirectsError` |
| `clientwright.adapters.urllib3` | `call_options(...)` | `Urllib3CircuitOpenError`, `Urllib3DeadlineExceededError`, `Urllib3TooManyRedirectsError` |

The three `call_options` are the same object — the shared ambient channel
documented in [Core → Per-call options](core.md#per-call-options).

## Capability records

Each adapter's `capabilities` module is zero-dependency and importable without
the SDK — that is what feeds `clientwright.capabilities_matrix()`:

```python
from clientwright.adapters.aiohttp.capabilities import CAPABILITIES
```

## Observability backends

::: clientwright.adapters.observability

The two backends live behind extras and are exposed lazily at the package root:

```python
from clientwright.adapters.observability import (
    OpenTelemetryTracer,  # clientwright[tracing]
    PrometheusClientMetrics,  # clientwright[metrics]
)
```

`PrometheusClientMetrics(registry=..., prefix=...)` implements
`ClientMetricsProtocol` over `prometheus_client`, with the frozen names from
`clientwright.core.telemetry.names`. `OpenTelemetryTracer(tracer_provider=...)`
implements `TracerProtocol`, emitting one `CLIENT` span per logical call and
propagating context from it.
